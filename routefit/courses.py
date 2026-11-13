"""생성된 코스 저장 · 공유 · 피드백 · 실증 지표 집계."""
import logging
import secrets
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from . import db
from .models import Course, CourseSummary, Feedback, FeedbackIn, PlannerStats, PlanRequest, Stats

log = logging.getLogger(__name__)


def exposure_rates(window: int, min_courses: int) -> dict[str, float]:
    """최근 코스 window 개에서 장소별 AI 추천 등장률(그 장소가 AI 추천으로 들어간 코스 수 / 코스 수).
    코스가 min_courses 개보다 적거나 DB 를 못 읽으면 빈 dict (감점 없음)."""
    try:
        with db.session() as s:
            rows = s.scalars(select(db.CourseRow.course).order_by(db.CourseRow.created_at.desc()).limit(window)).all()
    except SQLAlchemyError as e:
        log.warning("등장률 계산 실패: %s", e)
        return {}
    ai_sets = [{st["place_id"] for st in (c or {}).get("stops", []) if st.get("kind") == "ai"} for c in rows]
    ai_sets = [a for a in ai_sets if a]
    if len(ai_sets) < min_courses:
        return {}
    count = Counter(pid for a in ai_sets for pid in a)
    return {pid: k / len(ai_sets) for pid, k in count.items()}


def save_course(req: PlanRequest, course: Course) -> Optional[str]:
    """코스를 저장하고 id 를 돌려준다. 저장 실패가 코스 생성을 막지는 않는다(None)."""
    course_id = secrets.token_urlsafe(6)
    m = course.metrics
    try:
        with db.session() as s:
            s.add(
                db.CourseRow(
                    id=course_id,
                    query=req.query,
                    request=req.model_dump(mode="json"),
                    course=course.model_copy(update={"id": course_id}).model_dump(mode="json", exclude={"request"}),
                    planner=course.engine.get("planner", ""),
                    n_places=m.n_places,
                    n_ai_places=m.n_ai_places,
                    local_commerce_ratio=m.local_commerce_ratio,
                    travel_min=m.travel_min,
                    score=m.score,
                )
            )
            s.commit()
        return course_id
    except SQLAlchemyError as e:
        log.warning("코스 저장 실패: %s", e)
        return None


KST = timezone(timedelta(hours=9))  # 기간은 한국 날짜로 받는다(서머타임 없음). DB 에는 UTC 로 저장돼 있다


def _bound(day: date):
    """한국 날짜 0시 -> DB 와 비교할 시각. SQLite 는 시간대 없이 UTC 문자열로 저장하므로 시간대를 뗀다."""
    t = datetime.combine(day, time(), KST).astimezone(timezone.utc)
    return t.replace(tzinfo=None) if db.engine().dialect.name == "sqlite" else t


def in_period(column, start: Optional[date], end: Optional[date]) -> list:
    """created_at 이 start 0시 ~ end 다음 날 0시(한국 시각) 안인 조건. 비워 둔 쪽은 열어 둔다."""
    conds = []
    if start is not None:
        conds.append(column >= _bound(start))
    if end is not None:
        conds.append(column < _bound(end + timedelta(days=1)))
    return conds


def get_course(course_id: str) -> Optional[Course]:
    with db.session() as s:
        row = s.get(db.CourseRow, course_id)
        return Course(**{**row.course, "request": row.request}) if row else None


def recent_courses(limit: int, start: Optional[date] = None, end: Optional[date] = None) -> list[CourseSummary]:
    C = db.CourseRow
    with db.session() as s:
        rows = s.scalars(select(C).where(*in_period(C.created_at, start, end)).order_by(C.created_at.desc()).limit(limit))
        return [
            CourseSummary(
                id=r.id,
                created_at=r.created_at,
                query=r.query,
                planner=r.planner,
                n_places=r.n_places,
                local_commerce_ratio=r.local_commerce_ratio,
                score=r.score,
            )
            for r in rows
        ]


def add_feedback(course_id: str, fb: FeedbackIn) -> Optional[Feedback]:
    with db.session() as s:
        if s.get(db.CourseRow, course_id) is None:
            return None
        row = db.FeedbackRow(course_id=course_id, rating=fb.rating, comment=fb.comment)
        s.add(row)
        s.commit()
        return Feedback(id=row.id, course_id=course_id, rating=row.rating, comment=row.comment, created_at=row.created_at)


def recent_feedback(limit: int, start: Optional[date] = None, end: Optional[date] = None) -> list[Feedback]:
    F = db.FeedbackRow
    with db.session() as s:
        rows = s.scalars(select(F).where(*in_period(F.created_at, start, end)).order_by(F.id.desc()).limit(limit))
        return [
            Feedback(id=r.id, course_id=r.course_id, rating=r.rating, comment=r.comment, created_at=r.created_at)
            for r in rows
        ]


def stats(top: int = 10, start: Optional[date] = None, end: Optional[date] = None) -> Stats:
    """실증 비교 지표. 코스 생성기(planner)별로 평균을 낸다. start·end(한국 날짜, 끝 날 포함)를 주면 그 기간에 만든 코스·평가만."""
    C = db.CourseRow
    period = in_period(C.created_at, start, end)
    with db.session() as s:
        by_planner = {
            planner: PlannerStats(
                courses=n,
                avg_places=round(places, 2),
                avg_ai_places=round(ai, 2),
                avg_travel_min=round(travel, 1),
                avg_local_commerce_ratio=round(ratio, 3),
                avg_score=round(score, 3),
            )
            for planner, n, places, ai, travel, ratio, score in s.execute(
                select(
                    C.planner,
                    func.count(),
                    func.avg(C.n_places),
                    func.avg(C.n_ai_places),
                    func.avg(C.travel_min),
                    func.avg(C.local_commerce_ratio),
                    func.avg(C.score),
                ).where(*period).group_by(C.planner)
            )
        }
        F = db.FeedbackRow
        n_feedback, avg_rating = s.execute(
            select(func.count(), func.avg(F.rating)).where(*in_period(F.created_at, start, end))
        ).one()

        counts: Counter[str] = Counter()
        names: dict[str, str] = {}
        for course in s.scalars(select(C.course).where(*period)):
            for stop in course["stops"]:
                if stop["kind"] == "ai":
                    counts[stop["place_id"]] += 1
                    names[stop["place_id"]] = stop["name"]

    return Stats(
        courses=sum(p.courses for p in by_planner.values()),
        feedback=n_feedback,
        avg_rating=round(float(avg_rating), 2) if avg_rating is not None else None,
        by_planner=by_planner,
        top_places=[{"place_id": pid, "name": names[pid], "count": n} for pid, n in counts.most_common(top)],
    )
