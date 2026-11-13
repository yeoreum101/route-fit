"""인기 장소 쏠림: 최근 코스에 자주 나온 곳은 감점해서 덜 고른다."""
from routefit import config, pipeline
from routefit.courses import exposure_rates
from routefit.diversity import _stats
from routefit.models import PlanRequest
from routefit.pipeline import make_course

QUERY = "5·18 역사 공부하는 하루"


def _ai(course):
    return {s.place_id for s in course.stops if s.kind == "ai"}


def test_exposure_rates_count_ai_places_in_recent_courses():
    course = make_course(PlanRequest(query=QUERY))
    rates = exposure_rates(window=1, min_courses=1)
    assert set(rates) == _ai(course) and all(r == 1.0 for r in rates.values())  # 가장 최근 1개 코스: 모두 100%
    assert exposure_rates(window=1, min_courses=2) == {}  # 코스가 모자라면 재지 않는다


def test_popular_place_is_penalized(monkeypatch):
    base = _ai(make_course(PlanRequest(query=QUERY)))
    assert "jeonil245" in base  # 역사 하루에는 전일빌딩245 가 들어간다

    monkeypatch.setattr(config, "POPULARITY_WEIGHT", 3.0)
    monkeypatch.setattr(pipeline, "exposure_rates", lambda window, min_courses: {"jeonil245": 1.0})
    assert "jeonil245" not in _ai(make_course(PlanRequest(query=QUERY)))  # 모든 코스에 나왔다면 다른 곳으로

    monkeypatch.setattr(pipeline, "exposure_rates", lambda window, min_courses: {"jeonil245": config.POPULARITY_TARGET})
    assert "jeonil245" in _ai(make_course(PlanRequest(query=QUERY)))  # 목표 등장률 이하는 감점 없음


def test_stats_measure_concentration():
    s = _stats([["a", "b"], ["a", "c"], ["a"], ["d"]], n_candidates=8)
    assert s["count"]["a"] == 3 and s["top_rate"] == 0.75
    assert s["coverage"] == 0.5  # a b c d / 8


def test_stats_period_filters_courses_and_feedback():
    """실증 통계 기간: 한국 날짜로 시작일~종료일(끝 날 포함). 그 기간에 만든 코스·평가만 센다."""
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from routefit.api import app

    client = TestClient(app)
    course = client.post("/api/plan", json={"query": QUERY}).json()
    client.post(f"/api/courses/{course['id']}/feedback", json={"rating": 5, "comment": "좋아요"})
    today = datetime.now(timezone(timedelta(hours=9))).date()
    tomorrow, yesterday = today + timedelta(days=1), today - timedelta(days=1)

    now = client.get("/api/stats", params={"start": today.isoformat(), "end": today.isoformat()}).json()
    assert now["courses"] >= 1 and now["feedback"] >= 1 and now["top_places"]
    later = client.get("/api/stats", params={"start": tomorrow.isoformat()}).json()
    assert (later["courses"], later["feedback"], later["top_places"]) == (0, 0, [])
    before = client.get("/api/stats", params={"end": yesterday.isoformat()}).json()
    assert before["courses"] == 0
    assert client.get("/api/stats").json()["courses"] >= now["courses"]  # 기간 없이: 전체

    ids = [c["id"] for c in client.get("/api/courses", params={"limit": 50, "start": today.isoformat()}).json()]
    assert course["id"] in ids
    assert client.get("/api/courses", params={"start": tomorrow.isoformat()}).json() == []
    assert client.get("/api/admin/feedback", params={"start": tomorrow.isoformat()}).json() == []
    assert client.get("/api/stats", params={"start": today.isoformat(), "end": yesterday.isoformat()}).status_code == 422
