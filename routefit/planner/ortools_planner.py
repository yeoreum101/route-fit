"""③-b OR-Tools 제약 최적화 코스 생성 (Phase 2).

'상금이 걸린 시간창 경로 문제'로 모델링한다.
- Must Visit: 반드시 방문하는 노드 (고정 시각이면 시간창이 한 점)
- AI Discover 후보: 빼도 되지만 빼면 그 장소의 가치만큼 벌점(disjunction)
- 시간 차원: 영업시간 시간창 + 종료 희망 시각 soft 상한(시간 초과 페널티)
- 예산 · 유형별 상한 · 최대 장소 수: 용량 차원
"""
import logging
from typing import Optional

from ..config import LIMITS, WEIGHTS
from .core import Node, PlanError, Travel, Window, back_to_back_cafes, meal_slot
from .greedy import plan_greedy

log = logging.getLogger(__name__)

SCALE = 1000  # OR-Tools 는 정수만 다루므로 점수를 1000배 한다
COST_UNIT = 100  # 예산 차원 단위(원)


def plan_ortools(
    musts: list[Node],
    candidates: list[Node],
    day_start: int,
    day_end: int,
    budget: Optional[int],
    travel: Travel,
    time_limit_s: int = 2,
) -> list[Node]:
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError:
        log.warning("ortools 미설치: 그리디로 대체")
        return plan_greedy(musts, candidates, day_start, day_end, budget, travel)

    hard_end = day_end + LIMITS.overtime_grace_min

    def windows(n: Node, slot: Optional[int] = None) -> list[Window]:
        """하루 안으로 자른 시작 가능 구간. slot 을 주면 그 끼니의 구간만."""
        if n.fixed_start is not None:
            return [(n.fixed_start, n.fixed_start)]
        out = [(max(lo, day_start), min(hi, hard_end - n.stay)) for lo, hi in n.windows]
        return [(lo, hi) for lo, hi in out if lo <= hi and (slot is None or meal_slot(lo) == slot)]

    # 하루 안에 들어갈 수 없는 후보와 가치가 없는 후보는 미리 뺀다.
    # 식당은 끼니마다 따로 한 개씩 노드를 만들고, 그중 하나만 고르게 한다(disjunction).
    nodes: list[Node] = []
    node_windows: list[list[Window]] = []
    slots: list[Optional[int]] = []  # 식당 노드의 끼니
    groups: list[list[int]] = []  # 같은 장소의 노드 번호들 (AI 추천 후보만)

    def add(n: Node, w: list[Window], slot: Optional[int] = None) -> int:
        nodes.append(n)
        node_windows.append(w)
        slots.append(slot)
        return len(nodes)

    for n in musts:
        add(n, windows(n))
    for n in candidates:
        if n.value <= 0:
            continue
        meal_slots = range(len(LIMITS.meal_windows)) if n.meal else [None]
        group = [add(n, windows(n, slot), slot) for slot in meal_slots if windows(n, slot)]
        if group:
            groups.append(group)
    size = len(nodes) + 1  # 0번은 출발·도착용 가상 노드(어디서든 이동시간 0)

    manager = pywrapcp.RoutingIndexManager(size, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    minutes = [[0] * size for _ in range(size)]
    for i, a in enumerate(nodes, 1):
        for j, b in enumerate(nodes, 1):
            if i != j:
                minutes[i][j] = travel(a, b)
    stay = [0] + [n.stay for n in nodes]

    def arc_cost(i, j):
        return round(SCALE * WEIGHTS.travel_per_min * minutes[manager.IndexToNode(i)][manager.IndexToNode(j)])

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(arc_cost))

    def elapsed(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return stay[a] + minutes[a][b]

    routing.AddDimension(routing.RegisterTransitCallback(elapsed), 24 * 60, hard_end, False, "Time")
    time = routing.GetDimensionOrDie("Time")
    time.CumulVar(routing.Start(0)).SetRange(day_start, hard_end)
    time.CumulVar(routing.End(0)).SetRange(day_start, hard_end)
    time.SetCumulVarSoftUpperBound(routing.End(0), day_end, round(SCALE * WEIGHTS.overtime_per_min))
    time.SetSlackCostCoefficientForAllVehicles(round(SCALE * WEIGHTS.wait_per_min))  # 일정 사이 빈 시간
    for k, (n, w) in enumerate(zip(nodes, node_windows), 1):
        if not w:
            raise PlanError(f"'{n.place.name}' 을(를) 하루 일정 안에 넣을 수 없습니다.")
        cumul = time.CumulVar(manager.NodeToIndex(k))
        cumul.SetRange(w[0][0], w[-1][1])
        for (_, prev_hi), (next_lo, _) in zip(w, w[1:]):  # 브레이크 타임처럼 구간 사이에 비는 시각
            if prev_hi + 1 <= next_lo - 1:
                cumul.RemoveInterval(prev_hi + 1, next_lo - 1)

    def add_capacity(name: str, demand: list[int], capacity: int):
        cb = routing.RegisterUnaryTransitCallback(lambda i: demand[manager.IndexToNode(i)])
        routing.AddDimension(cb, 0, capacity, True, name)

    is_ai = [0] + [0 if n.mandatory else 1 for n in nodes]
    add_capacity("Stops", is_ai, LIMITS.max_ai_stops)
    for cat, cap in LIMITS.category_caps:
        add_capacity(f"Cap_{cat}", [0] + [int(not n.mandatory and n.place.category == cat) for n in nodes], cap)
    if budget is not None:
        add_capacity("Budget", [0] + [-(-n.cost // COST_UNIT) for n in nodes], budget // COST_UNIT)
    for slot in range(len(LIMITS.meal_windows)):  # 한 끼에 식당 한 곳
        add_capacity(f"Meal_{slot}", [0] + [int(not n.mandatory and s == slot) for n, s in zip(nodes, slots)], 1)

    for i, a in enumerate(nodes, 1):  # 카페 다음에 바로 카페로 가는 길은 없앤다
        for j, b in enumerate(nodes, 1):
            if i != j and back_to_back_cafes(a, b):
                routing.NextVar(manager.NodeToIndex(i)).RemoveValue(manager.NodeToIndex(j))

    for group in groups:
        value = nodes[group[0] - 1].value
        routing.AddDisjunction([manager.NodeToIndex(k) for k in group], round(SCALE * value), 1)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(time_limit_s)
    solution = routing.SolveWithParameters(params)
    if solution is None:
        log.warning("OR-Tools 해 없음: 그리디로 대체")
        return plan_greedy(musts, candidates, day_start, day_end, budget, travel)

    route = []
    index = solution.Value(routing.NextVar(routing.Start(0)))
    while not routing.IsEnd(index):
        route.append(nodes[manager.IndexToNode(index) - 1])
        index = solution.Value(routing.NextVar(index))
    return route
