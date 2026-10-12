"""④ 추천 이유 생성: 판단은 알고리즘, 표현은 생성형 AI.

LLM 에는 점수 계산 결과(유사도·이동시간·라벨 점수)만 넘기고, 그 사실을 문장으로 옮기게 한다.
"""
import json

from pydantic import BaseModel

from . import llm
from .models import CATEGORY_KO, Constraints, to_hm
from .planner import Visit

SYSTEM = """너는 광주 여행 코스 생성 서비스 Route-Fit 의 코스 해설자다.
코스는 이미 알고리즘이 확정했다. 너는 주어진 계산 결과를 근거로 "왜 이 코스인가"를 한국어로 설명만 한다.

규칙:
- 입력 JSON 에 있는 사실(장소 설명, 유사도, 이동시간, 라벨 점수, 시간)만 근거로 쓴다. 메뉴·가격·행사 등 없는 정보를 지어내지 않는다.
- 장소를 추가·삭제하거나 순서를 바꾸자고 제안하지 않는다.
- reasons: kind 가 "ai" 인 장소마다 1~2문장. 사용자의 취향 문장과 어떻게 맞는지, 동선상 왜 이 자리인지를 구체적으로 쓴다.
- summary: 코스 전체를 2~3문장으로. 필수 방문지를 중심으로 하루가 어떻게 이어지는지 설명한다.
- 점수 숫자를 그대로 나열하지 말고 자연스러운 말로 풀어 쓴다.
"""


class StopReason(BaseModel):
    place_id: str
    reason: str


class Explanation(BaseModel):
    summary: str
    reasons: list[StopReason]


def _facts(visits: list[Visit], c: Constraints) -> dict:
    return {
        "user_taste": c.taste,
        "budget": c.budget,
        "companions": c.companions,
        "stops": [
            {
                "place_id": v.node.id,
                "name": v.node.place.name,
                "kind": "must" if v.node.mandatory else "ai",
                "category": CATEGORY_KO[v.node.place.category],
                "area": v.node.place.area,
                "description": v.node.place.description,
                "time": f"{to_hm(v.start)}~{to_hm(v.end)}",
                "travel_min_from_prev": v.travel,
                "taste_similarity": round(v.node.similarity, 3),
                "gwangju_ness_1to5": v.node.place.gwangju_ness,
                "stay_inducement_1to5": v.node.place.stay_inducement,
                "commerce_link_1to5": v.node.place.commerce_link,
                "is_local_commerce": v.node.place.is_local_commerce,
            }
            for v in visits
        ],
    }


def explain(visits: list[Visit], c: Constraints) -> tuple[str, dict[str, str], str]:
    """(코스 요약, {place_id: 추천 이유}, 사용된 설명기 이름)."""
    facts = json.dumps(_facts(visits, c), ensure_ascii=False, indent=1)
    result = llm.structured(SYSTEM, facts, Explanation)
    if result is not None:
        return result.summary, {r.place_id: r.reason for r in result.reasons}, llm.name()
    return _template(visits)


def _template(visits: list[Visit]) -> tuple[str, dict[str, str], str]:
    reasons = {}
    for i, v in enumerate(visits):
        if v.node.mandatory:
            continue
        p = v.node.place
        parts = [f"취향 유사도 {v.node.similarity:.2f}"]
        if i:
            parts.append(f"{visits[i - 1].node.place.name}에서 {v.travel}분")
        parts.append(f"광주다움 {p.gwangju_ness:g}/5 · 체류 유도성 {p.stay_inducement:g}/5")
        if p.is_local_commerce:
            parts.append("지역상권")
        reasons[v.node.id] = ", ".join(parts)
    musts = " · ".join(v.node.place.name for v in visits if v.node.mandatory) or "자유 일정"
    summary = f"{musts}을(를) 고정하고, 앞뒤 시간을 취향과 동선에 맞는 원도심 {len(reasons)}곳으로 채웠습니다."
    return summary, reasons, "template"
