"""관리자 API: 현장조사 데이터 입력. ROUTEFIT_ADMIN_TOKEN 을 설정하면 X-Admin-Token 헤더가 필요하다."""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import func, select

from . import config, db
from .data import invalidate, to_place
from .models import PlaceKind, PlaceRecord, Rating, RatingIn, TravelTime


def require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    if config.ADMIN_TOKEN and not secrets.compare_digest(x_admin_token or "", config.ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다 (X-Admin-Token).")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _record(s, row: db.PlaceRow) -> PlaceRecord:
    n = s.scalar(select(func.count()).select_from(db.RatingRow).where(db.RatingRow.place_id == row.id))
    return PlaceRecord(**to_place(row).model_dump(), kind=row.kind, updated_at=row.updated_at, n_ratings=n)


def _get_row(s, place_id: str) -> db.PlaceRow:
    row = s.get(db.PlaceRow, place_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"장소 '{place_id}' 이(가) 없습니다.")
    return row


def _apply(row: db.PlaceRow, rec: PlaceRecord) -> None:
    data = rec.model_dump(exclude={"id", "updated_at", "n_ratings"})
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


# ---------- 현장조사 채점 ----------


@router.get("/places/{place_id}/ratings", response_model=list[Rating])
def list_ratings(place_id: str):
    with db.session() as s:
        _get_row(s, place_id)
        rows = s.scalars(select(db.RatingRow).where(db.RatingRow.place_id == place_id).order_by(db.RatingRow.rater))
        return [Rating(**{c: getattr(r, c) for c in Rating.model_fields}) for r in rows]


@router.put("/places/{place_id}/ratings", response_model=PlaceRecord)
def put_rating(place_id: str, rating: RatingIn):
    """팀원 1명의 채점을 저장(같은 rater 면 덮어씀)하고, 장소의 3속성을 채점 평균으로 갱신한다."""
    with db.session() as s:
        row = _get_row(s, place_id)
        existing = s.get(db.RatingRow, (place_id, rating.rater))
        if existing is None:
            s.add(db.RatingRow(place_id=place_id, **rating.model_dump()))
        else:
            for key, value in rating.model_dump().items():
                setattr(existing, key, value)
        s.flush()
        _average_ratings(s, row)
        s.commit()
        invalidate()
        return _record(s, row)


@router.delete("/places/{place_id}/ratings/{rater}", response_model=PlaceRecord)
def delete_rating(place_id: str, rater: str):
    with db.session() as s:
        row = _get_row(s, place_id)
        existing = s.get(db.RatingRow, (place_id, rater))
        if existing is None:
            raise HTTPException(status_code=404, detail=f"'{rater}' 의 채점이 없습니다.")
        s.delete(existing)
        s.flush()
        _average_ratings(s, row)  # 남은 채점이 없으면 마지막 평균값을 그대로 둔다
        s.commit()
        invalidate()
        return _record(s, row)


def _average_ratings(s, row: db.PlaceRow) -> None:
    R = db.RatingRow
    avg = s.execute(
        select(func.avg(R.gwangju_ness), func.avg(R.stay_inducement), func.avg(R.commerce_link)).where(
            R.place_id == row.id
        )
    ).one()
    if avg[0] is not None:
        row.gwangju_ness, row.stay_inducement, row.commerce_link = (round(float(v), 2) for v in avg)


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
    """현재 DB 의 장소를 data/places.json · anchors.json 형식으로 내보낸다(저장소에 커밋할 때)."""
    with db.session() as s:
        rows = s.scalars(select(db.PlaceRow).order_by(db.PlaceRow.id)).all()
        travel = {f"{r.from_id}|{r.to_id}": r.minutes for r in s.scalars(select(db.TravelRow))}
    out: dict = {"places": [], "anchors": [], "travel_matrix": travel}
    for r in rows:
        out["places" if r.kind == "candidate" else "anchors"].append(to_place(r).model_dump())
    return out

