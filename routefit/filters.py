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
