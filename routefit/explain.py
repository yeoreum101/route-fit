"""④ 추천 이유 생성: 판단은 알고리즘, 표현은 생성형 AI.

LLM 에는 점수 계산 결과(유사도·이동시간·라벨 점수)만 넘기고, 그 사실을 문장으로 옮기게 한다.
"""
import json
import re
from typing import Optional

from pydantic import BaseModel

from . import llm
from .config import LIMITS
from .data import travel_mode
from .models import CATEGORY_KO, Constraints, to_hm
from .planner import Visit
from .planner.core import meal_slot

SYSTEM = """너는 광주 여행 코스 생성 서비스 Route-Fit 의 코스 해설자다.
코스는 이미 알고리즘이 확정했다. 너는 주어진 계산 결과를 근거로 "왜 이 코스인가"를 한국어로 설명만 한다.

규칙:
- 입력 JSON 에 있는 사실(장소 설명, 유사도, 이동시간, 라벨 점수, 시간, 동행 적합 여부)만 근거로 쓴다. 메뉴·가격·행사 등 없는 정보를 지어내지 않는다.
- 장소를 추가·삭제하거나 순서를 바꾸자고 제안하지 않는다.
- 그 장소에서 하는 일은 activities 와 description 에 있는 것만 말한다. 사용자가 원한 일이 activities 에 없으면(전시를 원했는데
  극장) 그 일을 하는 곳처럼 쓰지 말고, 실제로 하는 일과 동선을 이유로 든다.
- reasons: kind 가 "ai" 인 장소마다 2문장, 합쳐서 100~120자.
  첫 문장은 그곳이 어떤 곳인지 description·activities·mood 로 쓴다. 식당·카페는 대표 메뉴와 분위기
  (예: "눈앞에서 한우를 구워 주는 코스 요리집으로, 룸이 있어 조용히 식사하기 좋습니다.").
  둘째 문장은 왜 이 자리인지: 취향 문장과 맞으면 그 점을, 아니면 하루에서 맡은 역할(meal 이 있으면 그 끼니, 카페면
  쉬어 가는 자리)을 쓴다(예: "전시를 본 뒤 여유 있게 점심을 먹는 자리입니다").
  "취향과 직접 맞닿지 않지만" 처럼 안 맞는다는 말로 시작하지 않는다.
- reasons 에는 이동 얘기("걸어서 ○분", "가까워서")를 쓰지 않는다. 이동 시간·수단은 화면의 타임라인에 따로 나온다.
- summary: 코스 전체를 2~3문장, 150~170자로 하루가 어떻게 이어지는지 쓴다.
- 장소 이름은 name 그대로 쓴다.
- kind 가 "start" 인 곳은 사용자가 출발하는 위치다(머무는 곳이 아니다). 있으면 "○○에서 출발해" 처럼만 쓴다.
  start 가 없으면 '출발' 이라는 말을 쓰지 않고 "○○에서 시작해" 처럼 쓴다.
- 점수 숫자를 그대로 나열하지 말고 자연스러운 말로 풀어 쓴다.
"""
# 사용자가 직접 고른 곳(kind 가 must)이 있을 때만 붙인다. 없을 때도 이 말을 주면 "직접 고른 곳은 없지만" 처럼 쓴다.
MUST_RULE = """- kind 가 "must" 인 곳은 사용자가 직접 고른 곳이다. summary 는 그곳을 중심으로 쓰고 "직접 고른" 처럼 부른다.
  "필수" 라는 말은 쓰지 않는다. kind 가 "ai" 인 곳은 사용자가 고른 곳처럼 쓰지 않는다.
"""
# 모든 구간이 가까운 도보일 때만 붙인다. 늘 주면 버스 구간이 있는데도 "모두 걸어서 이어지는" 이라고 썼다
WALK_RULE_ALL = '- 모든 구간이 걸어서 가깝다. summary 에서만 "모두 걸어서 이어지는" 처럼 한 번 말해도 된다.\n'
WALK_RULE_NONE = "- summary 에도 이동 수단·거리(걸어서, 도보, 가깝다) 얘기를 쓰지 않는다.\n"


SHORT_WALK_MIN = 10  # 모든 구간이 걸어서 이만큼 안쪽이면 요약에서 "모두 걸어서 이어지는" 코스라고 한 번 말한다


def _all_short_walks(visits: list[Visit]) -> bool:
    return len(visits) > 1 and all(
        travel_mode(a.node, b.node) == "walk" and b.travel <= SHORT_WALK_MIN for a, b in zip(visits, visits[1:])
    )


class StopReason(BaseModel):
    place_id: str
    reason: str


class Explanation(BaseModel):
    summary: str
    reasons: list[StopReason]


def _meal_name(v: Visit) -> Optional[str]:
    slot = meal_slot(v.start)
    return None if slot is None else LIMITS.meal_windows[slot][0]


def _facts(visits: list[Visit], c: Constraints) -> dict:
    return {
        "user_taste": c.taste,
        "budget": c.budget,
        "companions": c.companions,
        # 이동은 장소마다 말하지 않는다("걸어서 7분" 이 매번 나왔다). 모두 가까우면 요약에서 한 번만(WALK_RULE_ALL)
        "all_walk": _all_short_walks(visits),
        "stops": [
            {
                "place_id": v.node.id,
                "name": v.node.place.name,
                "kind": "start" if v.node.origin else "must" if v.node.mandatory else "ai",
                "category": CATEGORY_KO[v.node.place.category],
                "area": v.node.place.area,
                "description": v.node.place.description,
                "activities": v.node.place.tags.get("activity", []),  # '할 거리' 태그. 유형 이름(문화·전시)보다 정확하다
                "mood": v.node.place.tags.get("mood", []),
                # 식사 시간대에 넣은 식당이면 그 끼니("점심"·"저녁"). 취향과 상관없이 들어간 식당의 이유가 된다
                "meal": _meal_name(v) if v.node.meal else None,
                "time": f"{to_hm(v.start)}~{to_hm(v.end)}",
                "stay_min": v.node.stay,
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
    system = SYSTEM + (MUST_RULE if any(v.node.mandatory and not v.node.origin for v in visits) else "")
    system += WALK_RULE_ALL if facts["all_walk"] else WALK_RULE_NONE
    result = llm.structured(system, json.dumps(facts, ensure_ascii=False, indent=1), Explanation)
    if result is None:
        return _template(visits)
    # 모델 출력은 그대로 믿지 않는다: 근거 없는 금액·시간이 섞였거나 빠진 문장은 템플릿으로 바꾼다.
    fallback_summary, fallback_reasons, _ = _template(visits)
    allowed_min = _allowed_minutes(facts)
    given = {r.place_id: _drop_movement(r.reason.strip()) for r in result.reasons}
    reasons = {}
    for v in visits:
        if v.node.mandatory:
            continue
        text = given.get(v.node.id, "")
        reasons[v.node.id] = text if text and _grounded(text, c.budget, allowed_min) else fallback_reasons[v.node.id]
    summary = result.summary.strip() if facts["all_walk"] else _drop_movement(result.summary.strip())
    if not summary or not _grounded(summary, c.budget, allowed_min):
        summary = fallback_summary
    return summary, reasons, llm.name()


_MOVEMENT = re.compile(r"걸어서|도보|대중교통|버스|이동")
_SENTENCE = re.compile(r"(?<=[.!?다요])\s+")


def _drop_movement(text: str) -> str:
    """이동 얘기가 든 문장만 뺀다(규칙을 어기고 "걸어서 7분이라…" 를 써도 그 문장만 지운다). 다 지워지면 빈 문자열."""
    return " ".join(s for s in _SENTENCE.split(text) if not _MOVEMENT.search(s)).strip()


_MONEY = re.compile(r"(\d[\d,.]*)\s*([천만])?\s*원")
_MINUTES = re.compile(r"(\d+)\s*분")


_CLOCK = re.compile(r"\d{1,2}\s*시\s*(\d{1,2}\s*분)?|\d{1,2}:\d{2}")


def _allowed_minutes(facts: dict) -> set[int]:
    """문장에 나와도 되는 '○분': 장소에 머무는 시간('1시간 30분'의 30분도 포함). 이동시간은 넘기지 않으므로
    "걸어서 ○분" 을 쓰면 지어낸 것으로 보고 템플릿으로 바꾼다."""
    out = set()
    for s in facts["stops"]:
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
    musts = " · ".join(v.node.place.name for v in visits if v.node.mandatory and not v.node.origin) or "자유 일정"
    summary = f"{musts}을(를) 고정하고, 앞뒤 시간을 취향과 동선에 맞는 원도심 {len(reasons)}곳으로 채웠습니다."
    return summary, reasons, "template"
