"""입력 -> ① 조건 파싱 -> ② 취향 매칭 -> ③ 코스 최적화 -> ④ 추천 이유 -> 코스."""
import logging
import threading
import time
from typing import Optional

from . import config
from .courses import save_course
from .data import load_anchors, load_places, travel_minutes
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
from .parser import parse_query
from .planner import Node, PlanError, Visit, objective, plan_greedy, plan_ortools, schedule

log = logging.getLogger(__name__)


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
    key = (name or "").replace(" ", "")
    if not key:
        return None
    for p in known:
        names = [n.replace(" ", "") for n in [p.name, *p.aliases]]
        if any(key == n or n in key or key in n for n in names):
            return p
    return None


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
        nodes.append(
            Node(
                place=place,
                open=to_min(place.open),
                close=to_min(place.close),
                stay=m.stay_min or place.stay_min,
                cost=place.cost,
                mandatory=True,
                fixed_start=to_min(m.start) if m.start else None,
            )
        )
    return nodes


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
    return [
        Node(
            place=p,
            open=to_min(p.open),
            close=to_min(p.close),
            stay=p.stay_min,
            cost=p.cost,
            taste=(sims[p.id] - lo) / span,
            similarity=sims[p.id],
        )
        for p in places
    ]


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


def make_course(req: PlanRequest) -> Course:
    known = load_anchors() + load_places()

    # ① 자연어 조건 파싱
    parsed, parser_used = parse_query(req.query, known)
    musts = _must_nodes(req, parsed, known)

    day_start = to_min(req.day_start or parsed.day_start or config.DEFAULT_DAY_START)
    day_end = to_min(req.day_end or parsed.day_end or config.DEFAULT_DAY_END)
    for m in musts:  # 고정 일정은 하루의 시간 축을 결정한다
        if m.fixed_start is not None:
            day_start = min(day_start, m.fixed_start)
            day_end = max(day_end, m.fixed_start + m.stay)
    if day_end <= day_start:
        raise PlanError("종료 시각이 시작 시각보다 빠릅니다.")

    c = Constraints(
        taste=parsed.taste or req.query,
        day_start=to_hm(day_start),
        day_end=to_hm(day_end),
        budget=req.budget if req.budget is not None else parsed.budget,
        companions=parsed.companions,
        weekday=parsed.weekday,
        avoid_categories=parsed.avoid_categories,
    )

    # ② 임베딩 취향 매칭
    index = _index()
    candidates = _candidate_nodes(c, index.similarities(c.taste), {m.id for m in musts})

    # ③ 제약 최적화
    planner_name = req.planner or config.DEFAULT_PLANNER
    planner = plan_ortools if planner_name == "ortools" else plan_greedy
    route = planner(musts, candidates, day_start, day_end, c.budget, travel_minutes)
    visits = schedule(route, day_start, day_end + config.LIMITS.overtime_grace_min, travel_minutes)
    if visits is None:
        raise PlanError("실행 가능한 코스를 만들지 못했습니다. 시간·예산 조건을 완화해 주세요.")

    # ④ 추천 이유 생성
    engine = {"parser": parser_used, "embedder": index.embedder.name, "planner": planner_name}
    course = _to_course(visits, c, engine)
    course.id = save_course(req, course)
    return course
