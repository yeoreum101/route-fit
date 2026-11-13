"""③-a 그리디 삽입 방식 코스 생성 (Phase 1).

Must Visit 만으로 뼈대를 만든 뒤, 점수를 가장 많이 올리는 (후보, 삽입 위치)를
더 이상 점수가 오르지 않을 때까지 하나씩 끼워 넣는다.
"""
from typing import Optional

from ..config import LIMITS, Limits
from .core import Node, PlanError, Travel, activity_shortfall, has_activity, objective, schedule, within_caps


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

    remaining = list(candidates)
    while remaining:
        best = None
        # 문장에서 말한 할 거리("서점 많이")가 모자라면, 그걸 채우는 후보부터 본다. 넣을 곳이 없으면 다른 후보로
        short = activity_shortfall(route, limits)
        helpful = [c for c in remaining if any(has_activity(c, a) for a in short)]
        for cand in helpful or remaining:
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
        if best is None and helpful and len(helpful) < len(remaining):
            # 모자란 할 거리를 채울 곳이 하루에 안 들어간다: 그 후보들은 접고 나머지로 계속
            for c in helpful:
                remaining.remove(c)
            continue
        n_ai = sum(not n.mandatory for n in route)
        # 점수가 더 오르지 않으면 멈춘다. 다만 최소 장소 수(limits.min_ai_stops)나 할 거리 수(limits.activity_min)에
        # 못 미치면 들어갈 수 있는 한 계속 넣는다
        if best is None or (best[0] <= best_score + 1e-9 and n_ai >= limits.min_ai_stops and not (helpful and short)):
            break
        best_score, chosen, route = best
        remaining.remove(chosen)
    return route
