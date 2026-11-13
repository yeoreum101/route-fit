"""결과에서 '다른 곳으로 바꾸기': 같은 역할의 후보를 보여 주고, 고른 곳으로 바꿔 다시 짠다."""
from fastapi.testclient import TestClient

from routefit.api import app
from routefit.models import to_min
from routefit.planner.core import meal_slot

client = TestClient(app)
QUERY = "연인이랑 조용하고 아늑한 데이트, 맛있는 거 먹고 디저트 카페도 가고 싶어. 토요일"


def _plan(**body):
    res = client.post("/api/plan", json={"query": QUERY, **body})
    assert res.status_code == 200, res.text
    return res.json()


def _alts(course, order):
    res = client.get(f"/api/courses/{course['id']}/alternatives", params={"order": order})
    assert res.status_code == 200, res.text
    return res.json()


def test_alternatives_have_same_role_and_are_not_in_course():
    course = _plan()
    in_course = {s["place_id"] for s in course["stops"]}
    found = 0
    for stop in (s for s in course["stops"] if s["kind"] == "ai"):
        alts = _alts(course, stop["order"])
        assert len(alts) <= 3  # 그 자리에 시간이 맞는 곳이 없으면 비어 있을 수 있다
        found += bool(alts)
        for a in alts:
            assert a["category"] == stop["category"] and a["place_id"] not in in_course
        if stop["order"] > 1:
            assert all(a["travel_from_prev"] is not None for a in alts)
    assert found  # 적어도 한 곳은 바꿀 후보가 있다


def test_swap_keeps_other_places_and_puts_chosen_one_in():
    course = _plan(exclude_ids=["s_001"])
    food = next(s for s in course["stops"] if s["kind"] == "ai" and s["category"] == "food")
    chosen = _alts(course, food["order"])[0]
    res = client.post(f"/api/courses/{course['id']}/swap", json={"order": food["order"], "place_id": chosen["place_id"]})
    assert res.status_code == 200, res.text
    new = res.json()
    want = [chosen["place_id"] if s["order"] == food["order"] else s["place_id"] for s in course["stops"]]
    assert [s["place_id"] for s in new["stops"]] == want  # 바꾼 자리만 갈아끼우고 순서는 그대로
    swapped = next(s for s in new["stops"] if s["place_id"] == chosen["place_id"])
    assert swapped["kind"] == "ai" and swapped["reason"]  # 꼭 갈 곳이 아니라 AI 추천으로 보이고 추천 이유가 있다
    assert meal_slot(to_min(swapped["start"])) is not None  # 식당은 식사 시간대에
    assert new["id"] != course["id"] and food["name"] in new["constraints"]["notes"][0]
    saved = client.get(f"/api/courses/{new['id']}").json()["request"]
    assert set(saved["exclude_ids"]) == {"s_001", food["place_id"]}  # 원래 뺀 곳 + 바꾼 곳


def test_swap_keeps_must_read_from_sentence(monkeypatch):
    """문장에서 읽은 꼭 갈 곳은, 바꾸기로 다시 짤 때 문장을 다르게 읽어도(LLM) 코스에 남는다."""
    from routefit import pipeline

    res = client.post("/api/plan", json={"query": "챔필에서 야구 보기 전에 맛있는 거 먹고 카페 가고 싶어"})
    assert res.status_code == 200, res.text
    course = res.json()
    assert any(s["place_id"] == "champions_field" and s["kind"] == "must" for s in course["stops"])
    stop, chosen = next((s, a) for s in course["stops"] if s["kind"] == "ai" for a in _alts(course, s["order"])[:1])

    real = pipeline.parse_query
    def forgetful(query, known):  # 이번에는 꼭 갈 곳을 못 읽었다고 치자
        parsed, used = real(query, known)
        return parsed.model_copy(update={"must_visits": []}), used
    monkeypatch.setattr(pipeline, "parse_query", forgetful)

    res = client.post(f"/api/courses/{course['id']}/swap", json={"order": stop["order"], "place_id": chosen["place_id"]})
    assert res.status_code == 200, res.text
    new = res.json()
    assert any(s["place_id"] == "champions_field" and s["kind"] == "must" for s in new["stops"])
    assert chosen["place_id"] in {s["place_id"] for s in new["stops"]}


def test_swap_rejects_must_and_unknown():
    course = _plan()
    cid = course["id"]
    assert client.get(f"/api/courses/{cid}/alternatives", params={"order": 99}).status_code == 422
    assert client.get("/api/courses/nope/alternatives", params={"order": 1}).status_code == 404
    first_ai = next(s for s in course["stops"] if s["kind"] == "ai")
    already = next(s for s in course["stops"] if s["kind"] == "ai" and s["order"] != first_ai["order"])
    res = client.post(f"/api/courses/{cid}/swap", json={"order": first_ai["order"], "place_id": already["place_id"]})
    assert res.status_code == 422 and "이미" in res.json()["detail"]
    assert client.post(f"/api/courses/{cid}/swap", json={"order": first_ai["order"], "place_id": "nope"}).status_code == 422

    with_must = client.post("/api/plan", json={"query": QUERY, "must_visits": [{"id": "s_001"}]}).json()
    must = next(s for s in with_must["stops"] if s["kind"] == "must")
    res = client.get(f"/api/courses/{with_must['id']}/alternatives", params={"order": must["order"]})
    assert res.status_code == 422 and "AI" in res.json()["detail"]
