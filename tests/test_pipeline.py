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
    assert wanted_activities("동명동 독립서점이랑 북카페 가고 싶어") == {"책·독서"}
    assert wanted_activities("비 오면 충장로에서 방탈출이나 보드게임 하고 싶어") == {"게임·놀이"}
    assert wanted_activities("야구 게임 보기 전에 카페 가고 싶어") == set()
    assert wanted_activities("카페에서 책 읽으면서 쉬고 싶어") == {"책·독서"}
    assert wanted_activities("공원 산책하고 싶어") == set()  # '산책' 의 '책' 은 책이 아니다
    assert wanted_activities("서점은 말고 전시") == {"전시 관람"}
    assert wanted_activities("서점이랑 전시를 돌고 싶어. 저녁 즘에 돌아갈거야.") == {"책·독서", "전시 관람"}
    for q in ("책 사러 가고 싶어", "책 좋아하는 친구랑", "조용히 독서하고 싶어", "책방 투어", "북카페"):
        assert wanted_activities(q) == {"책·독서"}, q
    for q in ("산책하고 싶어", "책임감 있게 짜 줘", "공책 사러", "책은 별로"):
        assert wanted_activities(q) == set(), q

    from routefit.filters import wanted_activity_counts as counts

    cases = {"서점 많이랑 전시 보고 싶어. 저녁즘에 돌아갈 듯?": {"책·독서": 2, "전시 관람": 1},
             "서점이랑 전시를 돌고 싶어": {"책·독서": 1, "전시 관람": 1}, "여러 서점 돌기": {"책·독서": 2},
             "책방 투어하고 싶어": {"책·독서": 2}, "서점 3곳이랑 미술관": {"책·독서": 3, "전시 관람": 1},
             "전시 두 곳 보고 서점": {"전시 관람": 2, "책·독서": 1}, "서점은 말고 전시 많이": {"전시 관람": 2}}
    for q, want in cases.items():
        assert counts(q) == want, q


def test_named_activity_count_is_kept_in_course():
    """"서점 많이랑 전시" 면 코스에 서점 2곳(책과생활·꽃이피다)과 전시 1곳 이상."""
    for planner in ("greedy", "ortools"):
        c = _plan("서점 많이랑 전시 보고 싶어. 저녁즘에 돌아갈 듯?", planner=planner)
        acts = [set(p.tags.get("activity", [])) for p in (_place(s.place_id) for s in c.stops)]
        assert sum("책·독서" in a for a in acts) >= 2, (planner, [s.name for s in c.stops])
        assert sum("전시 관람" in a for a in acts) >= 1, (planner, [s.name for s in c.stops])
        assert c.constraints.day_end == "19:30"


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
    assert (c.day_start, c.day_end, c.budget) == ("11:00", "21:00", None)
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


def _place(place_id):
    return next(p for p in load_anchors() + load_places() if p.id == place_id)


def test_place_count_is_read_from_sentence():
    from routefit.filters import place_count

    cases = {
        "장소 너무 많아. 3곳만 해줘": (3, 3), "세 군데 정도": (3, 3), "네 곳으로 짜줘": (4, 4), "장소는 5개": (5, 5),
        "4곳 이상 가고 싶어": (4, None), "최소 다섯 곳": (5, None), "최대 3곳": (None, 3), "3곳까지만": (None, 3),
        "3~4곳": (3, 4), "장소 너무 많아": (None, 9), "몇 군데만 천천히": (None, 9),
        # 장소 수가 아닌 말
        "만두 2개 먹고": (None, None), "한 곳에 오래 있고 싶어": (None, None), "돈은 적게 쓰고 싶어": (None, None),
        "조금만 걷고 싶어": (None, None), "오후 2시부터 5만원으로": (None, None),
    }
    for q, want in cases.items():
        assert place_count(q, fewer=9) == want, q


@pytest.mark.parametrize("planner", ["greedy", "ortools"])
def test_place_count_limits_the_course(planner):
    from routefit import config

    query = "맛집이랑 카페, 구경거리"
    assert len(_plan(query, planner=planner).stops) > 3  # 말이 없으면 더 넣는다
    # 말이 없으면 꼭 갈 곳을 포함해 하루 LIMITS.max_places(6)곳까지
    assert len(_plan(query, must_visits=[BASEBALL], planner=planner).stops) <= config.LIMITS.max_places

    few = _plan(query + ". 장소 너무 많아. 3곳만 해줘", planner=planner)
    assert len(few.stops) == 3 and (few.constraints.min_places, few.constraints.max_places) == (3, 3)
    vague = _plan(query + ". 장소 너무 많아", planner=planner)
    assert len(vague.stops) <= config.LIMITS.fewer_places
    # 꼭 갈 곳도 센다: 야구장 + AI 2곳
    with_must = _plan(query + " 3곳만", must_visits=[BASEBALL], planner=planner)
    assert len(with_must.stops) == 3 and sum(s.kind == "ai" for s in with_must.stops) == 2

    # 기본 상한(6곳)보다 많이 달라고 하면 그만큼 넣는다. 하루가 짧아 못 채우면 들어가는 만큼 넣고 알린다
    assert len(_plan("구경거리 많이. 8곳 이상 가고 싶어", planner=planner).stops) >= 8
    short = _plan("구경거리 많이. 8곳 이상 가고 싶어", day_start="15:00", day_end="19:00", planner=planner)
    assert len(short.stops) < 8 and any("곳까지만 넣을 수 있었습니다" in n for n in short.constraints.notes)


@pytest.mark.parametrize("planner", ["greedy", "ortools"])
def test_default_place_cap_follows_day_length(planner):
    # 장소 수를 말하지 않으면 100분에 1곳, 많아야 6곳(꼭 갈 곳 포함). 기본 하루(11~21시)는 6곳, 짧은 하루는 덜 넣는다
    query = "맛집이랑 카페, 구경거리"
    assert len(_plan(query, planner=planner).stops) <= 6
    for start, end, cap in (("10:00", "19:00", 5), ("13:00", "19:00", 3)):
        assert len(_plan(query, day_start=start, day_end=end, planner=planner).stops) <= cap, (start, end)
    # 직접 말하면 그 수를 따른다
    assert len(_plan(query + ". 4곳 정도", day_start="13:00", day_end="19:00", planner=planner).stops) == 4


@pytest.mark.parametrize("planner", ["greedy", "ortools"])
def test_capped_day_is_filled_by_staying_longer(planner):
    # 6곳으로 줄여도 22시까지 놀겠다는 하루를 20시에 끝내지 않는다. 남는 시간만큼 AI 가 고른 곳에 더 머문다
    from routefit.data import load_places

    base = {p.id: p for p in load_places()}
    c = _plan("연인이랑 맛있는 거 먹고 카페랑 구경거리", day_start="10:00", day_end="22:00", planner=planner)
    assert len(c.stops) <= 6 and to_min(c.stops[-1].end) >= to_min("21:00")
    assert to_min(c.stops[-1].end) <= to_min("22:00")
    for s in c.stops:  # 원래의 1.5배를 넘지 않는다(카페·식당은 최소 시간부터)
        floor = {"cafe": 90, "food": 70}.get(s.category, 0)
        assert s.stay_min <= max(base[s.place_id].stay_min, floor) * 1.5 + 10


def test_vague_day_end_is_read_from_sentence():
    from routefit.parser import vague_day_end

    cases = {"저녁까지 놀 거야": "20:00", "저녁 먹고 들어갈 거야": "20:00", "저녁 전까지": "18:00", "오후까지 구경": "18:00",
             "점심까지만": "14:00", "밤까지 놀자": "22:00", "저녁 먹고 카페 가고 싶어": None, "저녁에 맛집": None,
             "저녁즘에 돌아갈 것 같아": "19:30", "저녁쯤 집에 갈 거야": "19:30", "저녁 무렵 들어가야 해": "19:30",
             "저녁쯤까지 놀래": "20:00", "저녁때 맛집 가자": None}
    for q, want in cases.items():
        assert vague_day_end(q) == want, q
    c = _plan("친구랑 맛집이랑 카페. 저녁까지 놀 거야")
    assert c.constraints.day_end == "20:00" and to_min(c.stops[-1].end) <= to_min("20:00") + 30


def test_reasons_do_not_get_walking_times(monkeypatch):
    # 장소마다 "걸어서 ○분" 을 말하지 않게, 이유를 쓰는 AI 에 장소별 이동시간을 넘기지 않는다.
    # 모두 가까운 코스인지(all_walk)만 넘겨 요약에서 한 번 말하게 한다
    import json

    from routefit import explain

    sent = []
    def fake(system, user, schema):  # 조건 파싱도 같은 함수를 부르므로 추천 이유 요청만 잡는다
        if schema is explain.Explanation:
            sent.append(json.loads(user))

    monkeypatch.setattr(explain.llm, "structured", fake)
    _plan("맛집이랑 카페, 구경거리")
    facts = sent[-1]
    assert isinstance(facts["all_walk"], bool)
    assert not any(k.startswith(("travel", "walk")) for s in facts["stops"] for k in s)
    # 그래도 이동 얘기를 쓰면 그 문장만 뺀다
    text = "치즈케이크로 유명한 아늑한 카페입니다. 앞 장소에서 걸어서 3분이라 부담이 없습니다."
    assert explain._drop_movement(text) == "치즈케이크로 유명한 아늑한 카페입니다."


def test_no_transit_is_read_from_sentence():
    from routefit.filters import avoids_transit

    for q in ("대중교통 타기 싫어", "버스는 안 탈래", "지하철 말고", "걸어서 다닐 수 있는 곳으로만", "도보로만 다닐래"):
        assert avoids_transit(q), q
    for q in ("많이 걷기 싫어", "버스 타고 가도 돼", "맛집이랑 카페"):
        assert not avoids_transit(q), q
    assert parse_rule_based("대중교통 타기 싫어. 맛집", []).avoid_keywords == []  # '싫은 것'으로 장소를 거르지 않는다


@pytest.mark.parametrize("planner", ["greedy", "ortools"])
def test_no_transit_course_walks_between_places(planner):
    from routefit.data import travel_mode

    def rides(course):
        nodes = {p.id: p for p in load_places() + load_anchors()}
        stops = [nodes[s.place_id] for s in course.stops]
        return [(a.id, b.id) for a, b in zip(stops, stops[1:]) if travel_mode(a, b) != "walk"]

    query = "대중교통 타기 싫어. 맛집이랑 카페, 구경거리"
    c = _plan(query, planner=planner)
    assert c.constraints.walk_only and len(c.stops) >= 3
    assert rides(c) == []
    assert any("걸어서 닿는 곳끼리" in n for n in c.constraints.notes)

    # 꼭 갈 곳이 멀면(야구장) 그곳을 오가는 구간만 대중교통이 남고, 그렇다고 알린다
    far = _plan(query, must_visits=[BASEBALL], planner=planner)
    assert all("champions_field" in leg for leg in rides(far))
    assert any("대중교통 구간이 남았습니다" in n for n in far.constraints.notes) == bool(rides(far))


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
def test_times_are_in_5_and_10_minute_steps(planner):
    # 시작은 5분 단위, 나가는 시각은 10분 단위라 머무는 시간이 5분 단위로 보인다. 다음 장소는 나간 시각 + 이동시간에 도착한다
    from routefit.config import LIMITS

    c = _plan("연인이랑 조용하고 아늑한 데이트, 맛있는 거 먹고 디저트 카페도 가고 싶어", planner=planner)
    assert c.stops and all(to_min(s.end) % 10 == 0 for s in c.stops)
    assert all((to_min(s.end) - to_min(s.start)) % 5 == 0 for s in c.stops)
    opens = {p.id: p.open for p in load_places()}
    for prev, s in zip(c.stops, c.stops[1:]):
        assert to_min(s.arrive) == to_min(prev.end) + s.travel_min
        assert to_min(s.end) - to_min(s.start) - s.stay_min in range(10)
        # 5분 단위로 맞추느라 몇 분(5분 미만) 기다리는 것 말고는, 식사 시간대 시작(17:00)이나 영업 시작만 기다린다
        if to_min(s.start) - to_min(s.arrive) >= LIMITS.start_step:
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
