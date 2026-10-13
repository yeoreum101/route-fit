import pytest
from fastapi.testclient import TestClient

from routefit import config
from routefit.api import app
from routefit.data import load_places

client = TestClient(app)

QUERY = "토요일 야구 보기 전에 사진 찍기 좋은 데랑 로컬 맛집 가고 싶어. 예산 10만원"
NEW_PLACE = {
    "id": "test_lp_bar",
    "name": "테스트 LP바",
    "category": "night",
    "area": "동구 동명동",
    "lat": 35.1475,
    "lng": 126.9260,
    "description": "LP 음악 바이닐 레코드 재즈 음악 감상",
    "open": "18:00",
    "close": "25:00",
    "stay_min": 60,
    "cost": 15000,
}


@pytest.fixture
def restore_places():
    """장소를 고치는 테스트가 끝나면 data/*.json 기준으로 되돌린다."""
    yield
    assert client.post("/api/admin/import").status_code == 200


def plan(**body):
    res = client.post("/api/plan", json={"query": QUERY, **body})
    assert res.status_code == 200, res.text
    return res.json()


def test_course_is_saved_and_shareable():
    course = plan(must_visits=[{"id": "champions_field", "start": "18:30"}])
    assert course["id"]

    shared = client.get(f"/api/courses/{course['id']}").json()
    assert shared == course
    assert course["id"] in [c["id"] for c in client.get("/api/courses").json()]
    assert client.get("/api/courses/nope").status_code == 404


def test_feedback_and_stats():
    course = plan(planner="ortools")
    before = client.get("/api/stats").json()

    assert client.post(f"/api/courses/{course['id']}/feedback", json={"rating": 6}).status_code == 422
    assert client.post("/api/courses/nope/feedback", json={"rating": 5}).status_code == 404
    res = client.post(f"/api/courses/{course['id']}/feedback", json={"rating": 5, "comment": "좋아요"})
    assert res.status_code == 201

    after = client.get("/api/stats").json()
    assert after["feedback"] == before["feedback"] + 1
    assert after["by_planner"]["ortools"]["courses"] >= 1
    assert after["top_places"] and after["top_places"][0]["count"] >= 1


def test_added_place_is_used_without_restart(restore_places):
    query = "밤에 LP 바이닐 레코드 재즈 음악 감상"
    assert client.post("/api/admin/places", json=NEW_PLACE).status_code == 201
    assert client.post("/api/admin/places", json=NEW_PLACE).status_code == 409
    assert "test_lp_bar" in [p["id"] for p in client.get("/api/places").json()]
    assert "test_lp_bar" in [s["place_id"] for s in plan(query=query, day_start="18:00")["stops"]]

    assert client.delete("/api/admin/places/test_lp_bar").status_code == 204
    assert "test_lp_bar" not in [p.id for p in load_places()]
    assert "test_lp_bar" not in [s["place_id"] for s in plan(query=query, day_start="18:00")["stops"]]


def test_patch_and_validation(restore_places):
    res = client.patch("/api/admin/places/acc", json={"verified": True, "cost": 5000})
    assert res.status_code == 200
    assert (res.json()["verified"], res.json()["cost"]) == (True, 5000)
    assert client.get("/api/admin/places", params={"verified": True}).json()[0]["id"] == "acc"

    assert client.patch("/api/admin/places/acc", json={"open": "19:00", "close": "18:00"}).status_code == 422
    assert client.patch("/api/admin/places/acc", json={"gwangju_ness": 7}).status_code == 422
    assert client.patch("/api/admin/places/nope", json={"cost": 1}).status_code == 404
    bad = {**NEW_PLACE, "category": "zoo"}
    assert client.post("/api/admin/places", json=bad).status_code == 422


def test_ratings_are_averaged(restore_places):
    for rater, g in [("a", 5), ("b", 4), ("c", 3)]:
        res = client.put(
            "/api/admin/places/plaza_518/ratings",
            json={"rater": rater, "gwangju_ness": g, "stay_inducement": 2, "commerce_link": 1},
        )
        assert res.status_code == 200
    place = res.json()
    assert (place["gwangju_ness"], place["commerce_link"], place["n_ratings"]) == (4.0, 1.0, 3)
    # 같은 사람이 다시 채점하면 덮어쓴다
    client.put("/api/admin/places/plaza_518/ratings", json={"rater": "c", "gwangju_ness": 5, "stay_inducement": 2, "commerce_link": 1})
    assert client.get("/api/admin/places/plaza_518").json()["gwangju_ness"] == pytest.approx(4.67)
    assert len(client.get("/api/admin/places/plaza_518/ratings").json()) == 3
    assert client.delete("/api/admin/places/plaza_518/ratings/a").json()["gwangju_ness"] == 4.5
    # 알고리즘이 쓰는 장소 데이터에도 바로 반영된다
    assert next(p for p in load_places() if p.id == "plaza_518").gwangju_ness == 4.5


def test_travel_times(restore_places):
    from routefit.data import travel_minutes

    a, b = (next(p for p in load_places() if p.id == i) for i in ("acc", "daein_market"))
    assert client.put("/api/admin/travel-times", json=[{"from_id": "acc", "to_id": "daein_market", "minutes": 42}]).status_code == 200
    assert travel_minutes(a, b) == 42
    assert client.put("/api/admin/travel-times", json=[{"from_id": "acc", "to_id": "nope", "minutes": 1}]).status_code == 422
    assert client.get("/api/admin/export").json()["travel_matrix"] == {"acc|daein_market": 42}


def test_export_matches_seed():
    import json

    out = client.get("/api/admin/export").json()
    with open(config.DATA_DIR / "places.json", encoding="utf-8") as f:
        assert {p["id"] for p in out["places"]} == {p["id"] for p in json.load(f)}
    assert {p["id"] for p in out["anchors"]} == {"champions_field", "arts_center", "kdj_convention"}


def test_admin_token(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "secret")
    assert client.get("/api/admin/places").status_code == 401
    assert client.get("/api/admin/places", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.get("/api/admin/places", headers={"X-Admin-Token": "secret"}).status_code == 200
    assert client.get("/api/places").status_code == 200  # 공개 API 는 토큰 없이
