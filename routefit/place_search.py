"""필수 방문지 검색: 등록된 장소를 먼저, 없으면 카카오 장소 검색(키워드)으로 광주 안의 장소를 찾는다.

카카오에서 고른 장소는 DB 에 넣지 않고 코스를 만들 때만 쓴다(id 는 'kakao_<카카오 장소 id>').
업종(category_group_code·category_name)으로 식당·카페·명소·숙소 등을 나눠 식사·카페 규칙에 맞게 다룬다.
영업시간은 알 수 없어 하루 종일 연 것으로 본다.
"""
import logging
from typing import Optional

import httpx

from . import config
from .models import Category, Place

log = logging.getLogger(__name__)

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
CENTER = (35.1487, 126.9165)  # 원도심(동구) 근처. 여기서 가까운 결과부터
RADIUS_M = 20000  # 광주 안쪽
KAKAO_PREFIX = "kakao_"

# 카카오 업종 묶음 코드 -> 우리 유형. 묶음이 없으면 category_name("여행 > 관광,명소 > 산")의 낱말로 판단한다.
_GROUP = {"FD6": "food", "CE7": "cafe", "AT4": "sight", "CT1": "culture", "AD5": "lodging", "MT1": "shop"}
_NAME_HINTS = [
    ("전통시장", "market"),
    ("시장", "market"),
    ("숙박", "lodging"),
    ("카페", "cafe"),
    ("음식점", "food"),
    ("관광,명소", "sight"),
    ("공원", "sight"),
    ("문화시설", "culture"),
    ("미술관", "culture"),
    ("박물관", "culture"),
    ("공연장", "venue"),
    ("경기장", "venue"),
    ("쇼핑", "shop"),
]
DEFAULT_STAY = {"food": 60, "cafe": 60, "lodging": 30, "etc": 30}
# 업종 이름·장소 이름에 이 낱말이 있으면 기본 머무는 시간을 이만큼 잡는다(영화관을 1시간으로 잡지 않게). 앞에 있는 것이 먼저.
STAY_BY_WORD = [
    ("야구장", 210), ("경기장", 180), ("놀이공원", 240), ("테마파크", 240), ("영화관", 150), ("시네마", 150),
    ("극장", 150), ("공연장", 150), ("찜질방", 150), ("수족관", 90), ("아쿠아리움", 90), ("미술관", 90),
    ("박물관", 90), ("방탈출", 70), ("볼링", 70), ("노래방", 60), ("서점", 40),
]


def kakao_category(group_code: str, category_name: str) -> Category:
    if group_code in _GROUP:
        return _GROUP[group_code]
    return next((cat for word, cat in _NAME_HINTS if word in category_name), "etc")


def is_kakao_id(place_id: Optional[str]) -> bool:
    return bool(place_id) and place_id.startswith(KAKAO_PREFIX)


def kakao_place(doc: dict) -> Place:
    """카카오 검색 결과 한 건 -> Place (DB 에 없는 임시 장소)."""
    category = kakao_category(doc.get("category_group_code") or "", doc.get("category_name") or "")
    address = doc.get("road_address_name") or doc.get("address_name") or ""
    area = " ".join(address.split()[1:3]) or "광주"  # '전남광주통합특별시 동구 동명로 40' -> '동구 동명로'
    return Place(
        id=f"{KAKAO_PREFIX}{doc['id']}",
        name=doc["place_name"],
        category=category,
        area=area,
        lat=float(doc["y"]),
        lng=float(doc["x"]),
        description=doc.get("category_name") or "",
        stay_min=default_stay(category, f"{doc.get('category_name') or ''} {doc['place_name']}"),
    )


def default_stay(category: str, text: str) -> int:
    """카카오 장소의 기본 머무는 시간(분). 화면에 '기본 N' 으로 보이고, 사용자가 비워 두면 이 값을 보낸다."""
    return next((m for word, m in STAY_BY_WORD if word in text), DEFAULT_STAY.get(category, 60))


def search_kakao(query: str, size: int = 5) -> list[Place]:
    """광주 원도심에서 가까운 순. 키가 없거나 호출이 실패하면 빈 목록."""
    if not config.KAKAO_REST_API_KEY:
        return []
    try:
        res = httpx.get(
            KAKAO_KEYWORD_URL,
            params={"query": query, "y": CENTER[0], "x": CENTER[1], "radius": RADIUS_M, "size": size},
            headers={"Authorization": f"KakaoAK {config.KAKAO_REST_API_KEY}"},
            timeout=5,
        )
        res.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("카카오 장소 검색 실패 (%s): %s", query, e)
        return []
    return [kakao_place(d) for d in res.json().get("documents", [])]


def search_known(known: list[Place], query: str, size: int = 5) -> list[Place]:
    """등록된 장소 중 이름·별칭에 검색어가 들어간 곳(공백 무시)."""
    key = query.replace(" ", "")
    hits = [p for p in known if any(key in n.replace(" ", "") for n in [p.name, *p.aliases])]
    return hits[:size]
