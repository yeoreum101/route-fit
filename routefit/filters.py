"""AI 추천 후보에서 뺄 장소를 고른다. 유형 단위 제외(avoid_categories)보다 좁은, 장소·낱말 단위 규칙.

- 사용자가 뺀 장소(화면의 제외 장소)와 싫다고 한 낱말("훠궈 싫어")이 들어간 장소
- 데이트 코스의 추모 공간(5·18 사적지 등). 문장에서 역사·5·18 을 원하면 빼지 않는다
- 필수 방문지와 같은 종류(영화관을 골랐으면 다른 영화관)
"""
import re
from typing import Optional

from .models import Place

_SPACE = re.compile(r"\s+")


def compact(text: str) -> str:
    return _SPACE.sub("", text or "").lower()


def place_text(p: Place) -> str:
    """장소를 낱말로 찾을 때 보는 글: 이름·별칭·소개·태그."""
    tags = " ".join(v for values in (p.tags or {}).values() for v in values)
    return compact(" ".join([p.name, *p.aliases, p.description, tags]))


def has_keyword(p: Place, keywords: list[str]) -> Optional[str]:
    """장소 글에 들어간 첫 낱말. 없으면 None."""
    text = place_text(p)
    return next((k for k in keywords if compact(k) and compact(k) in text), None)


# ---------- 데이트 코스의 추모 공간 ----------

DATE_WORDS = ("데이트", "로맨틱", "연인", "커플", "애인", "여자친구", "남자친구", "여친", "남친")
MEMORIAL_WORDS = ("5·18", "5.18", "추모", "희생자", "묘역", "묘지", "민주화운동")


def is_date(query: str, companions: Optional[str]) -> bool:
    return companions == "연인" or any(w in query for w in DATE_WORDS)


def wants_history(query: str) -> bool:
    """문장에서 역사·5·18 을 원하면 추모 공간을 빼지 않는다."""
    return "역사" in query or any(w in query for w in MEMORIAL_WORDS)


def is_memorial(p: Place) -> bool:
    return has_keyword(p, list(MEMORIAL_WORDS)) is not None


# ---------- 필수 방문지와 같은 종류 ----------

# (종류, 장소 글에 들어 있으면 그 종류로 보는 낱말). 필수 방문지가 이 종류면 같은 종류의 AI 추천은 뺀다.
KINDS = [
    ("영화관", ("영화관", "극장", "시네마", "cgv", "메가박스")),
    ("서점", ("서점", "책방")),
    ("노래방", ("노래방", "코인노래")),
    ("찜질방", ("찜질방", "사우나", "스파")),
    ("수족관", ("수족관", "아쿠아리움")),
    ("볼링장", ("볼링",)),
    ("방탈출", ("방탈출",)),
    ("놀이공원", ("놀이공원", "테마파크", "패밀리랜드")),
]


def kind_of(p: Place) -> Optional[str]:
    text = place_text(p)
    return next((kind for kind, words in KINDS if any(w in text for w in words)), None)


# ---------- 문장에서 콕 집어 말한 할 거리 ----------

# (할 거리 태그, 문장에 이 말(정규식)이 있으면 그 할 거리를 원한다고 본다). 먹고 마시는 것·산책·휴식처럼 넓은 말은
# 유형·끼니 규칙과 취향 매칭이 맡으므로 넣지 않는다.
ACTIVITY_WORDS = [
    ("전시 관람", ("전시", "미술관", "갤러리", "박물관")),
    ("공연·영화", ("공연", "영화", "연극", "뮤지컬", "콘서트")),
    ("역사 탐방", ("역사",)),
    ("건축 구경", ("건축",)),
    ("야경", ("야경",)),
    ("공방 체험", ("공방",)),
    # '책' 은 서점·책방·북카페까지 다 잡는다. 산책·공책·대책·정책·채책 과 책임·책상 은 책이 아니다
    ("책·독서", ("서점", r"(?<![산공대정채])책(?![임상])", "독서", "북카페")),
    ("쇼핑", ("쇼핑",)),
    ("시장 구경", ("시장",)),
]
_NEGATED = r"\S{0,3}\s*(?:싫|빼|말고|제외|별로|안\s*보)"


# ---------- 장소 수 ("3곳만", "4곳 이상", "장소 너무 많아") ----------

_KO_NUM = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5, "여섯": 6,
           "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
_NUM = r"(\d{1,2}|" + "|".join(sorted(_KO_NUM, key=len, reverse=True)) + ")"
_UNIT = r"\s*(?:곳|군데|개|장소)"
_COUNT_RANGE = re.compile(_NUM + r"\s*[~\-–]\s*" + _NUM + _UNIT)
_COUNT_MIN = re.compile(r"(?:최소|적어도)\s*" + _NUM + _UNIT + "|" + _NUM + _UNIT + r"\s*(?:이상|넘게|넘는|넘어)")
_COUNT_MAX = re.compile(r"(?:최대|많아야)\s*" + _NUM + _UNIT + "|" + _NUM + _UNIT + r"\s*(?:이하|까지|안쪽|넘지)")
# 수만 말할 때는 "3곳만·세 군데 정도·4개로" 처럼 붙는 말이 있거나 "장소는 3곳" 처럼 장소 얘기여야 한다
# ("만두 2개 먹고", "한 곳에 오래" 는 장소 수가 아니다)
_COUNT = re.compile(
    r"(?<![가-힣\d])" + _NUM + _UNIT + r"\s*(?:만|정도|쯤|으로|로)(?![가-힣])"
    + r"|(?<![가-힣\d])" + _NUM + _UNIT + r"\s*(?:만|정도|쯤)"
    + r"|장소\S{0,3}\s*" + _NUM + _UNIT
)
_FEWER = re.compile(
    r"(?:장소|곳|코스|일정)\S{0,3}\s*(?:너무\s*많|적게|조금만|줄여|많지\s*않게)|몇\s*(?:군데|곳)만|너무\s*많은\s*(?:곳|장소)"
)


def _num(text: str) -> int:
    return int(text) if text.isdigit() else _KO_NUM[text]


def place_count(query: str, fewer: int) -> tuple[Optional[int], Optional[int]]:
    """문장에서 말한 하루 장소 수 (최소, 최대). 출발 위치는 세지 않고 꼭 갈 곳은 센다.
    "3~4곳" -> (3, 4), "4곳 이상" -> (4, None), "최대 3곳"·"3곳까지" -> (None, 3), "3곳만"·"세 군데" -> (3, 3),
    수 없이 "장소 너무 많아"·"조금만" -> (None, fewer). 말이 없으면 (None, None)."""
    if m := _COUNT_RANGE.search(query):
        lo, hi = sorted((_num(m.group(1)), _num(m.group(2))))
        return lo, hi
    if m := _COUNT_MIN.search(query):
        return _num(m.group(1) or m.group(2)), None
    if m := _COUNT_MAX.search(query):
        return None, _num(m.group(1) or m.group(2))
    if m := _COUNT.search(query):
        n = _num(next(g for g in m.groups() if g))
        return n, n
    if _FEWER.search(query):
        return None, fewer
    return None, None


# ---------- 대중교통을 타지 않겠다는 말 ----------

_NO_TRANSIT = re.compile(
    r"(?:대중교통|버스|지하철)\S{0,4}\s*(?:타기\s*|타는\s*(?:건|게)\s*)?(?:싫|별로|말고|빼|없이|안\s*타|안\s*탈|타지\s*않|못\s*타)"
)
_WALK_ONLY = re.compile(r"(?:걸어서|도보로?)\s*(?:만|다닐|갈\s*수|이동|돌아)")


def avoids_transit(query: str) -> bool:
    """"대중교통 타기 싫어", "버스는 안 탈래", "걸어서 다닐 수 있는 곳으로만" -> True.
    "많이 걷기 싫어" 처럼 걷기를 피하는 말은 아니다."""
    return bool(_NO_TRANSIT.search(query) or _WALK_ONLY.search(query))


def wanted_activities(query: str) -> set[str]:
    """문장에서 하고 싶다고 한 할 거리 태그. "전시 좀 보고" -> {"전시 관람"}. "전시는 말고" 처럼 피하는 말이 붙으면 뺀다."""
    return set(wanted_activity_counts(query))


# 할 거리 바로 뒤(또는 앞)에 붙은 양. "서점 많이·여러 군데·책방 투어" -> 2, "서점 3곳" -> 3
_KO_COUNT = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
_COUNT_AFTER = re.compile(r"\S{0,3}?\s*(\d{1,2}|한|두|세|네|다섯)\s*(?:곳|군데|개)")
_MANY_AFTER = re.compile(r"\S{0,3}?\s*(?:많이|여러|잔뜩|투어|위주)")
_MANY_BEFORE = re.compile(r"(?:여러|많은)\s*(?:곳의?|군데의?)?\s*$")


def _amount(query: str, start: int, end: int) -> int:
    if m := _COUNT_AFTER.match(query, end):
        return max(1, int(m.group(1)) if m.group(1).isdigit() else _KO_COUNT[m.group(1)])
    if _MANY_AFTER.match(query, end) or _MANY_BEFORE.search(query[max(0, start - 8):start]):
        return 2
    return 1


def wanted_activity_counts(query: str) -> dict[str, int]:
    """문장에서 하고 싶다고 한 할 거리와 몇 곳은 넣어야 하는지. "서점 많이랑 전시 보고 싶어" ->
    {"책·독서": 2, "전시 관람": 1}. 양을 말하지 않으면 1곳. 피하는 말이 붙은 할 거리는 뺀다."""
    out: dict[str, int] = {}
    for activity, words in ACTIVITY_WORDS:
        if any(re.search(f"(?:{w}){_NEGATED}", query) for w in words):
            continue
        n = max((_amount(query, m.start(), m.end()) for w in words for m in re.finditer(w, query)), default=0)
        if n:
            out[activity] = n
    return out
