"""FastAPI 앱. 실행: uvicorn routefit.api:app --reload"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .config import WEB_DIR
from .data import load_anchors, load_places
from .models import Course, Place, PlanRequest
from .pipeline import make_course, warm_up
from .planner import PlanError

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 임베딩 모델 로딩에 1분쯤 걸리므로, 서버가 뜨는 동안 뒤에서 미리 불러 둔다.
    threading.Thread(target=warm_up, daemon=True).start()
    yield


app = FastAPI(title="Route-Fit", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "places": len(load_places()), "anchors": len(load_anchors())}


@app.get("/api/anchors", response_model=list[Place])
def anchors():
    return load_anchors()


@app.get("/api/places", response_model=list[Place])
def places():
    return load_places()


# 동기 함수로 두어 LLM·최적화 호출이 스레드풀에서 돌게 한다.
@app.post("/api/plan", response_model=Course)
def plan(req: PlanRequest):
    try:
        return make_course(req)
    except PlanError as e:
        raise HTTPException(status_code=422, detail=str(e))


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
