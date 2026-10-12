"""③-a 그리디 삽입 방식 코스 생성 (Phase 1).

Must Visit 만으로 뼈대를 만든 뒤, 점수를 가장 많이 올리는 (후보, 삽입 위치)를
더 이상 점수가 오르지 않을 때까지 하나씩 끼워 넣는다.
"""
from typing import Optional

from ..config import LIMITS
from .core import Node, PlanError, Travel, objective, schedule, within_caps


def plan_greedy(
    musts: list[Node],
    candidates: list[Node],
    day_start: int,
    day_end: int,
    budget: Optional[int],
    travel: Travel,
) -> list[Node]:
    hard_end = day_end + LIMITS.overtime_grace_min
    # 시작 시각이 고정된 일정을 시간순으로, 나머지 Must Visit 은 그 앞에 둔다.
    route = sorted(musts, key=lambda n: (n.fixed_start is not None, n.fixed_start or 0))
    visits = schedule(route, day_start, hard_end, travel)
    if visits is None:
        raise PlanError("필수 방문지를 모두 지키는 시간표를 만들 수 없습니다. 시간 조건을 확인해 주세요.")
    best_score = objective(visits, day_end)

    remaining = list(candidates)
    while remaining:
        best = None
        for cand in remaining:
            for pos in range(len(route) + 1):
                trial = route[:pos] + [cand] + route[pos:]
                if not within_caps(trial, budget):
                    break  # 삽입 위치와 무관한 제약
                trial_visits = schedule(trial, day_start, hard_end, travel)
                if trial_visits is None:
                    continue
                score = objective(trial_visits, day_end)
                if best is None or score > best[0]:
                    best = (score, cand, trial)
        if best is None or best[0] <= best_score + 1e-9:
            break
        best_score, chosen, route = best
        remaining.remove(chosen)
    return route
