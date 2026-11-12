"""DB -> 가게조사 엑셀. 장소 관리 화면에서 고치거나 더한 장소를 엑셀에도 남길 때 쓴다(xlsx_import 의 반대 방향).

    python -m routefit.xlsx_export docs/가게조사_입력본_초안채움.xlsx            # 이 파일에 DB 내용을 합쳐 덮어쓴다
    python -m routefit.xlsx_export docs/기존.xlsx -o 새파일.xlsx                 # 다른 이름으로 저장
    python -m routefit.xlsx_export -o 새양식.xlsx                                # 기존 파일 없이 새 양식으로

화면에서는 장소 관리의 '엑셀 내보내기' 버튼이 같은 일을 한다(/api/admin/export.xlsx).

합치는 규칙
- 가게정보: AI 추천 후보(Must Visit 목적지는 빼고)만 쓴다. id 가 같은 줄이 있으면 DB 에 저장되는 칸(이름·유형·지역·좌표·
  영업시간·브레이크·휴무·머무는 시간·지출·태그·별칭·한줄 소개)만 DB 값으로 바꾸고, [참고] 칸(메뉴·편의·링크·메모 등)과
  도로명 주소는 그대로 둔다. 없으면 빈 줄(가게 이름이 빈 첫 줄)에 새로 쓴다.
- DB 에 없는 엑셀 줄(아직 못 넣은 가게, 화면에서 지운 가게)은 지우지 않는다.
- 체크리스트: (가게 id, 채점자)가 같은 줄은 O/X 를 DB 값으로 바꾸고, 없으면 빈 줄에 더한다.
"""
import argparse
import io
import sys
from typing import Optional

from sqlalchemy import select

from . import checklist, db, xlsx_import, xlsx_template
from .data import to_place
from .models import CATEGORY_KO, Place

WEEKDAYS = "월화수목금토일"
# 엑셀 칸 키 -> 이전 양식의 다른 머리글 (예전 양식은 브레이크타임이 [참고] 칸이었다)
_OLD_HEADERS = {"break": ["브레이크타임[참고]"]}


def place_cells(p: Place) -> dict:
    """Place -> 가게정보 시트의 {칸 키: 값}. DB 에 저장되는 칸만."""
    tags = p.tags or {}
    join = lambda vs: ", ".join(vs)  # noqa: E731
    return {
        "id": p.id,
        "name": p.name,
        "category": CATEGORY_KO.get(p.category, p.category),
        "area": p.area,
        "lat": p.lat,
        "lng": p.lng,
        "hours": f"{p.open}-{p.close}",
        "break": f"{p.break_start}-{p.break_end}" if p.break_start else None,
        "closed": join(WEEKDAYS[d] for d in p.closed_days) or None,
        "stay": p.stay_min,
        "cost": p.cost,
        "activity": join(tags.get("activity", [])) or None,
        "mood": join(tags.get("mood", [])) or None,
        "setting": join(tags.get("setting", [])) or None,
        "time": join(tags.get("time", [])) or None,
        "companions": join(tags.get("companions", [])) or None,
        "aliases": join(p.aliases) or None,
        "desc": p.description or None,
    }


def _columns(ws) -> dict[str, int]:
    cols = xlsx_template._columns(ws)
    for key, olds in _OLD_HEADERS.items():
        if key not in cols:
            for c in range(1, ws.max_column + 1):
                if xlsx_template._norm(ws.cell(1, c).value) in olds:
                    cols[key] = c
    return cols


def _merge_places(ws, places: list[Place]) -> tuple[int, int]:
    cols = _columns(ws)
    if "id" not in cols or "name" not in cols:
        raise ValueError("'가게정보' 시트의 머리글(id·가게 이름)을 찾을 수 없습니다. 양식의 1행을 고치지 않은 파일을 넣어 주세요.")
    last = max(ws.max_row, 2 + xlsx_template.MAX_ROWS)
    filled = lambda r: bool(xlsx_import._text(ws.cell(r, cols["name"]).value))  # noqa: E731
    by_id = {xlsx_import._text(ws.cell(r, cols["id"]).value): r for r in range(3, last + 1) if filled(r)}
    updated = added = 0
    row = 3
    for p in places:
        r = by_id.get(p.id)
        if r is None:
            while filled(row):
                row += 1
            r, added = row, added + 1
        else:
            updated += 1
        for key, value in place_cells(p).items():
            if key in cols:
                ws.cell(r, cols[key]).value = value
    return updated, added


def _merge_checklists(ws, sheets: list[tuple[str, str, dict, dict]]) -> int:
    cols, _ = xlsx_import._rows(ws)
    id_col, rater_col = cols.get("가게id"), cols.get("채점자")
    items = xlsx_import._item_keys(cols)
    if id_col is None or rater_col is None or set(items) != set(checklist.manual_keys()):
        raise ValueError("'체크리스트' 시트의 머리글이 지금 체크리스트 항목과 맞지 않습니다.")
    evidence_col = next((i for h, i in cols.items() if h.startswith("근거")), None)
    text = lambda r, c: xlsx_import._text(ws.cell(r, c + 1).value)  # noqa: E731
    last = max(ws.max_row, 2 + xlsx_template.MAX_SHEETS)
    used = {(text(r, id_col), text(r, rater_col)): r for r in range(3, last + 1) if text(r, rater_col)}
    row, n = 3, 0
    for sid, rater, checks, evidence in sheets:
        r = used.get((sid, rater))
        if r is None:
            while text(row, rater_col) or any(text(row, i) for i in items.values()):
                row += 1
            r = row
            used[(sid, rater)] = r
        ws.cell(r, id_col + 1).value = sid
        ws.cell(r, rater_col + 1).value = rater
        for key, i in items.items():
            ws.cell(r, i + 1).value = "O" if checks.get(key) else "X"
        notes = list(dict.fromkeys(v for v in (evidence or {}).values() if v))
        if evidence_col is not None and notes:
            ws.cell(r, evidence_col + 1).value = " / ".join(notes)
        n += 1
    return n


def export(base: Optional[bytes] = None) -> tuple[bytes, dict]:
    """DB 의 AI 추천 후보와 체크리스트를 엑셀로. base(기존 엑셀 내용)가 있으면 거기에 합친다.
    돌려주는 값: (xlsx 바이트, {"updated": 바꾼 가게 수, "added": 더한 가게 수, "checklists": 쓴 체크리스트 줄 수})."""
    import openpyxl

    with db.session() as s:
        rows = s.scalars(select(db.PlaceRow).where(db.PlaceRow.kind == "candidate").order_by(db.PlaceRow.id)).all()
        places = [to_place(r) for r in rows]
        ids = {p.id for p in places}
        sheets = [
            (c.place_id, c.rater, c.checks or {}, c.evidence or {})
            for c in s.scalars(select(db.ChecklistRow).order_by(db.ChecklistRow.place_id, db.ChecklistRow.rater))
            if c.place_id in ids
        ]

    if base:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(base))
        except Exception:
            raise ValueError("엑셀(.xlsx) 파일을 읽을 수 없습니다.")
        if "가게정보" not in wb.sheetnames or "체크리스트" not in wb.sheetnames:
            raise ValueError("가게조사 양식이 아닙니다('가게정보'·'체크리스트' 시트가 없습니다).")
    else:
        buf = io.BytesIO()
        xlsx_template.build(buf)
        wb = openpyxl.load_workbook(io.BytesIO(buf.getvalue()))

    used = sum(1 for r in range(3, wb["가게정보"].max_row + 1) if wb["가게정보"].cell(r, 2).value)
    if used + len(places) > xlsx_template.MAX_ROWS * 4:  # 비정상적으로 커지는 것만 막는다
        raise ValueError("가게가 너무 많습니다.")
    updated, added = _merge_places(wb["가게정보"], places)
    n_sheets = _merge_checklists(wb["체크리스트"], sheets)
    xlsx_template.add_dropdowns(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), {"updated": updated, "added": added, "checklists": n_sheets}


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="DB 의 장소·체크리스트를 가게조사 엑셀로 내보낸다")
    ap.add_argument("base", nargs="?", help="합칠 기존 엑셀(없으면 새 양식)")
    ap.add_argument("-o", "--out", help="저장할 파일(없으면 base 를 덮어씀)")
    args = ap.parse_args(argv)
    out = args.out or args.base
    if not out:
        ap.error("기존 엑셀이나 -o 저장할 파일 중 하나는 있어야 합니다")
    base = open(args.base, "rb").read() if args.base else None
    try:
        data, info = export(base)
    except ValueError as e:
        sys.exit(str(e))
    with open(out, "wb") as f:
        f.write(data)
    print(f"{out}: 가게 {info['updated']}곳 갱신, {info['added']}곳 추가, 체크리스트 {info['checklists']}줄")


if __name__ == "__main__":
    main()
