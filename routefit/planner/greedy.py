"""③-a 그리디 삽입 방식 코스 생성 (Phase 1).

Must Visit 만으로 뼈대를 만든 뒤, 점수를 가장 많이 올리는 (후보, 삽입 위치)를
더 이상 점수가 오르지 않을 때까지 하나씩 끼워 넣는다.
"""
from typing import Optional

from ..config import LIMITS, Limits
from .core import Node, PlanError, Travel, matches, objective, schedule, want_shortfall, within_caps


def plan_greedy(
    musts: list[Node],
    candidates: list[Node],
    day_start: int,
    day_end: int,
    budget: Optional[int],
    travel: Travel,
    limits: Limits = LIMITS,
) -> list[Node]:
    hard_end = day_end + limits.overtime_grace_min
    # 시작 시각이 고정된 일정을 시간순으로, 나머지 Must Visit 은 그 앞에 둔다.
    route = sorted(musts, key=lambda n: (not n.origin, n.fixed_start is not None, n.fixed_start or 0))  # 출발 위치가 맨 앞
    visits = schedule(route, day_start, hard_end, travel)
    if visits is None:
        raise PlanError("꼭 갈 곳을 모두 지키는 시간표를 만들 수 없습니다. 시간 조건을 확인해 주세요.")
    best_score = objective(visits, day_end)

    def best_insertion(pool: list[Node]):
        best = None
        for cand in pool:
            for pos in range(len(route) + 1):
                trial = route[:pos] + [cand] + route[pos:]
                if not within_caps(trial, budget, limits):
                    break  # 삽입 위치와 무관한 제약
                trial_visits = schedule(trial, day_start, hard_end, travel)
                if trial_visits is None:
                    continue
                score = objective(trial_visits, day_end)
                if best is None or score > best[0]:
                    best = (score, cand, trial)
        return best

    remaining = list(candidates)
    while remaining:
        # 문장에서 말한 할 거리("서점 많이")가 모자라면 그걸 채우는 후보부터 넣는다. 지금은 들어갈 자리가 없으면
        # (예: 서점이 둘 다 카페라 카페끼리 붙는다) 평소처럼 다른 곳을 넣고, 사이가 생긴 다음 판에 다시 본다
        short = want_shortfall(route, limits)
        helpful = [c for c in remaining if any(matches(c, key) for key in short)]
        best = best_insertion(helpful) if helpful else None
        fills_need = best is not None
        if best is None:
            best = best_insertion(remaining)
        n_ai = sum(not n.mandatory for n in route)
        # 점수가 더 오르지 않으면 멈춘다. 다만 최소 장소 수(limits.min_ai_stops)에 못 미치거나, 모자란 할 거리를
        # 채우는 곳이면 들어갈 수 있는 한 넣는다
        if best is None or (best[0] <= best_score + 1e-9 and n_ai >= limits.min_ai_stops and not fills_need):
            break
        best_score, chosen, route = best
        remaining.remove(chosen)
    return route
