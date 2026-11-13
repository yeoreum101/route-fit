"""③ 코스 생성기 공통부: 노드, 시간표 계산(실행 가능성 검사), 추천 점수식."""
import itertools
from dataclasses import dataclass, replace
from typing import Callable, Optional

from ..config import LIMITS, WEIGHTS, Limits, Weights
from ..models import Place, to_min


class PlanError(Exception):
    """Must Visit 을 지키는 코스를 만들 수 없을 때."""


Window = tuple[int, int]  # 방문을 시작할 수 있는 (가장 이른, 가장 늦은) 시각


def start_windows(
    place: Place, stay: int, meal: bool = False, skip_meals: tuple[str, ...] = (), limits: Limits = LIMITS
) -> list[Window]:
    """영업시간에서 브레이크 타임을 빼고, 그 안에서 stay 분을 머물 수 있는 시작 시각 구간들.
    meal 이면 식사 시간대와 겹치는 부분만 남긴다. skip_meals("점심"·"저녁")의 시간대는 뺀다."""
    opens = [(to_min(place.open), to_min(place.close))]
    if place.break_start and place.break_end:
        opens = [(opens[0][0], to_min(place.break_start)), (to_min(place.break_end), opens[0][1])]
    windows = [(o, c - stay) for o, c in opens if c - stay >= o]
    if meal:
        windows = [
            (max(lo, m0), min(hi, m1))
            for lo, hi in windows
            for name, m0, m1 in limits.meal_windows
            if name not in skip_meals and max(lo, m0) <= min(hi, m1)
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
    origin: bool = False  # 출발 위치: 하루 시작 시각에 머무는 시간 0 으로 맨 앞에 둔다
    taste: float = 0.0  # 후보 내 0~1 로 정규화한 취향 적합도
    companion_fit: bool = False  # 문장의 동행이 이 장소의 '어울리는 동행' 태그에 있다
    activity_fit: bool = False  # 문장에서 말한 할 거리가 이 장소의 '할 거리' 태그에 있다
    similarity: float = 0.0  # 코사인 유사도 원값
    popularity: float = 0.0  # 쏠림 감점(가치에서 뺀다). 최근 코스 등장률이 목표를 넘는 만큼 × 가중치 (config.POPULARITY_*)

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
            + WEIGHTS.activity * self.activity_fit
            - self.popularity
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


_MEAL_CAFE = {("food", "cafe"), ("cafe", "food")}


def counts_as_neighbor(middle: Node, side: Node) -> bool:
    """밥·카페 번갈아 규칙에서 가운데 장소의 이웃으로 셀지. 가운데와 이웃이 둘 다 사용자가 고른 곳이면 세지 않는다."""
    return (middle.place.category, side.place.category) in _MEAL_CAFE and not (middle.mandatory and side.mandatory)


def meal_cafe_zigzag(a: Node, b: Node, c: Node) -> bool:
    """식당→카페→식당 또는 카페→식당→카페로 바로 이어지는지. 먹고 마시기만 반복하지 않게 막는다."""
    return counts_as_neighbor(b, a) and counts_as_neighbor(b, c)


def meal_gap_applies(a: Node, b: Node) -> bool:
    """두 곳 다 식당이라 사이에 식사 간격(min_meal_gap)을 둬야 하는지. 둘 다 사용자가 고른 곳이면 두지 않는다."""
    return a.place.category == b.place.category == "food" and not (a.mandatory and b.mandatory)


def ceil_step(t: int, step: int = LIMITS.time_step) -> int:
    return -(-t // step) * step


def floor_step(t: int, step: int = LIMITS.time_step) -> int:
    return t // step * step


def _finish(node: Node, start: int) -> int:
    """나가는 시각. 도착(시작)은 실제 시각 그대로 두고, 나가는 시각만 10분 단위(LIMITS.time_step)로 올려
    따르기 쉽게 한다(남는 몇 분은 그 장소에 조금 더 머문다). 시각을 정한 일정은 정한 대로, 올리면 영업 종료·
    브레이크 타임을 넘는 경우도 그대로 둔다."""
    end = start + node.stay
    if node.fixed_start is not None:
        return end
    limit = next((hi + node.stay for lo, hi in node.windows if lo <= start <= hi), end)
    rounded = ceil_step(end)
    return rounded if rounded <= limit else end


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
        if i >= 2 and meal_cafe_zigzag(route[i - 2], route[i - 1], node):
            return None
        move = travel(route[i - 1], node) if i else 0
        arrive = t + move
        # 앞 식당에서 나온 지 얼마 안 됐으면 식사 간격이 찰 때까지 기다린다
        not_before = max(
            (v.end + LIMITS.min_meal_gap for v in visits if meal_gap_applies(v.node, node)), default=arrive
        )
        if node.fixed_start is not None:
            if max(arrive, not_before) > node.fixed_start:
                return None
            start = node.fixed_start
        else:
            start = _earliest_start(node, max(arrive, not_before), meals_taken)
            if start is None:
                return None
            if node.meal:
                meals_taken.add(meal_slot(start))
        end = _finish(node, start)
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
        # 나가는 시각(10분 단위)이 다음 일정에 늦지 않고, 다음 식당과의 식사 간격도 지키는 범위에서
        latest_end = nxt.start - nxt.travel
        for later in visits[i + 1 :]:
            if meal_gap_applies(v.node, later.node):
                latest_end = min(latest_end, later.start - LIMITS.min_meal_gap)
        latest = min(floor_step(latest_end) - v.node.stay, window_end)
        if latest > v.start:
            v.start, v.end = latest, _finish(v.node, latest)
    # 출발 위치에서는 첫 장소에 늦지 않을 만큼 늦게(10분 단위) 나선다. 하루 시작에 나가서 문 열기를 기다리지 않게.
    if len(visits) > 1 and visits[0].node.origin:
        first = visits[1]
        leave = max(visits[0].start, floor_step(first.start - first.travel))
        visits[0].start = visits[0].end = leave
    for i, v in enumerate(visits):
        v.arrive = visits[i - 1].end + v.travel if i else v.start
        # 앞 일정이 10분 단위로 끝나서 몇 분(time_step 미만) 일찍 도착하면, 기다리지 않고 도착한 시각에 시작한다
        # (머무는 시간이 그만큼 늘 뿐 나가는 시각은 그대로). 영업시간·끼니가 같은 구간 안일 때만.
        early = v.start - v.arrive
        if v.node.fixed_start is None and 0 < early < LIMITS.time_step:
            window = next(((lo, hi) for lo, hi in v.node.windows if lo <= v.start <= hi), None)
            same_meal = not v.node.meal or meal_slot(v.arrive) == meal_slot(v.start)
            if window and window[0] <= v.arrive and same_meal:
                v.start = v.arrive
        # 시작은 5분 단위로 올린다(12:17 -> 12:20). 나가는 시각이 10분 단위라 머무는 시간이 5분 단위로 보인다.
        # 영업·끼니 구간 안이고 원래 머무는 시간이 남을 때만
        aligned = ceil_step(v.start, LIMITS.start_step)
        if v.node.fixed_start is None and aligned != v.start and aligned + v.node.stay <= v.end:
            window = next(((lo, hi) for lo, hi in v.node.windows if lo <= v.start <= hi), None)
            if window and aligned <= window[1] and (not v.node.meal or meal_slot(aligned) == meal_slot(v.start)):
                v.start = aligned
    return visits


def _windows_for_stay(n: Node, stay: int) -> list[Window]:
    """더 오래 머물 때의 시작 가능 구간: 지금 구간에서, 문 닫기(브레이크 시작) 전에 나올 수 있는 만큼만 남긴다.
    식사 시간대처럼 영업과 상관없는 시작 한계는 그대로 둔다."""
    p = n.place
    ends = [to_min(p.close)]
    if p.break_start and p.break_end:
        ends = [to_min(p.break_start), to_min(p.close)]
    out = []
    for lo, hi in n.windows:
        close = next((e for e in ends if e > lo), ends[-1])  # 이 구간이 들어 있는 영업 구간의 끝
        hi = min(hi, close - stay)
        if lo <= hi:
            out.append((lo, hi))
    return out


def fill_day(route: list[Node], day_start: int, day_end: int, travel: Travel, limits: Limits = LIMITS) -> list[Node]:
    """장소 수를 줄여 하루가 일찍 끝나면, 남는 시간만큼 AI 가 고른 곳에 더 머물게 한다(21시까지 놀겠다는데 19시에
    끝나지 않게). 장소마다 돌아가며 10분씩, 원래의 limits.stretch_max 배까지, 영업 종료·하루 종료를 넘지 않는 만큼.
    사용자가 고른 곳(꼭 갈 곳·출발 위치)은 정한 시간 그대로 둔다."""
    step = limits.time_step
    route = list(route)
    caps = [n.stay if n.mandatory else ceil_step(round(n.stay * limits.stretch_max)) for n in route]
    grown = True
    while grown:
        grown = False
        for i, n in enumerate(route):
            if n.stay + step > caps[i]:
                continue
            windows = _windows_for_stay(n, n.stay + step)
            if not windows:
                continue
            trial = route[:i] + [replace(n, stay=n.stay + step, windows=windows)] + route[i + 1 :]
            if schedule(trial, day_start, day_end, travel) is not None:
                route, grown = trial, True
    return route


def meals_covered(visits: list[Visit]) -> int:
    """식당(사용자가 고른 곳 포함)이 들어간 끼니 수. 식사 시간대에 시작한 식당만 센다."""
    return len({meal_slot(v.start) for v in visits if v.node.place.category == "food"} - {None})


def objective(visits: list[Visit], day_end: int, weights: Weights = WEIGHTS) -> float:
    """추천 점수식: 취향 적합도 + 지역상권 기여도 + 동행 적합도 + 끼니 - 이동 부담 - 빈 시간 - 시간 초과 페널티."""
    value = sum(v.node.value for v in visits if not v.node.mandatory) + weights.meal * meals_covered(visits)
    travel = sum(v.travel for v in visits)
    wait = sum(v.start - v.arrive for v in visits)
    overtime = max(0, visits[-1].end - day_end) if visits else 0
    return (
        value
        - weights.travel_per_min * travel
        - weights.wait_per_min * wait
        - weights.overtime_per_min * overtime
    )


CATEGORIES = {"sight", "culture", "market", "food", "cafe", "shop", "night", "venue", "lodging", "etc"}


def matches(n: Node, key: str) -> bool:
    """key 가 유형("cafe")이면 그 유형인지, 아니면 그 할 거리 태그("책·독서")가 있는지."""
    return n.place.category == key if key in CATEGORIES else key in n.place.tags.get("activity", [])


def caps(limits: Limits = LIMITS) -> dict[str, int]:
    """AI 추천 장소의 상한 {유형·할 거리: 곳 수}. 기본 유형 상한(category_caps)에 문장에서 말한 양을 얹는다:
    "카페 3곳" 처럼 상한보다 많이 원하면 올리고, "카페가 너무 많아" 처럼 줄여 달라면 내린다."""
    out = dict(limits.category_caps)
    for key, n in limits.want_min:
        if key in out and out[key] < n:
            out[key] = n
    for key, n in limits.want_max:
        out[key] = min(out.get(key, n), n)
    return out


def within_caps(route: list[Node], budget: Optional[int], limits: Limits = LIMITS) -> bool:
    """예산 · AI 추천 장소 수 · 유형별 상한."""
    if budget is not None and sum(n.cost for n in route) > budget:
        return False
    ai = [n for n in route if not n.mandatory]
    if len(ai) > limits.max_ai_stops:
        return False
    return all(sum(matches(n, key) for n in ai) <= cap for key, cap in caps(limits).items())


def want_shortfall(route: list[Node], limits: Limits = LIMITS) -> dict[str, int]:
    """limits.want_min 에 아직 모자란 AI 추천 장소 수. {할 거리·유형: 모자란 곳 수}, 다 채웠으면 빈 dict."""
    ai = [n for n in route if not n.mandatory]
    short = {key: need - sum(matches(n, key) for n in ai) for key, need in limits.want_min}
    return {key: k for key, k in short.items() if k > 0}


EXHAUSTIVE_MAX = 7  # 이 개수까지는 모든 순서를 본다(7! = 5040, 약 0.2초)


def improve_order(route: list[Node], day_start: int, day_end: int, travel: Travel) -> list[Node]:
    """고른 장소는 그대로 두고 방문 순서만 바꿔 점수(objective)가 가장 좋은 순서로.
    그리디는 한 곳씩 끼워 넣기만 해서, 장소는 괜찮아도 순서 때문에 오가는 이동이 생길 수 있다.
    영업시간·식사·고정 시각 등은 schedule() 이 그대로 따지므로, 지킬 수 없는 순서는 고르지 않는다."""
    hard_end = day_end + LIMITS.overtime_grace_min

    def score(order) -> Optional[float]:
        visits = schedule(list(order), day_start, hard_end, travel)
        return None if visits is None else objective(visits, day_end)

    best, best_score = list(route), score(route)
    if best_score is None or len(route) < 3:
        return best
    if len(route) <= EXHAUSTIVE_MAX:
        for order in itertools.permutations(route):
            s = score(order)
            if s is not None and s > best_score + 1e-9:
                best, best_score = list(order), s
        return best
    improved = True
    while improved:  # 장소가 많으면 한 곳을 다른 자리로 옮겨 보며 나아지는 동안 반복
        improved = False
        for i in range(len(best)):
            for j in range(len(best)):
                if i == j:
                    continue
                order = best[:i] + best[i + 1 :]
                order.insert(j, best[i])
                s = score(order)
                if s is not None and s > best_score + 1e-9:
                    best, best_score, improved = order, s, True
    return best
