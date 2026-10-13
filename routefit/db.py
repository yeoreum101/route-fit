"""데이터베이스: 장소 · 현장조사 채점 · 이동시간 · 생성된 코스 · 사용자 피드백.

DATABASE_URL 이 없으면 data/routefit.db (SQLite) 를 쓴다. 시연 때는 docker compose 의 PostgreSQL.
테이블이 비어 있으면 data/*.json 으로 채운다(시드). 명령줄:

    python -m routefit.db reset   # 장소·이동시간을 data/*.json 기준으로 다시 채움 (코스·피드백은 유지)
"""
import json
import logging
import sys
import threading
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from . import config

log = logging.getLogger(__name__)

Json = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PlaceRow(Base):
    """장소 1건. kind='candidate' 는 AI 추천 후보, 'anchor' 는 Must Visit 목적지(추천 후보에서 제외)."""

    __tablename__ = "places"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(16))
    area: Mapped[str] = mapped_column(String(100))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")
    aliases: Mapped[list] = mapped_column(Json, default=list)
    # '25:00' 처럼 자정을 넘기는 표기를 쓰므로 TIME 이 아닌 문자열
    open_time: Mapped[str] = mapped_column(String(5), default="00:00")
    close_time: Mapped[str] = mapped_column(String(5), default="24:00")
    closed_days: Mapped[list] = mapped_column(Json, default=list)
    stay_min: Mapped[int] = mapped_column(Integer, default=60)
    cost: Mapped[int] = mapped_column(Integer, default=0)
    # 현장조사 3속성. place_ratings 가 있으면 그 평균으로 덮어쓴다.
    gwangju_ness: Mapped[float] = mapped_column(Float, default=3.0)
    stay_inducement: Mapped[float] = mapped_column(Float, default=3.0)
    commerce_link: Mapped[float] = mapped_column(Float, default=3.0)
    is_local_commerce: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class RatingRow(Base):
    """현장조사 채점 원점수 (팀원 1명 × 장소 1곳)."""

    __tablename__ = "place_ratings"

    place_id: Mapped[str] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), primary_key=True)
    rater: Mapped[str] = mapped_column(String(50), primary_key=True)
    gwangju_ness: Mapped[float] = mapped_column(Float)
    stay_inducement: Mapped[float] = mapped_column(Float)
    commerce_link: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class TravelRow(Base):
    """지도 API 로 구한 실제 이동시간(분). 없으면 직선거리로 추정한다."""

    __tablename__ = "travel_times"

    from_id: Mapped[str] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), primary_key=True)
    to_id: Mapped[str] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), primary_key=True)
    minutes: Mapped[int] = mapped_column(Integer)
    mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class CourseRow(Base):
    """생성된 코스. 공유 링크와 실증 지표 집계에 쓴다. 개인 식별 정보는 저장하지 않는다."""

    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    query: Mapped[str] = mapped_column(Text)
    request: Mapped[dict] = mapped_column(Json)
    course: Mapped[dict] = mapped_column(Json)  # 생성 당시의 Course 전체 (장소가 나중에 바뀌어도 그대로)
    # 집계용으로 꺼내 둔 값
    planner: Mapped[str] = mapped_column(String(16))
    n_places: Mapped[int] = mapped_column(Integer)
    n_ai_places: Mapped[int] = mapped_column(Integer)
    local_commerce_ratio: Mapped[float] = mapped_column(Float)
    travel_min: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)


class FeedbackRow(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------- 연결 ----------


@lru_cache
def engine() -> Engine:
    url = config.DATABASE_URL
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def _sessionmaker() -> sessionmaker:
    return sessionmaker(engine(), expire_on_commit=False)


_init_lock = threading.Lock()
_initialized = False


def session() -> Session:
    """테이블이 준비된 세션. 처음 호출될 때 테이블을 만들고, 장소가 비어 있으면 시드를 넣는다."""
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                Base.metadata.create_all(engine())
                with _sessionmaker()() as s:
                    if s.scalar(select(func.count()).select_from(PlaceRow)) == 0:
                        seed(s)
                _initialized = True
    return _sessionmaker()()


# ---------- 시드 ----------


def _read_json(name: str) -> Any:
    path = config.DATA_DIR / name
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def place_row(data: dict, kind: str) -> PlaceRow:
    """Place 형식의 dict -> PlaceRow."""
    data = dict(data)
    data["open_time"] = data.pop("open", "00:00")
    data["close_time"] = data.pop("close", "24:00")
    return PlaceRow(kind=kind, **data)


def seed(s: Session) -> dict[str, int]:
    """장소·이동시간을 data/*.json 기준으로 다시 채운다. 채점 원점수도 함께 지워진다."""
    from .models import Place  # 검증용. models 는 db 를 import 하지 않는다.

    s.execute(delete(TravelRow))
    s.execute(delete(RatingRow))
    s.execute(delete(PlaceRow))
    counts = {"candidate": 0, "anchor": 0, "travel": 0}
    for name, kind in (("places.json", "candidate"), ("anchors.json", "anchor")):
        for raw in _read_json(name) or []:
            s.add(place_row(Place(**raw).model_dump(), kind))
            counts[kind] += 1
    s.flush()
    known = set(s.scalars(select(PlaceRow.id)))
    for key, minutes in (_read_json("travel_matrix.json") or {}).items():
        a, b = key.split("|")
        if a in known and b in known:
            s.add(TravelRow(from_id=a, to_id=b, minutes=int(minutes)))
            counts["travel"] += 1
    s.commit()
    log.info("시드 완료: %s", counts)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["reset"]:
        with session() as s:
            print(seed(s))
    else:
        with session() as s:
            print("places:", s.scalar(select(func.count()).select_from(PlaceRow)), "@", engine().url.render_as_string())
