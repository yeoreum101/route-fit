"""데이터셋 로딩과 이동시간."""
import json
import math
from functools import lru_cache

from .config import DATA_DIR
from .models import Place


def _load(name: str) -> list[Place]:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return [Place(**row) for row in json.load(f)]


@lru_cache
def load_places() -> list[Place]:
    """AI Discover 후보 장소."""
    return _load("places.json")


@lru_cache
def load_anchors() -> list[Place]:
    """Must Visit 로 자주 쓰이는 목적지(야구장·공연장 등). AI 추천 후보에는 들어가지 않는다."""
    return _load("anchors.json")


@lru_cache
def _travel_matrix() -> dict[str, int]:
    """지도 API 로 보정한 실거리 이동시간. {"출발id|도착id": 분}. 없으면 직선거리 추정."""
    path = DATA_DIR / "travel_matrix.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(a))


def travel_minutes(a, b) -> int:
    """a -> b 이동시간(분). a, b 는 id/lat/lng 를 가진 객체."""
    if a.id == b.id:
        return 0
    known = _travel_matrix().get(f"{a.id}|{b.id}")
    if known is not None:
        return int(known)
    km = haversine_km(a.lat, a.lng, b.lat, b.lng) * 1.3  # 도로 우회 보정
    if km <= 1.2:
        return max(2, round(km / 4.5 * 60))  # 도보
    return round(8 + km / 20 * 60)  # 대중교통·택시 (대기 8분 + 시속 20km)
