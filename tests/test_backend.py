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
    request = shared.pop("request")
    assert course.pop("request") is None  # 생성 응답에는 넣지 않는다
    assert shared == course
    assert request["must_visits"][0]["id"] == "champions_field" and request["query"] == QUERY
    assert course["id"] in [c["id"] for c in client.get("/api/courses").json()]
    assert client.get("/api/courses/nope").status_code == 404


def test_feedback_and_stats():
    course = plan(planner="ortools")
    before = client.get("/api/stats").json()

    assert client.post(f"/api/courses/{course['id']}/feedback", json={"rating": 6}).status_code == 422
    assert client.post("/api/courses/nope/feedback", json={"rating": 5}).status_code == 404
    res = client.post(f"/api/courses/{course['id']}/feedback", json={"rating": 5, "comment": "좋아요"})
    assert res.status_code == 201

    assert client.get("/api/admin/feedback").json()[0]["comment"] == "좋아요"
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


def test_checklist_scores(restore_places):
    """5·18민주광장: 체류 20분 · 지출 0원 · 할 거리 2개 · 24시까지 운영 → 자동 항목 2개 체크."""
    url = "/api/admin/places/plaza_518/checklists"
    a = {"rater": "a", "checks": {"history_site": True, "not_franchise": True, "seating": True},
         "evidence": {"history_site": "5·18 사적지"}}
    b = {"rater": "b", "checks": {"history_site": True, "not_franchise": True, "market_zone": True}}
    assert client.put(url, json=a).status_code == 200
    place = client.put(url, json=b).json()
    assert (place["gwangju_ness"], place["commerce_link"], place["stay_inducement"]) == (2.0, 2.5, 3.5)
    assert place["is_local_commerce"] is True and place["n_ratings"] == 2  # 프랜차이즈 아님 + 시장 구역(절반)

    view = client.get(url).json()
    items = {i["key"]: i for i in view["evaluation"]["items"]}
    assert items["market_zone"]["disagree"] and items["seating"]["disagree"]
    assert items["open_evening"]["auto"] and items["open_evening"]["value"] == 1
    assert view["sheets"][0]["evidence"] == {"history_site": "5·18 사적지"}
    # 알고리즘이 쓰는 장소 데이터에도 바로 반영된다
    assert next(p for p in load_places() if p.id == "plaza_518").commerce_link == 2.5

    place = client.delete(f"{url}/b").json()
    assert (place["commerce_link"], place["stay_inducement"], place["is_local_commerce"]) == (2.0, 4.0, False)
    # 장소 정보가 바뀌면 자동 항목도 다시 계산한다 (지출 0원 → 3,000원)
    assert client.patch("/api/admin/places/plaza_518", json={"cost": 3000}).json()["commerce_link"] == 3.0

    assert client.put(url, json={"rater": "c", "checks": {"spending": True}}).status_code == 422  # 자동 항목
    assert client.put(url, json={"rater": "c", "checks": {"nope": True}}).status_code == 422
    assert client.put(url, json={"rater": "c", "evidence": {"nope": "x"}}).status_code == 422
    assert client.delete(f"{url}/zzz").status_code == 404
    assert client.get("/api/admin/export").json()["checklists"]["plaza_518"][0]["rater"] == "a"
    assert len(client.get("/api/checklist").json()["items"]) == 12


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


def test_rate_limit(monkeypatch):
    from routefit import ratelimit

    monkeypatch.setattr(config, "PLAN_RATE_PER_MIN", 2)
    ratelimit.reset()
    body = {"query": QUERY}
    assert [client.post("/api/plan", json=body).status_code for _ in range(3)] == [200, 200, 429]
    res = client.post("/api/plan", json=body)
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    ratelimit.reset()


def test_travel_builder_with_mocked_kakao(restore_places):
    import httpx

    from routefit import data, travel

    calls = []

    def kakao(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["origin"])
        return httpx.Response(200, json={"routes": [{"result_code": 0, "summary": {"duration": 601}}]})

    with httpx.Client(transport=httpx.MockTransport(kakao)) as mock:
        result = travel.build(mock, pause_s=0)
    assert result["called"] == len(calls) > 0 and result["failed"] == 0
    data.invalidate()

    a, b = travel.pairs(data.load_anchors() + data.load_places(), both_ways=False)[0]
    expected = 11 + travel.CAR_OVERHEAD_MIN  # 601초 -> 11분 + 승차·주차
    assert data.travel_minutes(a, b) == data.travel_minutes(b, a) == expected

    with httpx.Client(transport=httpx.MockTransport(kakao)) as mock:
        assert travel.build(mock, pause_s=0)["called"] == 0  # 이미 채운 구간은 다시 부르지 않는다


def test_tags_validation_and_embedding(restore_places):
    tags = {"activity": ["야경", "술"], "mood": ["활기찬"], "setting": ["실외"]}
    res = client.post("/api/admin/places", json={**NEW_PLACE, "tags": tags, "description": "자유 소개 문장"})
    assert res.status_code == 201
    assert res.json()["tags"] == {"activity": ["술", "야경"], "mood": ["활기찬"], "setting": ["실외"]}  # 목록 순서로
    place = next(p for p in load_places() if p.id == "test_lp_bar")
    assert "술" in place.embed_text and "자유 소개 문장" not in place.embed_text  # 매칭은 태그만

    bad = {**NEW_PLACE, "id": "test_bad"}
    assert client.post("/api/admin/places", json={**bad, "tags": {"activity": ["번지점프"]}}).status_code == 422
    assert client.post("/api/admin/places", json={**bad, "tags": {"setting": ["실내", "실외"]}}).status_code == 422
    assert client.post("/api/admin/places", json={**bad, "tags": {"color": ["빨강"]}}).status_code == 422

    no_tags = client.post("/api/admin/places", json={**NEW_PLACE, "id": "test_no_tags"}).json()
    assert no_tags["missing_tags"] == ["할 거리", "분위기", "공간"]
    assert client.get("/api/admin/places/champions_field").json()["missing_tags"] == []  # 목적지는 매칭 안 함
    assert [g["key"] for g in client.get("/api/tags").json()][:2] == ["activity", "mood"]


def test_tags_column_added_to_old_database(tmp_path, monkeypatch):
    """태그 도입 전에 만든 DB 도 서버를 켜면 컬럼이 생기고 예시 태그가 채워진다."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker

    from routefit import db

    old = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    db.Base.metadata.create_all(old)
    with old.begin() as conn:
        conn.execute(text("ALTER TABLE places DROP COLUMN tags"))
        conn.execute(text(
            "INSERT INTO places (id, kind, name, category, area, lat, lng, description, aliases, open_time, close_time,"
            " closed_days, stay_min, cost, gwangju_ness, stay_inducement, commerce_link, is_local_commerce, verified,"
            " updated_at) VALUES ('acc', 'candidate', 'ACC', 'culture', '동구', 35.1, 126.9, '', '[]', '10:00',"
            " '18:00', '[]', 60, 0, 3, 3, 3, 0, 0, '2026-01-01')"
        ))
    monkeypatch.setattr(db, "engine", lambda: old)
    monkeypatch.setattr(db, "_sessionmaker", lambda: sessionmaker(old, expire_on_commit=False))

    db._add_missing_columns()
    assert "tags" in {c["name"] for c in inspect(old).get_columns("places")}
    with db._sessionmaker()() as s:
        assert "전시 관람" in s.get(db.PlaceRow, "acc").tags["activity"]
    db._add_missing_columns()  # 두 번 불러도 괜찮다
