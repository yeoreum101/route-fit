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
    inspect,
    select,
    text,
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
    tags: Mapped[Optional[dict]] = mapped_column(Json, default=dict, nullable=True)
    aliases: Mapped[list] = mapped_column(Json, default=list)
    # '25:00' 처럼 자정을 넘기는 표기를 쓰므로 TIME 이 아닌 문자열
    open_time: Mapped[str] = mapped_column(String(5), default="00:00")
    close_time: Mapped[str] = mapped_column(String(5), default="24:00")
    break_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    break_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
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


class ChecklistRow(Base):
    """현장조사 체크리스트 (팀원 1명 × 장소 1곳). 항목 정의는 data/checklist.json, 계산은 checklist.py.

    예전의 점수 채점 테이블(place_ratings)은 더 쓰지 않는다. 기존 DB 에 남아 있어도 무시된다.
    """

    __tablename__ = "place_checklists"

    place_id: Mapped[str] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), primary_key=True)
    rater: Mapped[str] = mapped_column(String(50), primary_key=True)
    checks: Mapped[dict] = mapped_column(Json, default=dict)  # {항목 key: 체크 여부} (수동 항목만)
    evidence: Mapped[dict] = mapped_column(Json, default=dict)  # {항목 key: 근거 링크·메모}
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
                _add_missing_columns()
                with _sessionmaker()() as s:
                    if s.scalar(select(func.count()).select_from(PlaceRow)) == 0:
                        seed(s)
                _initialized = True
    return _sessionmaker()()


def _add_missing_columns() -> None:
    """create_all 은 이미 있는 테이블에 새 컬럼을 넣지 않는다. 마이그레이션 도구 대신, 나중에 추가한 컬럼만 여기서 넣는다.

    places.tags: 태그 도입 전 DB 면 컬럼을 만들고, data/places.json 에 같은 id 가 있으면 그 태그로 채운다.
    places.break_start · break_end: 브레이크 타임 도입 전 DB 면 컬럼을 만들고, data/places.json 의 값으로 채운다.
    """
    columns = {c["name"] for c in inspect(engine()).get_columns("places")}
    if "tags" not in columns:
        column_type = "JSONB" if engine().dialect.name == "postgresql" else "JSON"
        with engine().begin() as conn:
            conn.execute(text(f"ALTER TABLE places ADD COLUMN tags {column_type}"))
        seed_tags = {p["id"]: p["tags"] for p in (_read_json("places.json") or []) if p.get("tags")}
        with _sessionmaker()() as s:
            for row in s.scalars(select(PlaceRow).where(PlaceRow.id.in_(seed_tags))):
                row.tags = seed_tags[row.id]
            s.commit()
        log.info("places.tags 컬럼 추가, 예시 태그 %d곳 채움", len(seed_tags))
    if "break_start" not in columns:
        with engine().begin() as conn:
            conn.execute(text("ALTER TABLE places ADD COLUMN break_start VARCHAR(5)"))
            conn.execute(text("ALTER TABLE places ADD COLUMN break_end VARCHAR(5)"))
        seed_breaks = {p["id"]: p for p in (_read_json("places.json") or []) if p.get("break_start")}
        with _sessionmaker()() as s:
            for row in s.scalars(select(PlaceRow).where(PlaceRow.id.in_(seed_breaks))):
                row.break_start, row.break_end = seed_breaks[row.id]["break_start"], seed_breaks[row.id]["break_end"]
            s.commit()
        log.info("places.break_start · break_end 컬럼 추가, 브레이크 타임 %d곳 채움", len(seed_breaks))


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
    """장소·이동시간·체크리스트를 data/*.json 기준으로 다시 채운다. DB 에서만 고친 내용은 지워진다."""
    from .models import Place  # 검증용. models 는 db 를 import 하지 않는다.

    s.execute(delete(TravelRow))
    s.execute(delete(ChecklistRow))
    s.execute(delete(PlaceRow))
    counts = {"candidate": 0, "anchor": 0, "travel": 0, "checklists": 0}
    for name, kind in (("places.json", "candidate"), ("anchors.json", "anchor")):
        for raw in _read_json(name) or []:
            s.add(place_row(Place(**raw).model_dump(), kind))
            counts[kind] += 1
    s.flush()
    known = set(s.scalars(select(PlaceRow.id)))
    # 값은 {"minutes": 분, "mode": "transit"|"car"|null}. 예전 형식(분 숫자만)도 읽는다.
    for key, value in (_read_json("travel_matrix.json") or {}).items():
        a, b = key.split("|")
        if a in known and b in known:
            minutes, mode = (value["minutes"], value.get("mode")) if isinstance(value, dict) else (value, None)
            s.add(TravelRow(from_id=a, to_id=b, minutes=int(minutes), mode=mode))
            counts["travel"] += 1
    # 관리 화면 '내보내기'로 받은 체크리스트 (장소 점수는 places.json 에 이미 계산돼 있다)
    for place_id, sheets in (_read_json("checklists.json") or {}).items():
        if place_id in known:
            for sheet in sheets:
                s.add(ChecklistRow(place_id=place_id, rater=sheet["rater"], checks=sheet["checks"], evidence=sheet.get("evidence", {})))
                counts["checklists"] += 1
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
