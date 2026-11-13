"""입력 -> ① 조건 파싱 -> ② 취향 매칭 -> ③ 코스 최적화 -> ④ 추천 이유 -> 코스."""
import logging
import threading
import time
from dataclasses import replace
from typing import Optional

from . import config, filters, travel
from .courses import exposure_rates, save_course
from .data import is_measured, load_anchors, load_places, travel_minutes, travel_mode
from .embedding import PlaceIndex, get_embedder
from .explain import explain
from .models import (
    CATEGORY_KO,
    Alternative,
    Constraints,
    Course,
    Metrics,
    MustVisitInput,
    ParsedQuery,
    Place,
    PlanRequest,
    Stop,
    SwapIn,
    to_hm,
    to_min,
)
from .parser import find_by_name, parse_query
from .place_search import default_stay, is_kakao_id
from .planner import Node, PlanError, Visit, objective, plan_greedy, plan_ortools, schedule, start_windows
from .planner.core import fill_day, improve_order, matches, meal_slot, want_shortfall

log = logging.getLogger(__name__)


MEASURE_ROUNDS = 3  # 실측한 이동시간으로 시간표가 맞지 않을 때 코스를 다시 고르는 최대 횟수

_index_lock = threading.Lock()
_index_cache: Optional[PlaceIndex] = None


def _index() -> PlaceIndex:
    """장소 임베딩 인덱스. 모델 로딩이 오래 걸리므로 한 번만 만들고, 만드는 중인 요청은 기다린다.
    관리자가 장소를 고치면 load_places() 가 새 리스트를 돌려주므로 그때 다시 만든다."""
    global _index_cache
    with _index_lock:
        places = load_places()
        if _index_cache is None or _index_cache.source is not places:
            started = time.monotonic()
            _index_cache = PlaceIndex(places, get_embedder())
            log.info("임베딩 준비 완료: %s (%.0f초)", _index_cache.embedder.name, time.monotonic() - started)
    return _index_cache


def warm_up() -> None:
    """서버 시작 때 미리 불러 두어 첫 요청이 모델 로딩을 기다리지 않게 한다."""
    _index()


def _find(known: list[Place], m: MustVisitInput) -> Optional[Place]:
    if is_kakao_id(m.id):  # 검색으로 고른 카카오 장소: 화면이 보낸 정보로 만든다
        if m.name is None or m.lat is None or m.lng is None:
            return None
        category = m.category or "etc"
        return Place(
            id=m.id, name=m.name, category=category, area=m.area or "광주", lat=m.lat, lng=m.lng,
            description=m.description or "", stay_min=default_stay(category, f"{m.description or ''} {m.name}"),
        )
    if m.id:
        return next((p for p in known if p.id == m.id), None)
    return find_by_name(known, m.name)


def _stay(place: Place) -> int:
    """머무는 시간. 카페는 커피만 마시고 나오지 않도록, 식당은 밥을 서두르지 않도록 최소 시간을 둔다."""
    if place.category == "cafe":
        return max(place.stay_min, config.LIMITS.min_cafe_stay)
    if place.category == "food":
        return max(place.stay_min, config.LIMITS.min_meal_stay)
    return place.stay_min


def _must_nodes(req: PlanRequest, parsed: ParsedQuery, known: list[Place]) -> list[Node]:
    # 화면에서 직접 지정한 Must Visit 이 있으면 그것이 우선, 없으면 문장에서 파싱한 것을 쓴다.
    inputs = req.must_visits or [
        MustVisitInput(name=m.name, start=m.start, stay_min=m.stay_min) for m in parsed.must_visits
    ]
    nodes, seen = [], set()
    for m in inputs:
        place = _find(known, m)
        if place is None:
            raise PlanError(f"꼭 갈 곳 '{m.name or m.id}' 을(를) 찾을 수 없습니다. 검색 결과에서 골라 주세요.")
        if place.id in seen:
            continue
        seen.add(place.id)
        stay = m.stay_min or _stay(place)  # 사용자가 적은 머무는 시간이 우선
        nodes.append(
            Node(
                place=place,
                windows=start_windows(place, stay),  # 사용자가 고른 곳은 식사 시간대를 강제하지 않는다
                stay=stay,
                cost=place.cost,
                mandatory=True,
                fixed_start=to_min(m.start) if m.start else None,
            )
        )
    return nodes


def _origin_node(req: PlanRequest, known: list[Place], day_start: int) -> Optional[Node]:
    """출발 위치. 머무는 시간 0 으로 하루 시작 시각에 고정해 코스 맨 앞에 둔다. 유형은 '기타' 로 바꿔
    식사·카페 규칙에 걸리지 않게 한다(출발지가 식당이어도 그 끼니를 먹은 것으로 치지 않는다)."""
    if req.start is None or not (req.start.id or req.start.name):
        return None
    place = _find(known, req.start)
    if place is None:
        raise PlanError(f"출발 위치 '{req.start.name or req.start.id}' 을(를) 찾을 수 없습니다. 검색 결과에서 골라 주세요.")
    return Node(
        place=place.model_copy(update={"category": "etc", "cost": 0}),
        windows=[(0, 48 * 60)],
        stay=0,
        cost=0,
        mandatory=True,
        fixed_start=day_start,
        origin=True,
    )


def _check_fixed_conflicts(musts: list[Node]) -> None:
    """시작 시각이 고정된 필수 방문지끼리 (머무는 시간 + 이동시간) 겹치면 어느 두 곳인지 알려 준다."""
    fixed = sorted((m for m in musts if m.fixed_start is not None), key=lambda m: m.fixed_start)
    travel.measure_route(fixed)
    for a, b in zip(fixed, fixed[1:]):
        end = a.fixed_start + a.stay
        move = travel_minutes(a, b)
        if end + move > b.fixed_start:
            gap = f" + 이동 {move}분" if move and end <= b.fixed_start else ""
            raise PlanError(
                f"꼭 갈 곳의 시간이 겹칩니다: '{a.place.name}'({to_hm(a.fixed_start)}~{to_hm(end)}{gap}) 과 "
                f"'{b.place.name}'({to_hm(b.fixed_start)} 시작). 방문 예정 시각이나 머무는 시간을 조정해 주세요."
            )


def _excluded(places: list[Place], c: Constraints, query: str, musts: list[Node], exclude_ids: set[str]) -> set[str]:
    """AI 추천에서 뺄 장소 id. 무엇을 왜 뺐는지는 c.notes 에 남긴다."""
    out: set[str] = set(exclude_ids)
    by_keyword = [p for p in places if filters.has_keyword(p, c.avoid_keywords)]
    out |= {p.id for p in by_keyword}
    if filters.is_date(query, c.companions) and not filters.wants_history(query):
        memorial = [p for p in places if filters.is_memorial(p) and p.id not in out]
        if memorial:
            out |= {p.id for p in memorial}
            c.notes.append(f"데이트 코스라 추모 공간({', '.join(p.name for p in memorial)})은 추천에서 뺐습니다.")
    for kind in dict.fromkeys(k for k in (filters.kind_of(m.place) for m in musts) if k):
        same = [p for p in places if filters.kind_of(p) == kind and p.id not in out]
        if same:
            out |= {p.id for p in same}
            c.notes.append(f"꼭 갈 곳과 같은 {kind}({', '.join(p.name for p in same)})은 추천에서 뺐습니다.")
    return out


def _candidate_nodes(c: Constraints, sims: dict[str, float], exclude: set[str], activities: set[str]) -> list[Node]:
    places = [
        p
        for p in load_places()
        if p.id not in exclude
        and p.category not in c.avoid_categories
        and (c.weekday is None or c.weekday not in p.closed_days)
    ]
    if not places:
        return []
    lo = min(sims[p.id] for p in places)
    span = (max(sims[p.id] for p in places) - lo) or 1.0
    # 인기 장소 쏠림 감점: 최근 코스에 AI 추천으로 너무 자주 나온 곳은 그만큼 덜 고른다
    rates = (
        exposure_rates(config.POPULARITY_WINDOW, config.POPULARITY_MIN_COURSES) if config.POPULARITY_WEIGHT > 0 else {}
    )
    nodes = [
        Node(
            place=p,
            # 뺀 끼니(c.skip_meals)에는 식당이 들어갈 시간대가 없어서 그 끼니 점수도 생기지 않는다
            windows=start_windows(p, _stay(p), meal=p.category == "food", skip_meals=tuple(c.skip_meals)),
            stay=_stay(p),
            cost=p.cost,
            meal=p.category == "food",
            taste=(sims[p.id] - lo) / span,
            similarity=sims[p.id],
            companion_fit=bool(c.companions) and c.companions in p.tags.get("companions", []),
            activity_fit=bool(activities & set(p.tags.get("activity", []))),
            popularity=config.POPULARITY_WEIGHT * max(0.0, rates.get(p.id, 0.0) - config.POPULARITY_TARGET),
        )
        for p in places
    ]
    return [n for n in nodes if n.windows]  # 머무는 시간만큼 열려 있는 구간이 없는 곳은 뺀다


def _stop_limits(c: Constraints, n_musts: int, day_min: int) -> config.Limits:
    """하루 장소 수(꼭 갈 곳 포함)를 AI 추천 장소 수의 최소·최대로 바꾼다. 말이 없으면 하루 길이에 맞춘 상한
    (LIMITS.minutes_per_place 분에 1곳, 많아야 LIMITS.max_places)에서 꼭 갈 곳을 뺀 만큼까지.
    문장에서 장소 수를 말했으면 상한을 넘더라도 그 수를 따른다."""
    if c.max_places is not None:
        max_ai = max(0, c.max_places - n_musts)
    else:
        cap = min(config.LIMITS.max_places, max(1, day_min // config.LIMITS.minutes_per_place))
        max_ai = min(config.LIMITS.max_ai_stops, max(0, cap - n_musts))
    min_ai = max(0, (c.min_places or 0) - n_musts)
    return replace(config.LIMITS, min_ai_stops=min_ai, max_ai_stops=max(max_ai, min_ai))


def _choosing_travel(c: Constraints):
    """코스를 고를 때 쓰는 이동시간. 대중교통을 타지 않겠다고 했으면 걸어서 못 가는 구간을 LIMITS.no_transit_extra_min
    만큼 더 걸리는 것으로 본다. 둘 다 사용자가 정한 곳(출발 위치·꼭 갈 곳)인 구간은 피할 수 없으므로 그대로 둔다."""
    if not c.walk_only:
        return travel_minutes
    extra = config.LIMITS.no_transit_extra_min

    def minutes(a: Node, b: Node) -> int:
        t = travel_minutes(a, b)
        if (a.mandatory and b.mandatory) or travel_mode(a, b) == "walk":
            return t
        return t + extra

    return minutes


def _to_course(visits: list[Visit], c: Constraints, engine: dict[str, str]) -> Course:
    summary, reasons, engine["explainer"] = explain(visits, c)
    stops = [
        Stop(
            order=i,
            place_id=v.node.id,
            name=v.node.place.name,
            kind="start" if v.node.origin else "must" if v.node.mandatory else "ai",
            category=v.node.place.category,
            area=v.node.place.area,
            lat=v.node.lat,
            lng=v.node.lng,
            arrive=to_hm(v.arrive),
            start=to_hm(v.start),
            end=to_hm(v.end),
            travel_min=v.travel,
            travel_mode=travel_mode(visits[i - 2].node, v.node) if i > 1 else None,
            stay_min=v.node.stay,
            cost=v.node.cost,
            similarity=None if v.node.mandatory else round(v.node.similarity, 3),
            local_score=None if v.node.mandatory else round(v.node.place.local_score, 3),
            is_local_commerce=v.node.place.is_local_commerce,
            reason="출발 위치" if v.node.origin else "직접 고른 꼭 갈 곳" if v.node.mandatory else reasons.get(v.node.id, ""),
        )
        for i, v in enumerate(visits, 1)
    ]
    ai = [s for s in stops if s.kind == "ai"]
    places = [s for s in stops if s.kind != "start"]  # 출발 위치는 방문 장소로 세지 않는다
    local = sum(s.is_local_commerce for s in ai)
    metrics = Metrics(
        n_places=len(places),
        n_ai_places=len(ai),
        stay_min=sum(s.stay_min for s in places),
        travel_min=sum(s.travel_min for s in stops),
        total_cost=sum(s.cost for s in stops),
        local_commerce_count=local,
        local_commerce_ratio=round(local / len(ai), 3) if ai else 0.0,
        score=round(objective(visits, to_min(c.day_end)), 3),
    )
    return Course(stops=stops, summary=summary, metrics=metrics, constraints=c, engine=engine)


WEEKDAY_KO = "월화수목금토일"


def _pick(screen, sentence, default):
    """화면 입력 > 문장 > 기본값. (값, 출처)"""
    if screen is not None:
        return screen, "화면"
    if sentence is not None:
        return sentence, "문장"
    return default, "기본값"


def make_course(req: PlanRequest, extra_notes: tuple[str, ...] = ()) -> Course:
    """extra_notes: '인식된 조건' 맨 앞에 보일 안내(다른 곳으로 바꾸기 등)."""
    known = load_anchors() + load_places()

    # ① 자연어 조건 파싱
    parsed, parser_used = parse_query(req.query, known)
    musts = _must_nodes(req, parsed, known)
    _check_fixed_conflicts(musts)
    sources: dict[str, str] = {}
    notes: list[str] = list(extra_notes)

    if musts:
        sources["must_visits"] = "화면" if req.must_visits else "문장"
    if req.must_visits and parsed.must_visits:
        chosen = {m.place.name for m in musts}
        found = [m.name for m in parsed.must_visits if m.name not in chosen]
        if found:
            notes.append(f"문장에서 '{', '.join(found)}' 을(를) 찾았지만, 화면에서 고른 꼭 갈 곳을 썼습니다.")

    start_hm, sources["day_start"] = _pick(req.day_start, parsed.day_start, config.DEFAULT_DAY_START)
    end_hm, sources["day_end"] = _pick(req.day_end, parsed.day_end, config.DEFAULT_DAY_END)
    for key, screen, sentence in (("시작", req.day_start, parsed.day_start), ("종료", req.day_end, parsed.day_end)):
        if screen is not None and sentence is not None and screen != sentence:
            notes.append(f"문장의 하루 {key} 시각({sentence}) 대신 화면에 입력한 {screen} 을(를) 썼습니다.")

    day_start, day_end = to_min(start_hm), to_min(end_hm)
    for m in musts:  # 고정 일정은 하루의 시간 축을 결정한다
        if m.fixed_start is not None:
            if m.fixed_start < day_start:
                day_start = m.fixed_start
                sources["day_start"] = "고정 일정"
            if m.fixed_start + m.stay > day_end:
                day_end = m.fixed_start + m.stay
                sources["day_end"] = "고정 일정"
                notes.append(f"'{m.place.name}' 일정({to_hm(m.fixed_start)}~{to_hm(day_end)})에 맞춰 하루 종료를 늘렸습니다.")
    origin = _origin_node(req, known, day_start)
    if origin is not None:
        _check_fixed_conflicts([origin, *musts])  # 출발 위치에서 시각을 정한 첫 일정까지 갈 수 있는지
    if day_end <= day_start:
        raise PlanError(f"하루 종료({to_hm(day_end)})가 시작({to_hm(day_start)})보다 빠릅니다.")

    budget, budget_source = _pick(req.budget, parsed.budget, None)
    if budget is not None:
        sources["budget"] = budget_source
    if req.budget is not None and parsed.budget is not None and req.budget != parsed.budget:
        notes.append(f"문장의 예산({parsed.budget:,}원) 대신 화면에 입력한 {req.budget:,}원을 썼습니다.")

    weekday = req.visit_date.weekday() if req.visit_date else parsed.weekday
    if weekday is not None:
        sources["weekday"] = "화면" if req.visit_date else "문장"
        closed = [m.place.name for m in musts if weekday in m.place.closed_days]
        if closed:
            notes.append(f"'{', '.join(closed)}' 은(는) {WEEKDAY_KO[weekday]}요일 휴무입니다. 운영 여부를 확인해 주세요.")
    else:
        notes.append("방문 요일을 몰라 휴무일을 확인하지 않았습니다. 방문 날짜를 지정하거나 문장에 요일을 적어 주세요.")
    if req.visit_date and parsed.weekday is not None and parsed.weekday != weekday:
        notes.append(
            f"문장의 {WEEKDAY_KO[parsed.weekday]}요일 대신 화면에 입력한 날짜"
            f"({req.visit_date:%m/%d}, {WEEKDAY_KO[weekday]}요일)를 썼습니다."
        )

    min_places, max_places = filters.place_count(req.query, config.LIMITS.fewer_places, config.LIMITS.max_places)
    c = Constraints(
        taste=parsed.taste or req.query,
        day_start=to_hm(day_start),
        day_end=to_hm(day_end),
        budget=budget,
        companions=parsed.companions,
        weekday=weekday,
        avoid_categories=parsed.avoid_categories,
        skip_meals=parsed.skip_meals,
        avoid_keywords=parsed.avoid_keywords,
        excluded_places=[p.name for p in load_places() if p.id in set(req.exclude_ids)],
        walk_only=filters.avoids_transit(req.query),
        min_places=min_places,
        max_places=max_places,
        visit_date=req.visit_date,
        must_visits=[m.place.name for m in musts],
        start_place=origin.place.name if origin else None,
        sources=sources,
        notes=notes,
    )

    # ② 임베딩 취향 매칭
    index = _index()
    excluded = _excluded(load_places(), c, req.query, musts, set(req.exclude_ids))
    fixed_nodes = ([origin] if origin else []) + musts  # 출발 위치 + 꼭 갈 곳: 코스에서 빼지 않는다
    # 문장에서 말한 할 거리·유형의 양: "서점 좀 많이랑 전시" -> {"책·독서": (2, None), "전시 관람": (1, None)},
    # "카페가 너무 많아" -> {"cafe": (0, 1)}
    wants = filters.quantity_wants(req.query)
    activities = {k for k in wants if k not in filters.CATEGORY_KEYS}
    candidates = _candidate_nodes(c, index.similarities(c.taste), {m.id for m in fixed_nodes} | excluded, activities)

    # ③ 제약 최적화
    planner_name = req.planner or config.DEFAULT_PLANNER
    planner = plan_ortools if planner_name == "ortools" else plan_greedy
    # 후보 비교는 어림값으로 하고, 고른 코스의 구간만 TMAP 으로 재서 시간표를 다시 짠다.
    # 실측으로 시간이 맞지 않으면 실측값이 반영된 상태로 다시 고른다.
    choose_travel = _choosing_travel(c)  # 고를 때만 쓴다. 시간표(schedule)는 실제 이동시간으로 짠다
    limits = _stop_limits(c, len(musts), day_end - day_start)
    if req.only_ids is not None:
        # '다른 곳으로 바꾸기': 나머지 AI 장소는 그대로 두고 바꾼 곳 하나만 다르게, 순서·시간을 다시 짠다
        keep = set(req.only_ids)
        candidates = [n for n in candidates if n.id in keep]
        limits = replace(limits, min_ai_stops=len(candidates), max_ai_stops=len(candidates))
        if len(candidates) < len(keep):
            c.notes.append("바꾸기 전 코스의 장소 일부는 지금 조건(휴무일 등)에 맞지 않아 뺐습니다.")
    else:
        # 문장에서 말한 할 거리·유형의 양(꼭 갈 곳으로 이미 들어간 만큼은 빼고)
        in_musts = {k: sum(matches(m, k) for m in musts) for k in wants}
        want_min = tuple((k, lo - in_musts[k]) for k, (lo, _) in wants.items() if lo - in_musts[k] > 0)
        want_max = tuple((k, max(0, hi - in_musts[k])) for k, (_, hi) in wants.items() if hi is not None)
        # 하루가 짧아 장소 수 상한(100분에 1곳)보다 많이 말했으면 말한 만큼은 넣을 수 있게 상한을 올린다.
        # 들어갈 시간이 없으면 플래너가 넣을 수 있는 만큼만 넣고, 끼니보다 말한 할 거리를 먼저 채운다
        limits = replace(limits, want_min=want_min, want_max=want_max,
                         max_ai_stops=max(limits.max_ai_stops, sum(k for _, k in want_min)))
    visits = None
    if req.order_ids is not None:
        # '다른 곳으로 바꾸기': 장소 순서는 바꾸기 전 코스 그대로 두고 시간만 다시 맞춘다
        pool = {n.id: n for n in fixed_nodes + candidates}
        if set(req.order_ids) == set(pool) and len(req.order_ids) == len(pool):
            route = [pool[i] for i in req.order_ids]
            travel.measure_route(route)
            visits = schedule(route, day_start, day_end + config.LIMITS.overtime_grace_min, travel_minutes)
        if visits is None:
            c.notes.append("순서를 그대로 두면 영업시간·이동시간이 맞지 않아 순서를 다시 짰습니다.")
    for _ in range(MEASURE_ROUNDS if visits is None else 0):
        route = planner(fixed_nodes, candidates, day_start, day_end, c.budget, choose_travel, limits)
        route = improve_order(route, day_start, day_end, choose_travel)  # 같은 장소를 덜 오가는 순서로
        new_legs = travel.measure_route(route)
        visits = schedule(route, day_start, day_end + config.LIMITS.overtime_grace_min, travel_minutes)
        if visits is not None or not new_legs:
            break
    if visits is None and planner is plan_ortools:
        # OR-Tools 의 시간 모델과 schedule() 이 어긋나 시간표가 안 나오면 그리디로 한 번 더
        route = plan_greedy(fixed_nodes, candidates, day_start, day_end, c.budget, choose_travel, limits)
        travel.measure_route(route)
        visits = schedule(route, day_start, day_end + config.LIMITS.overtime_grace_min, travel_minutes)
    if visits is None:
        raise PlanError("실행 가능한 코스를 만들지 못했습니다. 시간·예산 조건을 완화해 주세요.")
    # 장소 수를 줄여 하루가 일찍 끝나면 남는 시간만큼 더 머문다(순서·장소는 그대로라 이동시간은 이미 쟀다)
    filled = schedule(fill_day([v.node for v in visits], day_start, day_end, travel_minutes), day_start, day_end, travel_minutes)
    if filled is not None:
        visits = filled
    n_places = sum(not v.node.origin for v in visits)
    for key, k in want_shortfall([v.node for v in visits], limits).items():
        want = dict(limits.want_min)[key]
        label = CATEGORY_KO.get(key, key)
        c.notes.append(f"'{label}' 장소를 {want}곳 넣으려 했지만, 후보·영업시간·하루 시간 안에 {want - k}곳만 넣을 수 있었습니다.")
    if c.max_places is not None and len(musts) > c.max_places:
        c.notes.append(f"꼭 갈 곳이 {len(musts)}곳이라 말씀하신 {c.max_places}곳보다 많습니다. 꼭 갈 곳만 넣었습니다.")
    elif c.min_places is not None and n_places < c.min_places:
        c.notes.append(f"하루 시간·영업시간 안에 {n_places}곳까지만 넣을 수 있었습니다(말씀하신 {c.min_places}곳).")
    if c.walk_only:
        rides = [b.node.place.name for a, b in zip(visits, visits[1:]) if travel_mode(a.node, b.node) != "walk"]
        c.notes.append(
            f"대중교통을 타지 않도록 걸어서 닿는 곳으로 골랐지만, 꼭 갈 곳이 멀어 {', '.join(rides)}까지는 대중교통 구간이 남았습니다."
            if rides
            else "대중교통을 타지 않도록 걸어서 닿는 곳끼리 골랐습니다."
        )

    # ④ 추천 이유 생성
    measured = all(is_measured(a.node, b.node) for a, b in zip(visits, visits[1:]))
    engine = {
        "parser": parser_used,
        "embedder": index.embedder.name,
        "planner": planner_name,
        "travel": "tmap" if measured else "estimate",
    }
    course = _to_course(visits, c, engine)
    course.id = save_course(req, course)
    return course


# ---------- 결과에서 '다른 곳으로 바꾸기' ----------

ALTERNATIVES = 3  # 장소 하나에 보여 주는 후보 수
NEAR_START_MIN = 90  # 식당이 아닌 곳은 원래 시작 시각 앞뒤 이만큼 안에 열려 있어야 한다


def _course_stop(course: Course, order: int) -> Stop:
    stop = next((s for s in course.stops if s.order == order), None)
    if stop is None:
        raise PlanError("바꿀 장소를 코스에서 찾을 수 없습니다.")
    if stop.kind != "ai":
        raise PlanError("AI 가 추천한 장소만 바꿀 수 있습니다(꼭 갈 곳·출발 위치는 입력칸에서 바꿔 주세요).")
    return stop


def _fits_role(n: Node, stop: Stop) -> bool:
    """같은 역할인지: 같은 유형이고, 식당은 같은 끼니(점심·저녁)에, 다른 곳은 원래 시각 근처에 들를 수 있다."""
    if n.place.category != stop.category:
        return False
    start = to_min(stop.start)
    if stop.category == "food":
        slot = meal_slot(start)
        if slot is None:
            return bool(n.windows)
        _, m0, m1 = config.LIMITS.meal_windows[slot]
        return any(lo <= m1 and hi >= m0 for lo, hi in n.windows)
    return any(lo <= start + NEAR_START_MIN and hi >= start - NEAR_START_MIN for lo, hi in n.windows)


def _course_route(course: Course, pool: dict[str, Node], by_id: dict[str, Place]) -> Optional[list[Node]]:
    """저장된 코스를 시간표를 다시 짤 수 있는 노드 순서로 되살린다. AI 장소는 후보 노드(원래 머무는 시간·식사 시간대),
    꼭 갈 곳은 입력한 시작 시각·머무는 시간, 출발 위치는 하루 시작에 고정. 되살릴 수 없으면 None."""
    starts = {m.id: m.start for m in course.request.must_visits if m.id and m.start}
    route = []
    for s in course.stops:
        if s.kind == "ai":
            if s.place_id not in pool:
                return None
            route.append(pool[s.place_id])
            continue
        place = by_id.get(s.place_id) or _stop_ref(s).place
        if s.kind == "start":
            route.append(Node(place=place.model_copy(update={"category": "etc", "cost": 0}), windows=[(0, 48 * 60)], stay=0, cost=0,
                              mandatory=True, fixed_start=to_min(s.start), origin=True))
        else:
            route.append(Node(place=place, windows=start_windows(place, s.stay_min), stay=s.stay_min, cost=s.cost, mandatory=True,
                              fixed_start=to_min(starts[s.place_id]) if s.place_id in starts else None))
    return route


def alternatives(course: Course, order: int, k: int = ALTERNATIVES) -> list[Alternative]:
    """코스의 AI 추천 장소(order) 대신 넣을 만한 곳 k 개. 같은 역할 후보를 추천 점수(취향·지역상권·동행·할 거리)에서
    앞뒤 장소와의 이동 부담을 뺀 순서로 고른다. 이미 코스에 있는 곳, 뺀 곳, 휴무인 곳은 빼고."""
    stop = _course_stop(course, order)
    req = course.request
    if req is None:
        raise PlanError("저장된 요청이 없는 코스라 바꿀 수 없습니다. 코스를 다시 만들어 주세요.")
    c = course.constraints.model_copy(deep=True)  # _excluded 가 notes 에 덧붙이므로 복사본으로
    places = load_places()
    by_id = {p.id: p for p in load_anchors() + places}
    musts = [Node(place=by_id[s.place_id], windows=[], stay=0, cost=0) for s in course.stops if s.kind == "must" and s.place_id in by_id]
    in_course = {s.place_id for s in course.stops}
    ai_ids = {s.place_id for s in course.stops if s.kind == "ai"}
    exclude = (in_course - ai_ids) | _excluded(places, c, req.query, musts, set(req.exclude_ids))
    pool = {n.id: n for n in _candidate_nodes(c, _index().similarities(c.taste), exclude, filters.wanted_activities(req.query))}
    nodes = [n for n in pool.values() if n.id not in in_course and _fits_role(n, stop)]
    # 그 자리에 갈아끼워도 시간표가 나오는 곳만(순서를 그대로 두고 바꾸므로)
    route = _course_route(course, pool, by_id)
    if route is not None:
        i = next(j for j, s in enumerate(course.stops) if s.order == order)
        day_start, hard_end = to_min(c.day_start), to_min(c.day_end) + config.LIMITS.overtime_grace_min
        nodes = [n for n in nodes if schedule(route[:i] + [n] + route[i + 1:], day_start, hard_end, travel_minutes) is not None]

    i = course.stops.index(stop)
    prev = _stop_ref(course.stops[i - 1]) if i > 0 else None
    nxt = _stop_ref(course.stops[i + 1]) if i + 1 < len(course.stops) else None
    def legs(n: Node) -> tuple[Optional[int], Optional[int]]:
        return (travel_minutes(prev, n) if prev else None, travel_minutes(n, nxt) if nxt else None)

    def score(n: Node) -> float:
        before, after = legs(n)
        return n.value - config.WEIGHTS.travel_per_min * ((before or 0) + (after or 0))

    if course.constraints.budget is not None:  # 바꿔 넣어도 예산 안이어야 한다
        others = course.metrics.total_cost - stop.cost
        nodes = [n for n in nodes if others + n.cost <= course.constraints.budget]
    out = []
    for n in sorted(nodes, key=score, reverse=True)[:k]:
        before, after = legs(n)
        p = n.place
        out.append(
            Alternative(
                place_id=p.id, name=p.name, category=p.category, area=p.area, cost=p.cost, is_local_commerce=p.is_local_commerce,
                similarity=round(n.similarity, 3), taste=round(n.taste, 3), travel_from_prev=before, travel_to_next=after,
                description=p.description,
            )
        )
    return out


def _stop_ref(s: Stop):
    """Stop 을 travel_minutes 가 받는 모양(id·lat·lng)으로. Stop 의 place_id 를 id 로 쓴다."""
    return Node(place=Place(id=s.place_id, name=s.name, category=s.category, area=s.area, lat=s.lat, lng=s.lng), windows=[], stay=0, cost=0)


def swap_course(course: Course, swap: SwapIn) -> Course:
    """코스의 AI 추천 장소 하나를 다른 곳으로 바꾼다. 그 자리만 갈아끼우고 나머지 장소와 순서는 그대로 두며
    시간만 다시 맞춘다(그 순서로 시간이 안 맞으면 순서를 다시 짠다). 바꾼 장소는 뺀 장소에 넣어 다시 나오지 않게 한다."""
    stop = _course_stop(course, swap.order)
    req = course.request
    if req is None:
        raise PlanError("저장된 요청이 없는 코스라 바꿀 수 없습니다. 코스를 다시 만들어 주세요.")
    if swap.place_id in {s.place_id for s in course.stops}:
        raise PlanError("이미 코스에 있는 장소입니다.")
    new = next((p for p in load_places() if p.id == swap.place_id), None)
    if new is None:
        raise PlanError("바꿀 장소를 찾을 수 없습니다.")
    keep = [s.place_id for s in course.stops if s.kind == "ai" and s.order != swap.order] + [new.id]
    order = [new.id if s.order == swap.order else s.place_id for s in course.stops]  # 바꾼 자리만 갈아끼운 순서
    exclude = list(dict.fromkeys([*req.exclude_ids, stop.place_id]))
    musts = req.must_visits
    if not musts:
        # 문장에서 읽은 꼭 갈 곳: 다시 짤 때 문장을 다시 읽으면 AI 가 이번엔 꼭 갈 곳으로 안 읽어 빠질 수 있다.
        # 바꾸기 전 코스에 있던 꼭 갈 곳을 그대로 붙잡아 둔다
        musts = [MustVisitInput(id=s.place_id, stay_min=s.stay_min) for s in course.stops if s.kind == "must"]
    new_req = req.model_copy(update={"only_ids": keep, "order_ids": order, "exclude_ids": exclude, "must_visits": musts})
    swapped = make_course(new_req, (f"'{stop.name}' 대신 '{new.name}' 을(를) 넣고 시간을 다시 맞췄습니다.",))
    if new.id not in {s.place_id for s in swapped.stops}:
        raise PlanError(f"'{new.name}' 을(를) 넣으면 시간이 맞지 않아 바꿀 수 없습니다. 다른 곳을 골라 주세요.")
    return swapped
