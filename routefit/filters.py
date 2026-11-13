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
    # 방탈출·보드게임. "게임" 만으로는 잡지 않는다("야구 게임 보기 전에")
    ("게임·놀이", ("방탈출", "보드게임", "보드 게임", "보드카페")),
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


_MORE_PLACES = re.compile(
    r"(?:장소|곳|코스|일정)\S{0,3}\s*(?:(?:좀\s*)?너무\s*적|좀\s*적|적은\s*것\s*같|부족|모자라|더\s*(?:많이|넣|늘려)|늘려)"
    r"|더\s*많은\s*(?:곳|장소)"
)


def _targeted(query: str, start: int) -> bool:
    """수 바로 앞에 할 거리·유형 낱말이 있다("서점 3곳만", "카페는 한 곳만"): 하루 전체 장소 수가 아니다."""
    words = [w for _, ws in ACTIVITY_WORDS + CATEGORY_WORDS for w in ws]
    return bool(re.search("(?:" + "|".join(words) + r")\S{0,3}\s*$", query[max(0, start - 12):start]))


def _first(pattern: re.Pattern, query: str):
    return next((m for m in pattern.finditer(query) if not _targeted(query, m.start())), None)


def place_count(query: str, fewer: int, more: Optional[int] = None) -> tuple[Optional[int], Optional[int]]:
    """문장에서 말한 하루 장소 수 (최소, 최대). 출발 위치는 세지 않고 꼭 갈 곳은 센다.
    "3~4곳" -> (3, 4), "4곳 이상" -> (4, None), "최대 3곳"·"3곳까지" -> (None, 3), "3곳만"·"세 군데" -> (3, 3),
    수 없이 "장소 너무 많아"·"조금만" -> (None, fewer), "장소가 너무 적어"·"더 많은 곳" -> (more, None).
    "서점 3곳만" 처럼 할 거리·유형에 붙은 수는 그 할 거리의 수라 여기서 세지 않는다. 말이 없으면 (None, None)."""
    if m := _first(_COUNT_RANGE, query):
        lo, hi = sorted((_num(m.group(1)), _num(m.group(2))))
        return lo, hi
    if m := _first(_COUNT_MIN, query):
        return _num(m.group(1) or m.group(2)), None
    if m := _first(_COUNT_MAX, query):
        return None, _num(m.group(1) or m.group(2))
    if m := _first(_COUNT, query):
        n = _num(next(g for g in m.groups() if g))
        return n, n
    if _FEWER.search(query):
        return None, fewer
    if more is not None and _MORE_PLACES.search(query):
        return more, None
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


# ---------- 할 거리·유형의 양 ("서점 좀 많이", "카페가 너무 많아", "전시는 한 곳만") ----------

# 유형으로 말하는 것. 양을 말했을 때만 쓴다("맛집 가고 싶어" 처럼 그냥 말한 것은 끼니·유형 규칙이 맡는다)
CATEGORY_WORDS = [
    ("cafe", (r"(?<!북)카페",)),
    ("food", ("식당", "밥집", "맛집")),
    ("night", ("술집", "포차")),
    ("shop", ("소품샵", "소품 가게", "편집샵")),
]
CATEGORY_KEYS = {c for c, _ in CATEGORY_WORDS}

_PART = r"\S{0,3}?\s*"  # 조사("은·이·를·이랑")
_ADV = r"(?:(?:좀|조금|더|아주|엄청|꽤|정말|진짜|훨씬)\s*)?"
_KO_COUNT = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
_EXACT = re.compile(_PART + r"(\d{1,2}|한|두|세|네|다섯)\s*(?:곳|군데|개)(\s*만)?")
_ONLY_ONE = re.compile(_PART + r"(?:하나|한\s*번)\s*만")
# 줄여 달라: "좀 적게·조금만·덜", "너무 많아·너무 많은 것 같아"
_FEWER_AFTER = re.compile(_PART + _ADV + r"(?:적게|조금만|덜|줄여|줄이)|" + _PART + r"(?:좀\s*)?너무\s*많")
# 늘려 달라: "좀 많이·여러 곳·투어·더 넣어", "너무 적어·부족해"
_MORE_AFTER = re.compile(
    _PART + _ADV + r"(?:많이|여러|잔뜩|투어|위주|더\s*넣|늘려)|" + _PART + r"(?:(?:좀\s*)?너무\s*적|부족|모자라)"
)
_MORE_BEFORE = re.compile(r"(?:여러|많은)\s*(?:곳의?|군데의?)?\s*$")

MORE = 2  # "많이" 는 2곳 이상
FEWER = 1  # "적게·너무 많아" 는 1곳까지


def _amount(query: str, start: int, end: int, category: bool) -> Optional[tuple[int, Optional[int]]]:
    """낱말 바로 뒤(또는 앞)의 양 -> (최소, 최대). 양을 말하지 않았으면 할 거리는 (1, None), 유형은 None."""
    if m := _EXACT.match(query, end):
        n = int(m.group(1)) if m.group(1).isdigit() else _KO_COUNT[m.group(1)]
        return (n, n) if m.group(2) else (n, None)
    if _ONLY_ONE.match(query, end):
        return 1, 1
    if _FEWER_AFTER.match(query, end):
        return 0, FEWER
    if _MORE_AFTER.match(query, end) or _MORE_BEFORE.search(query[max(0, start - 8):start]):
        return MORE, None
    return None if category else (1, None)


def quantity_wants(query: str) -> dict[str, tuple[int, Optional[int]]]:
    """문장에서 말한 할 거리·유형별 (최소, 최대) 곳 수. 키는 할 거리 태그("책·독서") 또는 유형("cafe").
    "서점 좀 많이랑 전시" -> {"책·독서": (2, None), "전시 관람": (1, None)},
    "카페가 너무 많아" -> {"cafe": (0, 1)}, "전시는 한 곳만" -> {"전시 관람": (1, 1)}.
    피하는 말("서점은 말고")이 붙은 것은 넣지 않는다(뺄 곳은 다른 규칙이 맡는다)."""
    out: dict[str, tuple[int, Optional[int]]] = {}
    targets = [(a, w, False) for a, w in ACTIVITY_WORDS] + [(c, w, True) for c, w in CATEGORY_WORDS]
    for key, words, category in targets:
        if any(re.search(f"(?:{w}){_NEGATED}", query) for w in words):
            continue
        found = [a for w in words for m in re.finditer(w, query) if (a := _amount(query, m.start(), m.end(), category))]
        if not found:
            continue
        lo = max(a[0] for a in found)
        his = [a[1] for a in found if a[1] is not None]
        hi = min(his) if his else None
        out[key] = (min(lo, hi) if hi is not None else lo, hi)
    return out


def wanted_activities(query: str) -> set[str]:
    """문장에서 하고 싶다고 한 할 거리 태그. "전시 좀 보고" -> {"전시 관람"}. "전시는 말고" 처럼 피하는 말이 붙으면 뺀다."""
    return {k for k in quantity_wants(query) if k not in CATEGORY_KEYS}


def wanted_activity_counts(query: str) -> dict[str, int]:
    """할 거리마다 적어도 넣어야 할 곳 수. "서점 많이랑 전시 보고 싶어" -> {"책·독서": 2, "전시 관람": 1}."""
    return {k: lo for k, (lo, _) in quantity_wants(query).items() if k not in CATEGORY_KEYS and lo > 0}
