"""데이터셋 로딩과 이동시간. 원본은 DB(db.py), 처음 실행할 때 data/*.json 으로 채워진다."""
import math
from functools import lru_cache

from sqlalchemy import select

from . import db
from .models import Place


def to_place(row: db.PlaceRow) -> Place:
    return Place(
        id=row.id,
        name=row.name,
        category=row.category,
        area=row.area,
        lat=row.lat,
        lng=row.lng,
        description=row.description,
        tags=row.tags or {},
        aliases=row.aliases or [],
        open=row.open_time,
        close=row.close_time,
        closed_days=row.closed_days or [],
        stay_min=row.stay_min,
        cost=row.cost,
        gwangju_ness=row.gwangju_ness,
        stay_inducement=row.stay_inducement,
        commerce_link=row.commerce_link,
        is_local_commerce=row.is_local_commerce,
        verified=row.verified,
    )


def _load(kind: str) -> list[Place]:
    with db.session() as s:
        rows = s.scalars(select(db.PlaceRow).where(db.PlaceRow.kind == kind).order_by(db.PlaceRow.id))
        return [to_place(r) for r in rows]


# 요청마다 DB 를 읽지 않도록 캐시한다. 장소를 고치면 invalidate() 로 비운다.
@lru_cache
def load_places() -> list[Place]:
    """AI Discover 후보 장소."""
    return _load("candidate")


@lru_cache
def load_anchors() -> list[Place]:
    """Must Visit 로 자주 쓰이는 목적지(야구장·공연장 등). AI 추천 후보에는 들어가지 않는다."""
    return _load("anchor")


@lru_cache
def _travel_matrix() -> dict[str, int]:
    """지도 API 로 보정한 실거리 이동시간. {"출발id|도착id": 분}. 없으면 직선거리 추정."""
    with db.session() as s:
        return {f"{r.from_id}|{r.to_id}": r.minutes for r in s.scalars(select(db.TravelRow))}


def invalidate() -> None:
    """장소·이동시간이 바뀌었을 때 호출. 임베딩 인덱스는 load_places() 결과가 바뀐 것을 보고 다시 만든다."""
    load_places.cache_clear()
    load_anchors.cache_clear()
    _travel_matrix.cache_clear()


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(a))


# 실측값이 없을 때 쓰는 추정치. 여행자는 걷거나 시내버스를 탄다고 본다.
ROAD_DETOUR = 1.3  # 직선거리 -> 도로 거리
WALK_KM = 1.2  # 도로 거리가 이 이하면 걷는다
WALK_KMH = 4.5
BUS_ACCESS_MIN = 6  # 정류장까지 걷기 + 내려서 걷기
BUS_WAIT_MIN = 7  # 평균 대기 (배차 15분 안팎의 절반)
BUS_KMH = 15  # 정차·신호를 포함한 도심 버스 평균 속도


def travel_minutes(a, b) -> int:
    """a -> b 이동시간(분). a, b 는 id/lat/lng 를 가진 객체.
    travel_times 에 실측값이 있으면 그것을, 없으면 도보·시내버스 추정치를 쓴다."""
    if a.id == b.id:
        return 0
    known = _travel_matrix().get(f"{a.id}|{b.id}")
    if known is not None:
        return int(known)
    km = haversine_km(a.lat, a.lng, b.lat, b.lng) * ROAD_DETOUR
    if km <= WALK_KM:
        return max(2, round(km / WALK_KMH * 60))
    return round(BUS_ACCESS_MIN + BUS_WAIT_MIN + km / BUS_KMH * 60)
