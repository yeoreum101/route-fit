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


# 그리디는 한 곳씩 끼워 넣어서, 오후를 먼저 채우면 장소 수 상한에 걸려 저녁을 못 넣을 수 있다
@pytest.mark.parametrize("planner, n_meals", [(plan_greedy, {1, 2}), (plan_ortools, {2})])
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
