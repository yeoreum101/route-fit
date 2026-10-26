"""① 자연어 조건 파싱: 자유 문장 -> 구조화 제약조건(ParsedQuery)."""
import re

from . import llm
from . import tags as tag_vocab
from .models import CATEGORY_KO, ParsedMustVisit, ParsedQuery, Place

SYSTEM = """너는 광주 여행 코스 생성 서비스 Route-Fit 의 조건 파서다.
사용자가 자유롭게 쓴 한국어 문장에서 여행 제약조건을 뽑아 구조화한다.

규칙:
- 문장에 없는 값은 추측하지 말고 null(목록은 빈 목록)로 둔다.
- taste: 사용자가 원하는 분위기·활동·취향만 남겨 한 문장으로 정리한다. 시간·예산·필수 방문지 언급은 뺀다.
- day_start, day_end, must_visits.start: 24시간제 'HH:MM'.
- budget: 1인 기준 원 단위 정수. "10만원" -> 100000.
- weekday: 0=월요일 ... 6=일요일.
- must_visits: 사용자가 이미 가기로 정한 장소만 넣는다. 아래 [알려진 목적지]에 해당하면 그 이름을 그대로 쓴다.
  "가보고 싶다" 수준의 취향은 must_visits 가 아니라 taste 에 넣는다.
  장소 이름 없이 예정된 일정만 말했더라도(예: "야구 보러 간다"), 그 일정이 열리는 곳이 [알려진 목적지] 중
  하나로 분명하면 그 목적지를 넣는다. 분명하지 않으면 넣지 않는다.
- companions: 같이 가는 사람. 혼자, 친구, 연인, 가족, 아이 동반 중 하나만. 아이와 함께면 "아이 동반".
- avoid_categories: 사용자가 "빼고", "말고", "싫다"처럼 분명히 피하고 싶다고 한 유형만. 값은 sight, culture, market, food, cafe, shop, night 중에서.
  가고 싶다고 한 유형(예: "점심 먹고 카페 가고 싶어" 의 food, cafe)은 절대 넣지 않는다. 피하는 말이 없으면 빈 목록.
"""


def parse_query(query: str, known: list[Place]) -> tuple[ParsedQuery, str]:
    """(파싱 결과, 사용된 파서 이름)을 돌려준다."""
    # 행사장은 어떤 일정이 열리는 곳인지 알 수 있게 설명을 함께 준다.
    names = "\n".join(f"- {p.name}" + (f" ({p.description})" if p.category == "venue" else "") for p in known)
    parsed = llm.structured(SYSTEM, f"[알려진 목적지]\n{names}\n\n[사용자 문장]\n{query}", ParsedQuery)
    if parsed is not None:
        return sanitize(parsed, known, query), llm.name()
    return parse_rule_based(query, known), "rule"


_HM = re.compile(r"^([01]?\d|2[0-9]):([0-5]\d)$")
_AVOIDABLE = {k for k in CATEGORY_KO if k != "venue"}
# 피하는 말. 문장에 하나도 없는데 LLM 이 avoid_categories 를 채우면 가고 싶다는 유형을 거꾸로 넣은 것이다
# (gpt-5.4-mini 가 "점심 먹고 카페 가고 싶어요" 를 가끔 food·cafe 회피로 읽는다).
_AVOID_WORDS = ("빼", "말고", "제외", "싫", "피하", "피해", "없이", "별로", "질려", "안 가", "안가", "말아")


def _hm(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _HM.match(value) else None


def find_by_name(known: list[Place], name: str | None) -> Place | None:
    """이름·별칭이 서로 포함되면 같은 장소로 본다(공백 무시)."""
    key = (name or "").replace(" ", "")
    if not key:
        return None
    for p in known:
        names = [n.replace(" ", "") for n in [p.name, *p.aliases]]
        if any(key == n or n in key or key in n for n in names):
            return p
    return None


def sanitize(parsed: ParsedQuery, known: list[Place], query: str | None = None) -> ParsedQuery:
    """LLM 출력을 믿지 않고 규칙에 맞게 정리한다. 형식이 틀린 값은 null 로 두어 기본값·화면 입력이 쓰이게 하고,
    알려진 목적지가 아닌 필수 방문지는 버린다(없으면 사용자에게 '찾을 수 없다'는 오류가 나기 때문).
    query(원문)를 주면, 피하는 말이 없는 문장의 avoid_categories 는 버린다."""
    parsed.companions = normalize_companions(parsed.companions)
    parsed.day_start = _hm(parsed.day_start)
    parsed.day_end = _hm(parsed.day_end)
    if parsed.budget is not None and parsed.budget <= 0:
        parsed.budget = None
    if parsed.weekday is not None and not 0 <= parsed.weekday <= 6:
        parsed.weekday = None
    parsed.avoid_categories = [c for c in dict.fromkeys(parsed.avoid_categories) if c in _AVOIDABLE]
    if query is not None and not any(w in query for w in _AVOID_WORDS):
        parsed.avoid_categories = []
    musts = []
    for m in parsed.must_visits:
        place = find_by_name(known, m.name)
        if place is None:
            continue
        m.name = place.name
        m.start = _hm(m.start)
        m.stay_min = m.stay_min if m.stay_min and m.stay_min > 0 else None
        musts.append(m)
    parsed.must_visits = musts
    return parsed


def normalize_companions(text: str | None) -> str | None:
    """동행을 장소 태그 '어울리는 동행' 값(혼자·친구·연인·가족·아이 동반)으로 맞춘다. 모르면 None."""
    if not text:
        return None
    text = text.strip()
    if text in tag_vocab.values("companions"):
        return text
    return next((v for k, v in _COMPANIONS.items() if k in text), None)


# ---------- 규칙 기반 대체 파서 (API 키 없이 개발·테스트할 때) ----------

_PM = ("오후", "저녁", "밤")
_TIME = re.compile(r"(오전|아침|낮|오후|저녁|밤)?\s*(\d{1,2})\s*시\s*(반|\d{1,2}\s*분)?\s*(부터|까지)?")
_WEEKDAYS = "월화수목금토일"
# 앞에 있는 것이 먼저 잡힌다. 아이와 함께면 가족보다 '아이 동반'이 더 구체적이다.
# '아이스크림' 같은 말에 걸리지 않도록 '아이' 단독은 쓰지 않는다.
_COMPANIONS = {
    "아이 동반": "아이 동반",
    "아이랑": "아이 동반",
    "아이와": "아이 동반",
    "아이들": "아이 동반",
    "아기": "아이 동반",
    "애기": "아이 동반",
    "유아": "아이 동반",
    "혼자": "혼자",
    "친구": "친구",
    "연인": "연인",
    "커플": "연인",
    "데이트": "연인",
    "가족": "가족",
    "부모님": "가족",
}


def _budget(text: str) -> int | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*만\s*원?", text)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원", text)
    return int(m.group(1).replace(",", "")) if m else None


def _times(text: str) -> tuple[str | None, str | None]:
    start = end = None
    for ampm, hour, minute, edge in _TIME.findall(text):
        h = int(hour)
        if ampm in _PM and h < 12:
            h += 12
        m = 30 if minute == "반" else int(re.sub(r"\D", "", minute)) if minute else 0
        if edge == "부터":
            start = f"{h:02d}:{m:02d}"
        elif edge == "까지":
            end = f"{h:02d}:{m:02d}"
    return start, end


def parse_rule_based(query: str, known: list[Place]) -> ParsedQuery:
    day_start, day_end = _times(query)
    weekday = next((i for i, d in enumerate(_WEEKDAYS) if f"{d}요일" in query), None)
    companions = next((v for k, v in _COMPANIONS.items() if k in query), None)
    compact = query.replace(" ", "")
    must = [
        ParsedMustVisit(name=p.name, start=None, stay_min=None)
        for p in known
        if any(a.replace(" ", "") in compact for a in [p.name, *p.aliases])
    ]
    return ParsedQuery(
        taste=query,
        day_start=day_start,
        day_end=day_end,
        budget=_budget(query),
        companions=companions,
        weekday=weekday,
        must_visits=must,
        avoid_categories=[],
    )
