"""관리자 API: 현장조사 데이터 입력. ROUTEFIT_ADMIN_TOKEN 을 설정하면 X-Admin-Token 헤더가 필요하다."""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import ValidationError
from sqlalchemy import func, select

from . import checklist, config, courses, db
from . import tags as tag_vocab
from .data import invalidate, to_place
from .models import ChecklistIn, ChecklistSheet, ChecklistView, Feedback, PlaceKind, PlaceRecord, TravelTime


def require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    if config.ADMIN_TOKEN and not secrets.compare_digest(x_admin_token or "", config.ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다 (X-Admin-Token).")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _record(s, row: db.PlaceRow) -> PlaceRecord:
    n = s.scalar(select(func.count()).select_from(db.ChecklistRow).where(db.ChecklistRow.place_id == row.id))
    place = to_place(row)
    return PlaceRecord(
        **place.model_dump(),
        kind=row.kind,
        updated_at=row.updated_at,
        n_ratings=n,
        missing_tags=tag_vocab.missing_required(place.tags) if row.kind == "candidate" else [],
        local_contribution=round(place.local_score, 3),
    )


def _get_row(s, place_id: str) -> db.PlaceRow:
    row = s.get(db.PlaceRow, place_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"장소 '{place_id}' 이(가) 없습니다.")
    return row


def _apply(row: db.PlaceRow, rec: PlaceRecord) -> None:
    data = rec.model_dump(exclude={"id", "updated_at", "n_ratings", "missing_tags", "local_contribution"})
    data["open_time"] = data.pop("open")
    data["close_time"] = data.pop("close")
    for key, value in data.items():
        setattr(row, key, value)


# ---------- 장소 ----------


@router.get("/places", response_model=list[PlaceRecord])
def list_places(kind: Optional[PlaceKind] = None, verified: Optional[bool] = None):
    with db.session() as s:
        q = select(db.PlaceRow).order_by(db.PlaceRow.kind, db.PlaceRow.id)
        if kind is not None:
            q = q.where(db.PlaceRow.kind == kind)
        if verified is not None:
            q = q.where(db.PlaceRow.verified == verified)
        return [_record(s, r) for r in s.scalars(q)]


@router.get("/places/{place_id}", response_model=PlaceRecord)
def get_place(place_id: str):
    with db.session() as s:
        return _record(s, _get_row(s, place_id))


@router.post("/places", response_model=PlaceRecord, status_code=201)
def create_place(rec: PlaceRecord):
    with db.session() as s:
        if s.get(db.PlaceRow, rec.id) is not None:
            raise HTTPException(status_code=409, detail=f"장소 '{rec.id}' 이(가) 이미 있습니다.")
        row = db.PlaceRow(id=rec.id)
        _apply(row, rec)
        s.add(row)
        s.commit()
        invalidate()
        return _record(s, row)


@router.put("/places/{place_id}", response_model=PlaceRecord)
def replace_place(place_id: str, rec: PlaceRecord):
    if rec.id != place_id:
        raise HTTPException(status_code=422, detail="경로의 id 와 본문의 id 가 다릅니다.")
    with db.session() as s:
        row = _get_row(s, place_id)
        _apply(row, rec)
        _apply_checklist(s, row)  # 체류시간·태그·영업시간·지출이 자동 항목에 쓰인다
        s.commit()
        invalidate()
        return _record(s, row)


@router.patch("/places/{place_id}", response_model=PlaceRecord)
def update_place(place_id: str, changes: dict):
    """일부 필드만 수정. 예: {"verified": true, "cost": 12000}"""
    with db.session() as s:
        row = _get_row(s, place_id)
        current = _record(s, row).model_dump()
        try:
            rec = PlaceRecord(**{**current, **changes, "id": place_id})
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False, include_input=False))
        _apply(row, rec)
        _apply_checklist(s, row)  # 체류시간·태그·영업시간·지출이 자동 항목에 쓰인다
        s.commit()
        invalidate()
        return _record(s, row)


@router.delete("/places/{place_id}", status_code=204)
def delete_place(place_id: str):
    with db.session() as s:
        s.delete(_get_row(s, place_id))
        s.commit()
    invalidate()
    return Response(status_code=204)


# ---------- 현장조사 체크리스트 ----------


def _sheets(s, place_id: str) -> list[db.ChecklistRow]:
    C = db.ChecklistRow
    return list(s.scalars(select(C).where(C.place_id == place_id).order_by(C.rater)))


def _apply_checklist(s, row: db.PlaceRow) -> None:
    """체크리스트가 있으면 3속성 점수·지역상권 여부를 체크리스트로 다시 계산한다.
    없으면 직접 입력한 값을 그대로 둔다(마지막 체크리스트를 지워도 마지막 계산값이 남는다)."""
    sheets = [{"rater": c.rater, "checks": c.checks} for c in _sheets(s, row.id)]
    if not sheets:
        return
    result = checklist.evaluate(to_place(row), sheets)
    for key, score in result["scores"].items():
        setattr(row, key, score)
    row.is_local_commerce = result["is_local_commerce"]


@router.get("/places/{place_id}/checklists", response_model=ChecklistView)
def get_checklists(place_id: str):
    with db.session() as s:
        row = _get_row(s, place_id)
        rows = _sheets(s, place_id)
        sheets = [ChecklistSheet(rater=c.rater, checks=c.checks, evidence=c.evidence or {}, updated_at=c.updated_at) for c in rows]
        evaluation = checklist.evaluate(to_place(row), [{"rater": c.rater, "checks": c.checks} for c in rows])
        return ChecklistView(sheets=sheets, evaluation=evaluation)


@router.put("/places/{place_id}/checklists", response_model=PlaceRecord)
def put_checklist(place_id: str, sheet: ChecklistIn):
    """팀원 1명의 체크리스트를 저장(같은 rater 면 덮어씀)하고 장소 점수를 다시 계산한다."""
    try:
        checks = checklist.validate_checks(sheet.checks)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    unknown = set(sheet.evidence) - set(checks)
    if unknown:
        raise HTTPException(status_code=422, detail=f"근거를 남길 수 없는 항목: {', '.join(sorted(unknown))}")
    with db.session() as s:
        row = _get_row(s, place_id)
        s.merge(db.ChecklistRow(place_id=place_id, rater=sheet.rater, checks=checks, evidence=sheet.evidence))
        s.flush()
        _apply_checklist(s, row)
        s.commit()
        invalidate()
        return _record(s, row)


@router.delete("/places/{place_id}/checklists/{rater}", response_model=PlaceRecord)
def delete_checklist(place_id: str, rater: str):
    with db.session() as s:
        row = _get_row(s, place_id)
        existing = s.get(db.ChecklistRow, (place_id, rater))
        if existing is None:
            raise HTTPException(status_code=404, detail=f"'{rater}' 의 체크리스트가 없습니다.")
        s.delete(existing)
        s.flush()
        _apply_checklist(s, row)
        s.commit()
        invalidate()
        return _record(s, row)


# ---------- 이동시간 ----------


@router.get("/travel-times", response_model=list[TravelTime])
def list_travel_times():
    with db.session() as s:
        return [
            TravelTime(from_id=r.from_id, to_id=r.to_id, minutes=r.minutes, mode=r.mode)
            for r in s.scalars(select(db.TravelRow).order_by(db.TravelRow.from_id, db.TravelRow.to_id))
        ]


@router.put("/travel-times", response_model=dict)
def put_travel_times(items: list[TravelTime]):
    """지도 API 로 구한 이동시간을 한꺼번에 저장(있으면 덮어씀)."""
    with db.session() as s:
        known = set(s.scalars(select(db.PlaceRow.id)))
        unknown = sorted({i for t in items for i in (t.from_id, t.to_id)} - known)
        if unknown:
            raise HTTPException(status_code=422, detail=f"없는 장소 id: {unknown}")
        for t in items:
            s.merge(db.TravelRow(**t.model_dump()))
        s.commit()
    invalidate()
    return {"saved": len(items)}


# ---------- 피드백 ----------


@router.get("/feedback", response_model=list[Feedback])
def list_feedback(limit: int = Query(default=50, ge=1, le=500)):
    """최근 별점·한줄평. 사용자가 쓴 글이라 공개 API 가 아닌 관리자 API 로 둔다."""
    return courses.recent_feedback(limit)


# ---------- 가져오기 / 내보내기 ----------


@router.post("/import", response_model=dict)
def import_json():
    """장소·이동시간을 data/*.json 기준으로 초기화한다. 관리자 화면에서 고친 내용과 채점은 지워진다."""
    with db.session() as s:
        counts = db.seed(s)
    invalidate()
    return counts


@router.get("/export", response_model=dict)
def export_json():
    """현재 DB 의 장소를 data/places.json · anchors.json · travel_matrix.json · checklists.json 형식으로 내보낸다(저장소에 커밋할 때)."""
    with db.session() as s:
        rows = s.scalars(select(db.PlaceRow).order_by(db.PlaceRow.id)).all()
        # 구간마다 분과 이동 수단(transit·car, 모르면 null). 수단이 있어야 다시 채울 때 같은 구간을 또 부르지 않는다.
        travel = {
            f"{r.from_id}|{r.to_id}": {"minutes": r.minutes, "mode": r.mode}
            for r in s.scalars(select(db.TravelRow).order_by(db.TravelRow.from_id, db.TravelRow.to_id))
        }
        sheets: dict[str, list] = {}
        for c in s.scalars(select(db.ChecklistRow).order_by(db.ChecklistRow.place_id, db.ChecklistRow.rater)):
            sheets.setdefault(c.place_id, []).append({"rater": c.rater, "checks": c.checks, "evidence": c.evidence or {}})
    out: dict = {"places": [], "anchors": [], "travel_matrix": travel, "checklists": sheets}
    for r in rows:
        out["places" if r.kind == "candidate" else "anchors"].append(to_place(r).model_dump())
    return out

