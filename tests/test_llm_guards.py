"""LLM 이 틀리거나 지어낸 값을 돌려줘도 코스가 깨지지 않는지 본다. 가짜 LLM 을 끼워 넣으므로 키가 필요 없다."""
from routefit import explain as explain_mod
from routefit import llm, parser
from routefit.data import load_anchors, load_places
from routefit.explain import Explanation, StopReason, _grounded
from routefit.models import ParsedMustVisit, ParsedQuery, PlanRequest
from routefit.pipeline import make_course


def _fake_llm(monkeypatch, answers: dict):
    """schema 클래스 -> 돌려줄 객체(또는 호출해서 만드는 함수)."""

    def structured(system, user, schema):
        a = answers.get(schema)
        return a(user) if callable(a) else a

    monkeypatch.setattr(llm, "structured", structured)
    monkeypatch.setattr(llm, "name", lambda: "fake:model")


def _parsed(**kw) -> ParsedQuery:
    base = dict(
        taste="조용한 산책",
        day_start=None,
        day_end=None,
        budget=None,
        companions=None,
        weekday=None,
        must_visits=[],
        avoid_categories=[],
    )
    return ParsedQuery(**{**base, **kw})


def test_sanitize_drops_bad_values():
    known = load_anchors() + load_places()
    bad = _parsed(
        day_start="9시",  # HH:MM 이 아님
        day_end="25:61",
        budget=-5,
        weekday=9,
        companions="직장 동료",
        avoid_categories=["food", "food", "venue", "spaceship"],
        must_visits=[
            ParsedMustVisit(name="챔피언스 필드", start="오후 6시반", stay_min=-30),
            ParsedMustVisit(name="존재하지않는곳", start="10:00", stay_min=None),
        ],
    )
    out = parser.sanitize(bad, known)
    assert (out.day_start, out.day_end, out.budget, out.weekday, out.companions) == (None,) * 5
    assert out.avoid_categories == ["food"]
    assert [m.name for m in out.must_visits] == ["광주-기아 챔피언스 필드"]
    assert (out.must_visits[0].start, out.must_visits[0].stay_min) == (None, None)


def test_sanitize_keeps_good_values():
    known = load_anchors() + load_places()
    good = _parsed(
        day_start="14:00",
        day_end="21:00",
        budget=50000,
        weekday=6,
        companions="커플",
        must_visits=[ParsedMustVisit(name="챔피언스 필드", start="18:30", stay_min=150)],
    )
    out = parser.sanitize(good, known)
    assert (out.day_start, out.day_end, out.budget, out.weekday, out.companions) == ("14:00", "21:00", 50000, 6, "연인")
    assert (out.must_visits[0].start, out.must_visits[0].stay_min) == ("18:30", 150)


def test_unknown_must_visit_from_llm_does_not_break_course(monkeypatch):
    # LLM 이 없는 장소를 필수 방문지로 지어내도 오류 없이 코스가 만들어진다
    _fake_llm(monkeypatch, {ParsedQuery: _parsed(must_visits=[ParsedMustVisit(name="우주정거장", start=None, stay_min=None)])})
    course = make_course(PlanRequest(query="조용한 산책"))
    assert course.engine["parser"] == "fake:model"
    assert all(s.kind == "ai" for s in course.stops)


def test_hallucinated_reason_falls_back_to_template(monkeypatch):
    def explanation(user):
        import json

        ids = [s["place_id"] for s in json.loads(user)["stops"] if s["kind"] == "ai"]
        reasons = [StopReason(place_id=i, reason="시그니처 메뉴는 8,000원이고 걸어서 77분 걸려요.") for i in ids[:-1]]
        reasons.append(StopReason(place_id=ids[-1], reason="분위기가 취향과 잘 맞는 곳입니다."))
        reasons.append(StopReason(place_id="없는장소", reason="무시되어야 함"))
        return Explanation(summary="하루 코스입니다. 평균 12,000원이면 충분해요.", reasons=reasons)

    _fake_llm(monkeypatch, {ParsedQuery: None, Explanation: explanation})
    course = make_course(PlanRequest(query="조용한 산책"))
    ai = [s for s in course.stops if s.kind == "ai"]
    assert len(ai) >= 2
    assert course.engine["explainer"] == "fake:model"
    assert all(s.reason for s in ai)  # 빠지거나 버려진 이유도 모두 채워진다
    assert all("8,000원" not in s.reason and "77분" not in s.reason for s in ai)
    assert "취향 유사도" in ai[0].reason  # 템플릿으로 대체됨
    assert ai[-1].reason == "분위기가 취향과 잘 맞는 곳입니다."  # 근거 있는 문장은 그대로
    assert "12,000원" not in course.summary
    assert all(s.place_id != "없는장소" for s in course.stops)


def test_grounded_rules():
    assert _grounded("예산 10만원 안에서 걸어서 8분", 100000, {8})
    assert _grounded("조용한 분위기가 취향과 맞습니다", None, set())
    assert not _grounded("커피 5,000원", 100000, set())
    assert not _grounded("5천원이면 돼요", None, set())
    assert not _grounded("3만원이면 돼요", None, set())
    assert not _grounded("이동 15분", 100000, {8})
    assert explain_mod._grounded("예산 100,000원", 100000, set())


def test_grounded_allows_stay_minutes_and_clock_times():
    # 머무는 시간(40분·80분)과 시각('5시 35분', '17:35')은 지어낸 숫자가 아니다
    allowed = {5, 40, 80, 20}
    assert _grounded("오후 2시 첫 방문지로 40분간 둘러본 뒤, 5분 이동합니다.", None, allowed)
    assert _grounded("오후 5시 35분부터 80분간 머문 뒤 이동합니다.", None, allowed)
    assert _grounded("17:35에 도착해 80분 머뭅니다.", None, allowed)
    assert _grounded("1시간 20분 머뭅니다.", None, allowed)
    # 입력에 없는 시간은 여전히 막는다
    assert not _grounded("커피 한 잔에 45분은 걸려요.", None, allowed)
    assert not _grounded("5시 35분부터 90분간 머뭅니다.", None, allowed)
