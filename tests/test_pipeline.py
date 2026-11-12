import pytest
from fastapi.testclient import TestClient

from routefit.api import app
from routefit.data import load_anchors, load_places
from routefit.models import MustVisitInput, PlanRequest, to_min
from routefit.parser import parse_rule_based
from routefit.pipeline import make_course
from routefit.planner import PlanError
from routefit.planner.core import meal_slot

QUERY = "토요일 야구 보기 전에 사진 찍기 좋은 데랑 로컬 맛집 가고 싶어. 예산 10만원"
BASEBALL = MustVisitInput(id="champions_field", start="18:30")


@pytest.mark.parametrize("planner", ["greedy", "ortools"])
def test_must_visit_is_kept_and_course_is_executable(planner):
    course = make_course(PlanRequest(query=QUERY, must_visits=[BASEBALL], planner=planner))

    must = [s for s in course.stops if s.kind == "must"]
    assert [s.place_id for s in must] == ["champions_field"]
    assert must[0].start == "18:30"
    assert course.metrics.n_ai_places >= 2

    places = {p.id: p for p in load_places()}
    for prev, cur in zip(course.stops, course.stops[1:]):
        assert to_min(prev.end) + cur.travel_min <= to_min(cur.start)
    for s in course.stops:
        if s.kind == "ai":
            p = places[s.place_id]
            assert to_min(p.open) <= to_min(s.start)
            assert to_min(s.end) <= to_min(p.close)
            if p.break_start:
                assert to_min(s.end) <= to_min(p.break_start) or to_min(p.break_end) <= to_min(s.start)
    for prev, cur in zip(course.stops, course.stops[1:]):
        assert not prev.category == cur.category == "cafe"  # 카페 연달아 금지
    assert all(s.stay_min >= 90 for s in course.stops if s.category == "cafe")
    assert all(s.stay_min >= 70 for s in course.stops if s.category == "food")
    meals = [s for s in course.stops if s.kind == "ai" and s.category == "food"]
    slots = [meal_slot(to_min(s.start)) for s in meals]
    assert None not in slots and len(set(slots)) == len(slots)  # 식사 시간대 안, 한 끼에 한 곳
    assert course.metrics.total_cost <= 100000


def test_must_visit_parsed_from_sentence_when_not_selected():
    course = make_course(PlanRequest(query=QUERY))
    assert "champions_field" in [s.place_id for s in course.stops if s.kind == "must"]


def test_closed_day_is_excluded():
    course = make_course(PlanRequest(query="월요일에 전시랑 미술관 보고 싶어"))
    assert "acc" not in [s.place_id for s in course.stops]


def test_conflicting_fixed_times_raise():
    req = PlanRequest(
        query="야구랑 공연",
        must_visits=[BASEBALL, MustVisitInput(id="arts_center", start="19:00")],
    )
    with pytest.raises(PlanError, match="시간이 겹칩니다") as e:
        make_course(req)
    assert "광주-기아 챔피언스 필드" in str(e.value)


def test_fixed_times_need_travel_gap():
    # 야구가 18:30~19:00 로 끝나도, 이동시간이 있으니 19:00 에 바로 시작하는 공연은 갈 수 없다.
    req = PlanRequest(
        query="야구랑 공연",
        must_visits=[
            MustVisitInput(id="champions_field", start="18:30", stay_min=30),
            MustVisitInput(id="arts_center", start="19:00"),
        ],
    )
    with pytest.raises(PlanError, match="이동"):
        make_course(req)


def test_companions_are_read_as_tag_values():
    from routefit.parser import normalize_companions

    places = load_anchors() + load_places()
    assert parse_rule_based("아이랑 주말에 산책", places).companions == "아이 동반"
    assert parse_rule_based("데이트 코스 추천", places).companions == "연인"
    assert parse_rule_based("아이스크림 먹고 싶어", places).companions is None
    # LLM 이 자유롭게 쓴 값도 태그 값으로 맞춘다
    assert normalize_companions("친구 2명") == "친구"
    assert normalize_companions("커플") == "연인"
    assert normalize_companions("직장 동료") is None


def test_companion_tag_raises_place_value():
    from routefit.models import Constraints
    from routefit.pipeline import _candidate_nodes

    places = load_places()
    sims = {p.id: 0.5 for p in places}
    base = dict(taste="", day_start="10:00", day_end="22:00", budget=None, weekday=None, avoid_categories=[])
    alone = {n.id: n for n in _candidate_nodes(Constraints(**base, companions=None), sims, set(), set())}
    couple = {n.id: n for n in _candidate_nodes(Constraints(**base, companions="연인"), sims, set(), set())}
    for p in places:
        fits = "연인" in p.tags.get("companions", [])
        assert couple[p.id].companion_fit == fits
        assert (couple[p.id].value > alone[p.id].value) == fits


def test_named_activity_is_read_from_sentence():
    from routefit.filters import wanted_activities

    assert wanted_activities("샌드위치 먹고 싶어. 그리고 적당히 전시 좀 보고") == {"전시 관람"}
    assert wanted_activities("전시는 말고 영화 볼래") == {"공연·영화"}
    assert wanted_activities("미술관이랑 야경") == {"전시 관람", "야경"}
    assert wanted_activities("맛있는 거 먹고 쉬고 싶어") == set()


def test_named_activity_tag_raises_place_value():
    # '전시'를 말하면 '전시 관람' 태그가 있는 곳만 점수가 오른다. 광주극장(공연·영화)은 오르지 않는다
    from routefit.models import Constraints
    from routefit.pipeline import _candidate_nodes

    places = load_places()
    sims = {p.id: 0.5 for p in places}
    c = Constraints(taste="", day_start="10:00", day_end="22:00", budget=None, weekday=None, avoid_categories=[], companions=None)
    plain = {n.id: n for n in _candidate_nodes(c, sims, set(), set())}
    exhibit = {n.id: n for n in _candidate_nodes(c, sims, set(), {"전시 관람"})}
    for p in places:
        fits = "전시 관람" in p.tags.get("activity", [])
        assert exhibit[p.id].activity_fit == fits
        assert (exhibit[p.id].value > plain[p.id].value) == fits
    assert exhibit["acc"].activity_fit and not exhibit["gwangju_theater"].activity_fit


def test_rule_based_parser():
    parsed = parse_rule_based("일요일 오후 2시부터 밤 9시까지 친구랑 5만원으로 챔필", load_anchors())
    assert (parsed.day_start, parsed.day_end) == ("14:00", "21:00")
    assert parsed.budget == 50000
    assert parsed.weekday == 6
    assert parsed.companions == "친구"
    assert [m.name for m in parsed.must_visits] == ["광주-기아 챔피언스 필드"]


def test_api():
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"]
    res = client.post("/api/plan", json={"query": QUERY, "must_visits": [{"id": "champions_field", "start": "18:30"}]})
    assert res.status_code == 200
    assert res.json()["stops"]
    assert client.post("/api/plan", json={"query": "x", "must_visits": [{"name": "없는장소"}]}).status_code == 422


def test_sentence_used_when_screen_is_empty():
    course = make_course(PlanRequest(query="일요일 오후 2시부터 밤 9시까지 친구랑 5만원으로 챔필 근처"))
    c = course.constraints
    assert (c.day_start, c.day_end, c.budget) == ("14:00", "21:00", 50000)
    assert c.sources == {"must_visits": "문장", "day_start": "문장", "day_end": "문장", "budget": "문장", "weekday": "문장"}
    assert c.must_visits == ["광주-기아 챔피언스 필드"]
    assert c.notes == []


def test_screen_overrides_sentence_with_notes():
    course = make_course(
        PlanRequest(
            query="오후 2시부터 밤 9시까지 5만원으로 예술의전당 공연",
            must_visits=[BASEBALL],
            day_start="12:00",
            budget=80000,
        )
    )
    c = course.constraints
    assert (c.day_start, c.budget) == ("12:00", 80000)
    assert c.sources["day_start"] == "화면" and c.sources["budget"] == "화면" and c.sources["must_visits"] == "화면"
    assert c.sources["day_end"] == "고정 일정"  # 문장의 21:00 보다 경기 종료가 늦다
    assert any("광주예술의전당" in n for n in c.notes)
    assert any("14:00" in n and "12:00" in n for n in c.notes)
    assert any("50,000원" in n for n in c.notes)
    assert any("하루 종료를 늘렸습니다" in n for n in c.notes)


def test_defaults_when_nothing_given():
    c = make_course(PlanRequest(query="조용한 산책")).constraints
    assert (c.day_start, c.day_end, c.budget) == ("10:00", "22:00", None)
    assert c.sources == {"day_start": "기본값", "day_end": "기본값"}
    assert c.weekday is None and any("요일을 몰라" in n for n in c.notes)


def test_visit_date_decides_closed_days():
    from datetime import date

    monday = date(2026, 10, 19)
    course = make_course(PlanRequest(query="토요일에 전시랑 미술관 보고 싶어", visit_date=monday))
    c = course.constraints
    assert (c.weekday, c.sources["weekday"]) == (0, "화면")
    assert "acc" not in [s.place_id for s in course.stops]  # 월요일 휴관
    assert any("토요일 대신" in n for n in c.notes)


def test_closed_must_visit_is_warned():
    from datetime import date

    course = make_course(
        PlanRequest(query="전시", must_visits=[MustVisitInput(id="acc")], visit_date=date(2026, 10, 19))
    )
    assert any("월요일 휴무" in n for n in course.constraints.notes)


def test_kakao_categories():
    from routefit.place_search import kakao_category

    assert kakao_category("AD5", "여행 > 숙박 > 호텔") == "lodging"
    assert kakao_category("CE7", "음식점 > 카페") == "cafe"
    assert kakao_category("FD6", "음식점 > 한식") == "food"
    assert kakao_category("", "교통,수송 > 기차,철도 > 기차역") == "etc"
    assert kakao_category("", "가정,생활 > 시장 > 전통시장") == "market"


def test_place_search_lists_known_places_first(monkeypatch):
    from routefit import config

    monkeypatch.setattr(config, "KAKAO_REST_API_KEY", "")  # 키가 없으면 카카오 결과 없이 등록된 장소만
    out = TestClient(app).get("/api/place-search", params={"q": "챔피언스"}).json()
    assert [p["id"] for p in out["known"]] == ["champions_field"] and out["kakao"] == []


def test_searched_kakao_places_can_be_must_visits(monkeypatch):
    # 등록되지 않은 숙소·식당도 화면이 보낸 좌표·업종으로 코스에 넣는다. 고른 식당은 그 끼니를 채운다.
    from routefit import config

    monkeypatch.setattr(config, "TMAP_APP_KEY", "")
    hotel = {"id": "kakao_1", "name": "테스트호텔", "category": "lodging", "area": "동구 동명로", "lat": 35.1495, "lng": 126.9240, "start": "10:00"}
    lunch = {"id": "kakao_2", "name": "테스트식당", "category": "food", "area": "동구 동명로", "lat": 35.1500, "lng": 126.9250, "start": "12:00"}
    res = TestClient(app).post("/api/plan", json={"query": "조용한 산책", "must_visits": [hotel, lunch]})
    assert res.status_code == 200, res.text
    stops = res.json()["stops"]
    by_id = {s["place_id"]: s for s in stops}
    assert by_id["kakao_1"]["category"] == "lodging" and by_id["kakao_1"]["kind"] == "must"
    assert by_id["kakao_2"]["start"] == "12:00"
    lunch_foods = [s for s in stops if s["category"] == "food" and to_min(s["start"]) <= to_min("13:30")]
    assert [s["place_id"] for s in lunch_foods] == ["kakao_2"]  # 점심은 고른 식당으로 이미 찼다


def _plan(query, **kw):
    return make_course(PlanRequest(query=query, **kw))


def test_disliked_word_and_excluded_places_are_not_recommended():
    # "오리탕 싫어" -> 오리탕 거리를 빼고, 화면에서 뺀 장소도 빼고, 인식된 조건에 남긴다
    c = _plan("오리탕 싫어. 맛집이랑 시장 구경", exclude_ids=["daein_market"])
    ids = [s.place_id for s in c.stops]
    assert "oritang_street" not in ids and "daein_market" not in ids
    assert c.constraints.avoid_keywords == ["오리탕"] and c.constraints.excluded_places == ["대인예술시장"]


def test_date_course_skips_memorials_unless_history_is_wanted():
    from routefit.data import load_places
    from routefit.filters import is_memorial

    memorial = {p.id for p in load_places() if is_memorial(p)}
    assert {"plaza_518", "jeonil245"} <= memorial
    c = _plan("연인이랑 조용한 데이트, 광장이나 산책하기 좋은 곳")
    assert not memorial & {s.place_id for s in c.stops}
    assert any("추모 공간" in n for n in c.constraints.notes)
    wanted = _plan("연인이랑 5·18 역사 탐방 데이트")
    assert not any("추모 공간" in n for n in wanted.constraints.notes)


def test_searched_cinema_gets_long_stay_and_no_second_cinema():
    cinema = {"id": "kakao_9", "name": "롯데시네마 광주", "category": "culture", "area": "동구", "lat": 35.1478, "lng": 126.9190,
              "description": "문화,예술 > 영화,영상 > 영화관"}
    c = _plan("영화 보고 산책하고 싶어", must_visits=[cinema])
    stops = {s.place_id: s for s in c.stops}
    assert stops["kakao_9"].stay_min == 150  # 영화관을 1시간으로 잡지 않는다
    assert "gwangju_theater" not in stops  # 영화를 두 번 보는 코스가 되지 않게
    assert any("영화관" in n for n in c.constraints.notes)


@pytest.mark.parametrize("planner", ["greedy", "ortools"])
def test_leave_times_are_in_10_minute_steps(planner):
    # 도착(시작)은 실제 시각, 나가는 시각만 10분 단위. 다음 장소는 나간 시각 + 이동시간에 시작한다
    c = _plan("연인이랑 조용하고 아늑한 데이트, 맛있는 거 먹고 디저트 카페도 가고 싶어", planner=planner)
    assert c.stops and all(to_min(s.end) % 10 == 0 for s in c.stops)
    for prev, s in zip(c.stops, c.stops[1:]):
        assert to_min(s.arrive) == to_min(prev.end) + s.travel_min
        assert to_min(s.end) - to_min(s.start) - s.stay_min in range(10)
        # 몇 분 일찍 왔다고 기다리게 하지 않는다. 식사 시간대 시작(17:00)이나 영업 시작을 기다리는 것만 된다
        if 0 < to_min(s.start) - to_min(s.arrive) < 10:
            opens = {p.id: p.open for p in load_places()}
            assert s.start in ("11:00", "17:00") or s.start == opens.get(s.place_id)


STATION = {"id": "kakao_7", "name": "광주역", "category": "etc", "area": "북구 무등로", "lat": 35.1653, "lng": 126.9093,
           "description": "교통,수송 > 기차,철도 > 기차역"}


@pytest.mark.parametrize("planner", ["greedy", "ortools"])
def test_course_starts_from_the_start_place(planner):
    c = _plan("연인이랑 조용하고 아늑한 데이트, 맛있는 거 먹고 디저트 카페도 가고 싶어", start=STATION, planner=planner)
    first, second = c.stops[0], c.stops[1]
    assert (first.kind, first.place_id, first.start, first.end) == ("start", "kakao_7", first.end, first.end)
    assert all(s.kind != "start" for s in c.stops[1:])
    assert second.travel_min > 0 and to_min(second.arrive) == to_min(first.end) + second.travel_min
    assert to_min(first.end) % 10 == 0  # 나서는 시각도 10분 단위
    assert c.metrics.n_places == len(c.stops) - 1  # 출발 위치는 방문 장소로 세지 않는다
    assert c.constraints.start_place == "광주역"


def test_registered_start_place_is_not_recommended_again():
    c = _plan("야구 보기 전에 사진 찍기 좋은 곳", start={"id": "acc"})
    assert [s.place_id for s in c.stops].count("acc") == 1 and c.stops[0].kind == "start"


def test_unreachable_fixed_time_from_start_place_is_reported():
    far = {**STATION, "id": "kakao_8", "lat": 35.30, "lng": 126.70}  # 광주 밖으로 한참
    with pytest.raises(PlanError, match="겹칩니다"):
        _plan("산책", start=far, day_start="10:00", must_visits=[{"id": "acc", "start": "10:10"}])
