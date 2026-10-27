"""③ 코스 생성기 공통부: 노드, 시간표 계산(실행 가능성 검사), 추천 점수식."""
from dataclasses import dataclass
from typing import Callable, Optional

from ..config import LIMITS, WEIGHTS, Limits, Weights
from ..models import Place, to_min


class PlanError(Exception):
    """Must Visit 을 지키는 코스를 만들 수 없을 때."""


Window = tuple[int, int]  # 방문을 시작할 수 있는 (가장 이른, 가장 늦은) 시각


def start_windows(place: Place, stay: int, meal: bool = False, limits: Limits = LIMITS) -> list[Window]:
    """영업시간에서 브레이크 타임을 빼고, 그 안에서 stay 분을 머물 수 있는 시작 시각 구간들.
    meal 이면 식사 시간대와 겹치는 부분만 남긴다."""
    opens = [(to_min(place.open), to_min(place.close))]
    if place.break_start and place.break_end:
        opens = [(opens[0][0], to_min(place.break_start)), (to_min(place.break_end), opens[0][1])]
    windows = [(o, c - stay) for o, c in opens if c - stay >= o]
    if meal:
        windows = [
            (max(lo, m0), min(hi, m1))
            for lo, hi in windows
            for _, m0, m1 in limits.meal_windows
            if max(lo, m0) <= min(hi, m1)
        ]
    return sorted(windows)


def meal_slot(start: int, limits: Limits = LIMITS) -> Optional[int]:
    """start 가 몇 번째 식사 시간대(0=점심, 1=저녁)에 드는지."""
    return next((i for i, (_, m0, m1) in enumerate(limits.meal_windows) if m0 <= start <= m1), None)


@dataclass
class Node:
    """코스에 들어갈 수 있는 장소 1곳. 시간은 모두 자정 기준 분."""

    place: Place
    windows: list[Window]  # start_windows()
    stay: int
    cost: int
    meal: bool = False  # 식사 시간대 식당: 한 끼(meal_slot)에 한 곳
    mandatory: bool = False  # Must Visit: 절대 제외하지 않는다
    fixed_start: Optional[int] = None  # 경기·공연처럼 시작 시각이 고정된 경우
    taste: float = 0.0  # 후보 내 0~1 로 정규화한 취향 적합도
    companion_fit: bool = False  # 문장의 동행이 이 장소의 '어울리는 동행' 태그에 있다
    similarity: float = 0.0  # 코사인 유사도 원값

    @property
    def id(self) -> str:
        return self.place.id

    @property
    def lat(self) -> float:
        return self.place.lat

    @property
    def lng(self) -> float:
        return self.place.lng

    @property
    def value(self) -> float:
        """이 장소를 코스에 넣었을 때 얻는 가치 (이동 부담 반영 전)."""
        return (
            WEIGHTS.taste * self.taste
            + WEIGHTS.local * self.place.local_score
            + WEIGHTS.companion * self.companion_fit
            - WEIGHTS.stop_cost
        )


@dataclass
class Visit:
    node: Node
    arrive: int
    start: int
    end: int
    travel: int  # 직전 장소에서의 이동시간


Travel = Callable[[Node, Node], int]


def back_to_back_cafes(a: Node, b: Node) -> bool:
    """카페 다음에 바로 카페. 둘 다 사용자가 고른 곳이면 막지 않는다."""
    return a.place.category == b.place.category == "cafe" and not (a.mandatory and b.mandatory)


def _earliest_start(node: Node, arrive: int, meals_taken: set[int]) -> Optional[int]:
    for lo, hi in node.windows:
        if arrive > hi:
            continue
        start = max(arrive, lo)
        if node.meal and meal_slot(start) in meals_taken:
            continue  # 이 끼니에는 이미 식당이 있다. 다음 끼니까지 기다린다
        return start
    return None


def schedule(route: list[Node], day_start: int, hard_end: int, travel: Travel) -> Optional[list[Visit]]:
    """순서가 정해진 route 의 시간표. 영업시간·브레이크 타임·식사 시간대·고정 시각·종료 한계를 못 지키면 None."""
    visits: list[Visit] = []
    meals_taken: set[int] = set()
    t = day_start
    for i, node in enumerate(route):
        if i and back_to_back_cafes(route[i - 1], node):
            return None
        move = travel(route[i - 1], node) if i else 0
        arrive = t + move
        if node.fixed_start is not None:
            if arrive > node.fixed_start:
                return None
            start = node.fixed_start
        else:
            start = _earliest_start(node, arrive, meals_taken)
            if start is None:
                return None
            if node.meal:
                meals_taken.add(meal_slot(start))
        end = start + node.stay
        if end > hard_end:
            return None
        visits.append(Visit(node, arrive, start, end, move))
        t = end

    # 고정 일정(경기 시작 등) 직전에 생기는 공백을 없애도록 앞 일정을 뒤로 당긴다.
    for i in range(len(visits) - 2, -1, -1):
        v, nxt = visits[i], visits[i + 1]
        if v.node.fixed_start is not None:
            continue
        # 지금 시작 시각이 든 구간 안에서만 당긴다 (브레이크 타임을 넘거나 끼니가 바뀌지 않게)
        window_end = next(hi for lo, hi in v.node.windows if lo <= v.start <= hi)
        latest = min(nxt.start - nxt.travel - v.node.stay, window_end)
        if latest > v.start:
            v.start, v.end = latest, latest + v.node.stay
    for i, v in enumerate(visits):
        v.arrive = visits[i - 1].end + v.travel if i else v.start
    return visits


def objective(visits: list[Visit], day_end: int, weights: Weights = WEIGHTS) -> float:
    """추천 점수식: 취향 적합도 + 지역상권 기여도 + 동행 적합도 - 이동 부담 - 빈 시간 - 시간 초과 페널티."""
    value = sum(v.node.value for v in visits if not v.node.mandatory)
    travel = sum(v.travel for v in visits)
    wait = sum(v.start - v.arrive for v in visits)
    overtime = max(0, visits[-1].end - day_end) if visits else 0
    return (
        value
        - weights.travel_per_min * travel
        - weights.wait_per_min * wait
        - weights.overtime_per_min * overtime
    )


def within_caps(route: list[Node], budget: Optional[int], limits: Limits = LIMITS) -> bool:
    """예산 · AI 추천 장소 수 · 유형별 상한."""
    if budget is not None and sum(n.cost for n in route) > budget:
        return False
    ai = [n for n in route if not n.mandatory]
    if len(ai) > limits.max_ai_stops:
        return False
    return all(sum(n.place.category == cat for n in ai) <= cap for cat, cap in limits.category_caps)
