"""입력 -> ① 조건 파싱 -> ② 취향 매칭 -> ③ 코스 최적화 -> ④ 추천 이유 -> 코스."""
import logging
import threading
import time
from typing import Optional

from . import config, travel
from .courses import save_course
from .data import is_measured, load_anchors, load_places, travel_minutes, travel_mode
from .embedding import PlaceIndex, get_embedder
from .explain import explain
from .models import (
    Constraints,
    Course,
    Metrics,
    MustVisitInput,
    ParsedQuery,
    Place,
    PlanRequest,
    Stop,
    to_hm,
    to_min,
)
from .parser import find_by_name, parse_query
from .planner import Node, PlanError, Visit, objective, plan_greedy, plan_ortools, schedule, start_windows

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


def _find(known: list[Place], id: Optional[str], name: Optional[str]) -> Optional[Place]:
    if id:
        return next((p for p in known if p.id == id), None)
    return find_by_name(known, name)


def _stay(place: Place) -> int:
    """머무는 시간. 카페는 커피만 마시고 나오지 않도록 최소 시간을 둔다."""
    if place.category == "cafe":
        return max(place.stay_min, config.LIMITS.min_cafe_stay)
    return place.stay_min


def _must_nodes(req: PlanRequest, parsed: ParsedQuery, known: list[Place]) -> list[Node]:
    # 화면에서 직접 지정한 Must Visit 이 있으면 그것이 우선, 없으면 문장에서 파싱한 것을 쓴다.
    inputs = req.must_visits or [
        MustVisitInput(name=m.name, start=m.start, stay_min=m.stay_min) for m in parsed.must_visits
    ]
    nodes, seen = [], set()
    for m in inputs:
        place = _find(known, m.id, m.name)
        if place is None:
            raise PlanError(f"필수 방문지 '{m.name or m.id}' 을(를) 찾을 수 없습니다. 목록에서 선택해 주세요.")
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
                f"필수 방문지 시간이 겹칩니다: '{a.place.name}'({to_hm(a.fixed_start)}~{to_hm(end)}{gap}) 과 "
                f"'{b.place.name}'({to_hm(b.fixed_start)} 시작). 방문 예정 시각이나 머무는 시간을 조정해 주세요."
            )


def _candidate_nodes(c: Constraints, sims: dict[str, float], exclude: set[str]) -> list[Node]:
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
    nodes = [
        Node(
            place=p,
            windows=start_windows(p, _stay(p), meal=p.category == "food"),
            stay=_stay(p),
            cost=p.cost,
            meal=p.category == "food",
            taste=(sims[p.id] - lo) / span,
            similarity=sims[p.id],
            companion_fit=bool(c.companions) and c.companions in p.tags.get("companions", []),
        )
        for p in places
    ]
    return [n for n in nodes if n.windows]  # 머무는 시간만큼 열려 있는 구간이 없는 곳은 뺀다


def _to_course(visits: list[Visit], c: Constraints, engine: dict[str, str]) -> Course:
    summary, reasons, engine["explainer"] = explain(visits, c)
    stops = [
        Stop(
            order=i,
            place_id=v.node.id,
            name=v.node.place.name,
            kind="must" if v.node.mandatory else "ai",
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
            reason="사용자가 지정한 필수 방문지" if v.node.mandatory else reasons.get(v.node.id, ""),
        )
        for i, v in enumerate(visits, 1)
    ]
    ai = [s for s in stops if s.kind == "ai"]
    local = sum(s.is_local_commerce for s in ai)
    metrics = Metrics(
        n_places=len(stops),
        n_ai_places=len(ai),
        stay_min=sum(s.stay_min for s in stops),
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


def make_course(req: PlanRequest) -> Course:
    known = load_anchors() + load_places()

    # ① 자연어 조건 파싱
    parsed, parser_used = parse_query(req.query, known)
    musts = _must_nodes(req, parsed, known)
    _check_fixed_conflicts(musts)
    sources: dict[str, str] = {}
    notes: list[str] = []

    if musts:
        sources["must_visits"] = "화면" if req.must_visits else "문장"
    if req.must_visits and parsed.must_visits:
        chosen = {m.place.name for m in musts}
        found = [m.name for m in parsed.must_visits if m.name not in chosen]
        if found:
            notes.append(f"문장에서 '{', '.join(found)}' 을(를) 찾았지만, 화면에서 고른 필수 방문지를 썼습니다.")

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

    c = Constraints(
        taste=parsed.taste or req.query,
        day_start=to_hm(day_start),
        day_end=to_hm(day_end),
        budget=budget,
        companions=parsed.companions,
        weekday=weekday,
        avoid_categories=parsed.avoid_categories,
        visit_date=req.visit_date,
        must_visits=[m.place.name for m in musts],
        sources=sources,
        notes=notes,
    )

    # ② 임베딩 취향 매칭
    index = _index()
    candidates = _candidate_nodes(c, index.similarities(c.taste), {m.id for m in musts})

    # ③ 제약 최적화
    planner_name = req.planner or config.DEFAULT_PLANNER
    planner = plan_ortools if planner_name == "ortools" else plan_greedy
    # 후보 비교는 어림값으로 하고, 고른 코스의 구간만 TMAP 으로 재서 시간표를 다시 짠다.
    # 실측으로 시간이 맞지 않으면 실측값이 반영된 상태로 다시 고른다.
    for _ in range(MEASURE_ROUNDS):
        route = planner(musts, candidates, day_start, day_end, c.budget, travel_minutes)
        new_legs = travel.measure_route(route)
        visits = schedule(route, day_start, day_end + config.LIMITS.overtime_grace_min, travel_minutes)
        if visits is not None or not new_legs:
            break
    if visits is None:
        raise PlanError("실행 가능한 코스를 만들지 못했습니다. 시간·예산 조건을 완화해 주세요.")

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
