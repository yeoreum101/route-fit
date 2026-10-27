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
    alone = {n.id: n for n in _candidate_nodes(Constraints(**base, companions=None), sims, set())}
    couple = {n.id: n for n in _candidate_nodes(Constraints(**base, companions="연인"), sims, set())}
    for p in places:
        fits = "연인" in p.tags.get("companions", [])
        assert couple[p.id].companion_fit == fits
        assert (couple[p.id].value > alone[p.id].value) == fits


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
