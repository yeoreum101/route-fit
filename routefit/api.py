"""FastAPI 앱. 실행: uvicorn routefit.api:app --reload"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import checklist, courses, db
from . import tags as tag_vocab
from .admin import router as admin_router
from .config import WEB_DIR
from .data import load_anchors, load_places
from .models import Course, CourseSummary, Feedback, FeedbackIn, Place, PlanRequest, Stats
from .pipeline import make_course, warm_up
from .planner import PlanError
from .ratelimit import limit_plan

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.session().close()  # DB 연결 확인 · 테이블 생성 · 비어 있으면 시드
    # 임베딩 모델 로딩에 1분쯤 걸리므로, 서버가 뜨는 동안 뒤에서 미리 불러 둔다.
    threading.Thread(target=warm_up, daemon=True).start()
    yield


app = FastAPI(title="Route-Fit", lifespan=lifespan)
app.include_router(admin_router)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "db": db.engine().dialect.name,
        "places": len(load_places()),
        "anchors": len(load_anchors()),
    }


@app.get("/api/tags")
def tags() -> list[dict]:
    """장소 태그 목록 (data/tags.json)."""
    return tag_vocab.groups()


@app.get("/api/checklist")
def checklist_definition() -> dict:
    """현장조사 체크리스트 항목 (data/checklist.json)."""
    return checklist.definition()


@app.get("/api/anchors", response_model=list[Place])
def anchors():
    return load_anchors()


@app.get("/api/places", response_model=list[Place])
def places():
    return load_places()


# 동기 함수로 두어 LLM·최적화 호출이 스레드풀에서 돌게 한다.
@app.post("/api/plan", response_model=Course, dependencies=[Depends(limit_plan)])
def plan(req: PlanRequest):
    try:
        return make_course(req)
    except PlanError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/courses", response_model=list[CourseSummary])
def recent_courses(limit: int = Query(default=20, ge=1, le=100)):
    return courses.recent_courses(limit)


@app.get("/api/courses/{course_id}", response_model=Course)
def get_course(course_id: str):
    course = courses.get_course(course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다.")
    return course


@app.post("/api/courses/{course_id}/feedback", response_model=Feedback, status_code=201)
def feedback(course_id: str, fb: FeedbackIn):
    saved = courses.add_feedback(course_id, fb)
    if saved is None:
        raise HTTPException(status_code=404, detail="코스를 찾을 수 없습니다.")
    return saved


@app.get("/api/stats", response_model=Stats)
def stats():
    return courses.stats()


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
