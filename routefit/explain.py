"""④ 추천 이유 생성: 판단은 알고리즘, 표현은 생성형 AI.

LLM 에는 점수 계산 결과(유사도·이동시간·라벨 점수)만 넘기고, 그 사실을 문장으로 옮기게 한다.
"""
import json
import re

from pydantic import BaseModel

from . import llm
from .models import CATEGORY_KO, Constraints, to_hm
from .planner import Visit

SYSTEM = """너는 광주 여행 코스 생성 서비스 Route-Fit 의 코스 해설자다.
코스는 이미 알고리즘이 확정했다. 너는 주어진 계산 결과를 근거로 "왜 이 코스인가"를 한국어로 설명만 한다.

규칙:
- 입력 JSON 에 있는 사실(장소 설명, 유사도, 이동시간, 라벨 점수, 시간, 동행 적합 여부)만 근거로 쓴다. 메뉴·가격·행사 등 없는 정보를 지어내지 않는다.
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
                "stay_min": v.node.stay,
                "travel_min_from_prev": v.travel,
                "taste_similarity": round(v.node.similarity, 3),
                "gwangju_ness_1to5": v.node.place.gwangju_ness,
                "stay_inducement_1to5": v.node.place.stay_inducement,
                "commerce_link_1to5": v.node.place.commerce_link,
                "is_local_commerce": v.node.place.is_local_commerce,
                "suits_companions": v.node.companion_fit,  # 장소 태그 기준으로 동행과 어울리는지
            }
            for v in visits
        ],
    }


def explain(visits: list[Visit], c: Constraints) -> tuple[str, dict[str, str], str]:
    """(코스 요약, {place_id: 추천 이유}, 사용된 설명기 이름)."""
    facts = _facts(visits, c)
    result = llm.structured(SYSTEM, json.dumps(facts, ensure_ascii=False, indent=1), Explanation)
    if result is None:
        return _template(visits)
    # 모델 출력은 그대로 믿지 않는다: 근거 없는 금액·시간이 섞였거나 빠진 문장은 템플릿으로 바꾼다.
    fallback_summary, fallback_reasons, _ = _template(visits)
    allowed_min = _allowed_minutes(facts)
    given = {r.place_id: r.reason.strip() for r in result.reasons}
    reasons = {}
    for v in visits:
        if v.node.mandatory:
            continue
        text = given.get(v.node.id, "")
        reasons[v.node.id] = text if text and _grounded(text, c.budget, allowed_min) else fallback_reasons[v.node.id]
    summary = result.summary.strip()
    if not summary or not _grounded(summary, c.budget, allowed_min):
        summary = fallback_summary
    return summary, reasons, llm.name()


_MONEY = re.compile(r"(\d[\d,.]*)\s*([천만])?\s*원")
_MINUTES = re.compile(r"(\d+)\s*분")


_CLOCK = re.compile(r"\d{1,2}\s*시\s*(\d{1,2}\s*분)?|\d{1,2}:\d{2}")


def _allowed_minutes(facts: dict) -> set[int]:
    """문장에 나와도 되는 '○분': 장소 사이 이동시간과 장소에 머무는 시간('1시간 30분'의 30분도 포함)."""
    out = set()
    for s in facts["stops"]:
        out.add(s["travel_min_from_prev"])
        out.add(s["stay_min"])
        if s["stay_min"] >= 60:
            out.add(s["stay_min"] % 60)
    return out


def _grounded(text: str, budget: int | None, allowed_min: set[int]) -> bool:
    """입력에 없는 사실을 지어냈는지 검사한다. 장소별 가격은 입력에 없으므로 금액은 예산과 같을 때만 허용하고,
    '○분'은 입력의 이동시간·머무는 시간과 같을 때만 허용한다. '5시 35분' 같은 시각은 시간 길이가 아니므로 뺀다."""
    for num, unit in _MONEY.findall(text):
        try:
            value = float(num.replace(",", "")) * {"천": 1000, "만": 10000}.get(unit, 1)
        except ValueError:
            return False
        if budget is None or int(value) != budget:
            return False
    return all(int(m) in allowed_min for m in _MINUTES.findall(_CLOCK.sub(" ", text)))


def _reason(v: Visit) -> str:
    p = v.node.place
    # 이동시간과 지역상권 여부는 화면의 타임라인·태그에 따로 나오므로 이유에는 쓰지 않는다.
    return f"취향 유사도 {v.node.similarity:.2f}, 광주다움 {p.gwangju_ness:g}/5 · 체류 유도성 {p.stay_inducement:g}/5"


def _template(visits: list[Visit]) -> tuple[str, dict[str, str], str]:
    reasons = {v.node.id: _reason(v) for v in visits if not v.node.mandatory}
    musts = " · ".join(v.node.place.name for v in visits if v.node.mandatory) or "자유 일정"
    summary = f"{musts}을(를) 고정하고, 앞뒤 시간을 취향과 동선에 맞는 원도심 {len(reasons)}곳으로 채웠습니다."
    return summary, reasons, "template"
