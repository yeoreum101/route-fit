"""데이터셋 로딩과 이동시간. 원본은 DB(db.py), 처음 실행할 때 data/*.json 으로 채워진다."""
import math
from functools import lru_cache
from typing import Literal, Optional

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
        break_start=row.break_start,
        break_end=row.break_end,
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
def _travel_matrix() -> dict[str, tuple[int, Optional[str]]]:
    """지도 API 로 보정한 실거리 이동시간. {"출발id|도착id": (분, 이동 수단)}. 없으면 직선거리 추정."""
    with db.session() as s:
        return {f"{r.from_id}|{r.to_id}": (r.minutes, r.mode) for r in s.scalars(select(db.TravelRow))}


def invalidate() -> None:
    """장소·이동시간이 바뀌었을 때 호출. 임베딩 인덱스는 load_places() 결과가 바뀐 것을 보고 다시 만든다."""
    load_places.cache_clear()
    load_anchors.cache_clear()
    _travel_matrix.cache_clear()


def invalidate_travel() -> None:
    """이동시간만 새로 저장했을 때 호출 (장소 캐시·임베딩 인덱스는 그대로 둔다)."""
    _travel_matrix.cache_clear()


def is_measured(a, b) -> bool:
    """a -> b 이동시간이 DB 에 있는지(길찾기 API 로 잰 값)."""
    return f"{a.id}|{b.id}" in _travel_matrix()


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(a))


# 실측값이 없을 때 쓰는 어림값. 후보를 비교할 때만 쓰고, 코스에 들어간 구간은 travel.measure_route 가
# TMAP 으로 재서 DB 에 저장한 뒤 그 값으로 시간표를 다시 짠다. 여행자는 걷거나 시내버스를 탄다고 본다.
# ODsay 대중교통 실측 29구간(도로 1.7~6.9km, 2026-10-26)과 비교해 평균 2.2분, 최대 6분 차이.
# 같은 구간에서 자동차 추정(시속 20km + 5분)은 평균 13분 짧게 나왔다.
ROAD_DETOUR = 1.3  # 직선거리 -> 도로 거리
WALK_KM = 1.2  # 도로 거리가 이 이하면 걷는다 (시속 4.5km 로 16분)
WALK_KMH = 4.5
BUS_ACCESS_MIN = 6  # 정류장까지 걷기 + 내려서 걷기
BUS_WAIT_MIN = 7  # 평균 대기 (배차 15분 안팎의 절반)
BUS_KMH = 15  # 정차·신호를 포함한 도심 버스 평균 속도
CAR_OVERHEAD_MIN = 5  # 카카오 자동차 길찾기(routefit.travel) 실측값에 더하는 승차·주차


def travel_minutes(a, b) -> int:
    """a -> b 이동시간(분). a, b 는 id/lat/lng 를 가진 객체.
    travel_times 에 실측값이 있으면 그것을, 없으면 도보·시내버스 어림값을 쓴다."""
    if a.id == b.id:
        return 0
    known = _travel_matrix().get(f"{a.id}|{b.id}")
    if known is not None:
        return int(known[0])
    km = _road_km(a, b)
    if km <= WALK_KM:
        return max(2, round(km / WALK_KMH * 60))
    return round(BUS_ACCESS_MIN + BUS_WAIT_MIN + km / BUS_KMH * 60)


TravelMode = Literal["walk", "transit", "car"]


def travel_mode(a, b) -> TravelMode:
    """a -> b 를 무엇으로 가는지(travel_minutes 와 같은 기준). 실측값이 있으면 그 수단,
    없거나 수단을 모르면 도로 거리 WALK_KM 이하는 도보, 그보다 멀면 대중교통(시내버스)."""
    known = _travel_matrix().get(f"{a.id}|{b.id}")
    if known is not None and known[1] in ("walk", "transit", "car"):
        return known[1]
    return "walk" if _road_km(a, b) <= WALK_KM else "transit"


def _road_km(a, b) -> float:
    return haversine_km(a.lat, a.lng, b.lat, b.lng) * ROAD_DETOUR
