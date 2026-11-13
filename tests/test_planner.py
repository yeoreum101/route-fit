import pytest

from routefit.models import Place, to_min
from routefit.planner import Node, plan_greedy, plan_ortools, schedule, start_windows
from routefit.planner.core import meal_slot
from routefit.xlsx_import import _break

LUNCH = (to_min("11:00"), to_min("13:30"))
DINNER = (to_min("17:00"), to_min("19:30"))


def place(id, category="food", open="10:00", close="22:00", **kw) -> Place:
    return Place(id=id, name=id, category=category, area="동구 동명동", lat=35.15, lng=126.92, open=open, close=close, **kw)


def node(p: Place, stay=60, taste=1.0, **kw) -> Node:
    meal = kw.pop("meal", p.category == "food")
    return Node(place=p, windows=start_windows(p, stay, meal=meal), stay=stay, cost=0, meal=meal, taste=taste, **kw)


def no_travel(a, b):
    return 0


def test_break_time_splits_opening_hours():
    p = place("a", category="cafe", open="11:00", close="21:00", break_start="15:00", break_end="17:00")
    assert start_windows(p, 60) == [(to_min("11:00"), to_min("14:00")), (to_min("17:00"), to_min("20:00"))]


def test_meal_windows_keep_only_lunch_and_dinner():
    p = place("a", open="10:30", close="21:00")
    assert start_windows(p, 60, meal=True) == [LUNCH, DINNER]
    late = place("b", open="18:00", close="26:00")
    assert start_windows(late, 60, meal=True) == [(to_min("18:00"), DINNER[1])]


def test_visit_waits_out_the_break():
    cafe = node(place("cafe", category="cafe", open="10:00", close="21:00", break_start="15:00", break_end="17:00"))
    visits = schedule([cafe], to_min("14:30"), to_min("22:00"), no_travel)
    assert visits[0].start == to_min("17:00")  # 14:30 에 들어가면 15:00 브레이크에 걸린다


def test_back_shift_does_not_cross_the_break():
    # 카페는 14:00 에 들어가 15:00 에 나와야 한다. 다음 일정이 18:00 이어도 브레이크 넘어로 당기지 않는다.
    cafe = node(place("cafe", category="cafe", open="10:00", close="21:00", break_start="15:00", break_end="17:00"))
    show = node(place("show", category="culture"), fixed_start=to_min("18:00"), mandatory=True, meal=False)
    visits = schedule([cafe, show], to_min("14:00"), to_min("22:00"), no_travel)
    assert (visits[0].start, visits[0].end) == (to_min("14:00"), to_min("15:00"))


def test_one_restaurant_per_meal():
    a, b = node(place("a")), node(place("b"))
    visits = schedule([a, b], to_min("12:00"), to_min("22:00"), no_travel)
    assert LUNCH[0] <= visits[0].start <= LUNCH[1]
    assert visits[1].start == DINNER[0]  # 점심에 이미 식당이 있으니 저녁까지 기다린다
    assert schedule([a, b, node(place("c"))], to_min("12:00"), to_min("22:00"), no_travel) is None


def test_user_chosen_restaurant_ignores_meal_windows():
    p = place("a")
    must = Node(place=p, windows=start_windows(p, 60), stay=60, cost=0, mandatory=True)
    assert schedule([must], to_min("15:00"), to_min("22:00"), no_travel)[0].start == to_min("15:00")


# 끼니 점수(WEIGHTS.meal) 덕분에 그리디도 오후보다 끼니를 먼저 채워 두 끼 모두 식당이 들어간다
@pytest.mark.parametrize("planner, n_meals", [(plan_greedy, {2}), (plan_ortools, {2})])
def test_planners_respect_meals_and_breaks(planner, n_meals):
    foods = [node(place(f"f{i}", break_start="15:00", break_end="17:00")) for i in range(4)]
    # 식당을 더 원하는 취향이라 두 끼 모두 식당이 들어가야 한다
    cafes = [node(place(f"c{i}", category="cafe", break_start="15:00", break_end="17:00"), taste=0.6) for i in range(2)]
    sights = [node(place(f"s{i}", category="sight"), taste=0.6) for i in range(3)]
    route = planner([], foods + cafes + sights, to_min("10:00"), to_min("22:00"), None, no_travel)
    visits = schedule(route, to_min("10:00"), to_min("22:30"), no_travel)
    assert visits is not None
    meals = [v for v in visits if v.node.meal]
    assert len(meals) in n_meals
    slots = [meal_slot(v.start) for v in meals]
    assert None not in slots and len(set(slots)) == len(slots)
    for v in visits:
        assert not (v.start < to_min("17:00") and v.end > to_min("15:00")) or v.node.place.break_start is None


@pytest.mark.parametrize(
    "value, want",
    [
        ("15:00-17:00", ("15:00", "17:00")),
        ("15:30 ~ 17:00", ("15:30", "17:00")),
        ("15:00-17:00 (평일). 주말·공휴일은 브레이크타임 없음", ("15:00", "17:00")),
        ("없음", (None, None)),
        (None, (None, None)),
    ],
)
def test_break_cell(value, want):
    assert _break(value) == want


def test_break_cell_rejects_garbage():
    with pytest.raises(ValueError, match="브레이크타임"):
        _break("점심 끝나고")


def test_break_must_be_inside_opening_hours():
    with pytest.raises(ValueError, match="브레이크 타임"):
        place("a", open="11:00", close="21:00", break_start="10:00", break_end="12:00")
    with pytest.raises(ValueError, match="함께"):
        place("a", break_start="15:00")


def test_back_to_back_cafes_are_rejected():
    a, b = node(place("a", category="cafe")), node(place("b", category="cafe"))
    walk = node(place("walk", category="sight"))
    assert schedule([a, b], to_min("10:00"), to_min("22:00"), no_travel) is None
    assert schedule([a, walk, b], to_min("10:00"), to_min("22:00"), no_travel) is not None


@pytest.mark.parametrize("planner", [plan_greedy, plan_ortools])
def test_planners_never_put_cafes_back_to_back(planner):
    # 카페만 원하는 취향이어도 카페 사이에 다른 곳이 끼어야 한다
    cafes = [node(place(f"c{i}", category="cafe"), stay=90) for i in range(4)]
    others = [node(place(f"s{i}", category="sight"), taste=0.5) for i in range(3)]
    route = planner([], cafes + others, to_min("10:00"), to_min("22:00"), None, no_travel)
    assert schedule(route, to_min("10:00"), to_min("22:30"), no_travel) is not None
    assert not any(a.place.category == b.place.category == "cafe" for a, b in zip(route, route[1:]))


GAP = 180  # config.LIMITS.min_meal_gap


def test_next_restaurant_waits_for_meal_gap():
    lunch, dinner = node(place("a")), node(place("b"))
    visits = schedule([lunch, dinner], to_min("13:30"), to_min("22:00"), no_travel)
    assert visits[1].start - visits[0].end >= GAP  # 14:30 에 점심이 끝나면 저녁은 17:30 부터
    assert visits[1].start == to_min("17:30")


def test_back_shift_keeps_meal_gap():
    # 점심을 저녁 쪽으로 당기더라도 식사 간격 아래로는 당기지 않는다
    lunch, dinner = node(place("a")), node(place("b"))
    visits = schedule([lunch, dinner], to_min("11:00"), to_min("22:00"), no_travel)
    assert visits[1].start - visits[0].end >= GAP


def test_user_chosen_restaurants_skip_meal_gap():
    a, b = place("a"), place("b")
    musts = [Node(place=p, windows=start_windows(p, 60), stay=60, cost=0, mandatory=True) for p in (a, b)]
    visits = schedule(musts, to_min("12:00"), to_min("22:00"), no_travel)
    assert visits[1].start == to_min("13:00")


@pytest.mark.parametrize("planner", [plan_greedy, plan_ortools])
def test_planners_keep_meal_gap(planner):
    foods = [node(place(f"f{i}")) for i in range(4)]
    cafes = [node(place(f"c{i}", category="cafe"), stay=90, taste=0.8) for i in range(2)]
    route = planner([], foods + cafes, to_min("12:00"), to_min("22:00"), None, no_travel)
    visits = schedule(route, to_min("12:00"), to_min("22:30"), no_travel)
    assert visits is not None  # 식사 간격을 어기는 순서면 시간표가 나오지 않는다
    meals = [v for v in visits if v.node.place.category == "food"]
    assert all(b.start - a.end >= GAP for a, b in zip(meals, meals[1:]))


@pytest.mark.parametrize("planner", [plan_greedy, plan_ortools])
def test_lunch_and_dinner_get_a_restaurant_even_if_taste_prefers_sights(planner):
    # "자연을 즐기고 싶어" 처럼 취향이 명소 쪽이어도, 하루가 점심·저녁에 걸치면 끼니마다 식당을 넣는다
    foods = [node(place(f"f{i}"), taste=0.0) for i in range(3)]
    sights = [node(place(f"s{i}", category="sight"), taste=1.0) for i in range(8)]
    route = planner([], foods + sights, to_min("10:00"), to_min("22:00"), None, no_travel)
    visits = schedule(route, to_min("10:00"), to_min("22:30"), no_travel)
    assert sorted(meal_slot(v.start) for v in visits if v.node.place.category == "food") == [0, 1]


@pytest.mark.parametrize("planner", [plan_greedy, plan_ortools])
def test_no_restaurant_when_the_day_misses_meal_times(planner):
    foods = [node(place(f"f{i}"), taste=0.0) for i in range(3)]
    sights = [node(place(f"s{i}", category="sight"), taste=1.0) for i in range(3)]
    route = planner([], foods + sights, to_min("14:00"), to_min("16:30"), None, no_travel)
    assert all(n.place.category != "food" for n in route)


def test_meal_cafe_zigzag_is_rejected():
    lunch, cafe, dinner = node(place("f1")), node(place("c1", category="cafe"), stay=90), node(place("f2"))
    sight = node(place("s1", category="sight"))
    day = (to_min("12:00"), to_min("22:00"))
    assert schedule([lunch, cafe, dinner], *day, no_travel) is None  # 밥 → 카페 → 밥
    assert schedule([cafe, lunch, node(place("c2", category="cafe"), stay=90)], *day, no_travel) is None  # 카페 → 밥 → 카페
    assert schedule([lunch, cafe, sight, dinner], *day, no_travel) is not None  # 사이에 다른 곳이 있으면 된다


def test_user_chosen_zigzag_is_allowed():
    def must(n):
        return Node(place=n.place, windows=start_windows(n.place, n.stay), stay=n.stay, cost=0, mandatory=True)

    lunch, cafe, dinner = node(place("f1")), node(place("c1", category="cafe"), stay=90), node(place("f2"))
    assert schedule([must(lunch), must(cafe), must(dinner)], to_min("12:00"), to_min("22:00"), no_travel) is not None


@pytest.mark.parametrize("planner", [plan_greedy, plan_ortools])
def test_planners_avoid_meal_cafe_zigzag(planner):
    foods = [node(place(f"f{i}")) for i in range(3)]
    cafes = [node(place(f"c{i}", category="cafe"), stay=90, taste=0.9) for i in range(3)]
    sights = [node(place(f"s{i}", category="sight"), taste=0.3) for i in range(3)]
    route = planner([], foods + cafes + sights, to_min("10:00"), to_min("22:00"), None, no_travel)
    visits = schedule(route, to_min("10:00"), to_min("22:30"), no_travel)
    assert visits is not None
    kinds = [v.node.place.category for v in visits]
    for a, b, c in zip(kinds, kinds[1:], kinds[2:]):
        assert (a, b, c) not in {("food", "cafe", "food"), ("cafe", "food", "cafe")}


def test_improve_order_removes_back_and_forth():
    from routefit.planner.core import improve_order

    # 한 줄로 놓인 a(0) b(1) c(2) d(3) 를 a → c → b → d 로 오가면 이동이 늘어난다
    pos = {"a": 0, "b": 1, "c": 2, "d": 3}
    nodes = {k: node(place(k, category="sight")) for k in pos}
    line = lambda x, y: 20 * abs(pos[x.id] - pos[y.id])  # noqa: E731
    route = [nodes[k] for k in "acbd"]
    better = improve_order(route, to_min("10:00"), to_min("22:00"), line)
    assert [n.id for n in better] in (list("abcd"), list("dcba"))


def test_improve_order_keeps_fixed_times():
    from routefit.planner.core import improve_order

    show = Node(place=place("show", category="culture"), windows=[(0, 24 * 60)], stay=120, cost=0, mandatory=True,
                fixed_start=to_min("18:00"))
    sights = [node(place(f"s{i}", category="sight")) for i in range(3)]
    better = improve_order([sights[0], sights[1], show, sights[2]], to_min("10:00"), to_min("22:00"), lambda a, b: 10)
    visits = schedule(better, to_min("10:00"), to_min("22:30"), lambda a, b: 10)
    assert next(v for v in visits if v.node.id == "show").start == to_min("18:00")


@pytest.mark.parametrize("planner", [plan_greedy, plan_ortools])
def test_planners_fill_activity_minimum(planner):
    """"서점 많이랑 전시" -> 서점 2곳·전시 1곳. 취향 점수가 낮아도 말한 만큼은 넣는다."""
    from dataclasses import replace

    from routefit.config import LIMITS

    books = [node(place(f"b{i}", category="cafe", tags={"activity": ["카페·디저트", "책·독서"]}), stay=90, taste=0.0) for i in range(2)]
    shows = [node(place(f"e{i}", category="culture", tags={"activity": ["전시 관람"]}), taste=0.0) for i in range(2)]
    others = [node(place(f"s{i}", category="sight"), taste=1.0) for i in range(4)] + [node(place("f0")), node(place("f1"))]
    limits = replace(LIMITS, want_min=(("책·독서", 2), ("전시 관람", 1)))
    route = planner([], books + shows + others, to_min("11:00"), to_min("19:30"), None, no_travel, limits)
    assert schedule(route, to_min("11:00"), to_min("20:00"), no_travel) is not None
    ids = {n.id for n in route}
    assert {"b0", "b1"} <= ids and ids & {"e0", "e1"}
    # 하루에 다 못 넣으면 실패하지 않고 넣을 수 있는 만큼만
    short = planner([], books + others, to_min("11:00"), to_min("13:00"), None, no_travel, limits)
    assert len({n.id for n in short} & {"b0", "b1"}) == 1


@pytest.mark.parametrize("planner", [plan_greedy, plan_ortools])
def test_planners_respect_wanted_maximum(planner):
    """"카페가 너무 많아" -> 카페 1곳까지, "전시는 한 곳만" -> 전시 1곳까지. 취향 점수가 높아도 더 넣지 않는다."""
    from dataclasses import replace

    from routefit.config import LIMITS

    cafes = [node(place(f"c{i}", category="cafe"), stay=90, taste=1.0) for i in range(3)]
    shows = [node(place(f"e{i}", category="culture", tags={"activity": ["전시 관람"]}), taste=1.0) for i in range(3)]
    others = [node(place(f"s{i}", category="sight"), taste=0.3) for i in range(3)]
    limits = replace(LIMITS, want_max=(("cafe", 1), ("전시 관람", 1)))
    route = planner([], cafes + shows + others, to_min("10:00"), to_min("22:00"), None, no_travel, limits)
    assert sum(n.place.category == "cafe" for n in route) <= 1
    assert sum(n.id.startswith("e") for n in route) <= 1
    # "카페 3곳" 처럼 기본 상한(2)보다 많이 원하면 상한도 올라간다
    more = replace(LIMITS, want_min=(("cafe", 3),))
    route = planner([], cafes + others, to_min("10:00"), to_min("22:00"), None, no_travel, more)
    assert sum(n.place.category == "cafe" for n in route) == 3
