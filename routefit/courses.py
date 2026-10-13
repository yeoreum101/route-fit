"""생성된 코스 저장 · 공유 · 피드백 · 실증 지표 집계."""
import logging
import secrets
from collections import Counter
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from . import db
from .models import Course, CourseSummary, Feedback, FeedbackIn, PlannerStats, PlanRequest, Stats

log = logging.getLogger(__name__)


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
                    course=course.model_copy(update={"id": course_id}).model_dump(mode="json"),
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


def get_course(course_id: str) -> Optional[Course]:
    with db.session() as s:
        row = s.get(db.CourseRow, course_id)
        return Course(**row.course) if row else None


def recent_courses(limit: int) -> list[CourseSummary]:
    with db.session() as s:
        rows = s.scalars(select(db.CourseRow).order_by(db.CourseRow.created_at.desc()).limit(limit))
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


def stats(top: int = 10) -> Stats:
    """실증 비교 지표. 코스 생성기(planner)별로 평균을 낸다."""
    C = db.CourseRow
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
                ).group_by(C.planner)
            )
        }
        n_feedback, avg_rating = s.execute(select(func.count(), func.avg(db.FeedbackRow.rating))).one()

        counts: Counter[str] = Counter()
        names: dict[str, str] = {}
        for course in s.scalars(select(C.course)):
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
