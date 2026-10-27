"""가게조사양식.xlsx -> DB. 팀원이 채운 엑셀의 '가게정보'·'체크리스트' 시트를 장소와 현장조사 체크리스트로 넣는다.

    python -m routefit.xlsx_import docs/가게조사양식.xlsx --dry-run   # 검사만 (DB 는 바뀌지 않는다)
    python -m routefit.xlsx_import docs/가게조사양식.xlsx             # DB 에 넣기 (같은 id 는 덮어씀)
    python -m routefit.xlsx_import 파일.xlsx --replace                # AI 추천 후보를 모두 지우고 이 파일로 바꿈(Must Visit 목적지는 그대로)

- 가게정보: 가게 이름이 비어 있는 줄은 건너뛴다. 틀린 줄은 어느 줄 어느 칸이 문제인지 알려 주고 나머지만 넣는다.
- 체크리스트: 채점자 한 줄 = 팀원 1명의 체크 (admin.put_checklist 와 같다). 넣은 뒤 3속성 점수를 다시 계산한다.
- 브레이크타임은 '15:00-17:00' 처럼 적힌 첫 구간만 넣는다('평일만' 같은 설명은 무시하고 매일 쉬는 것으로 본다).
- [참고] 열(라스트 오더·휴무 예외·메뉴·편의·네이버 링크·확인한 날짜·조사자·메모)과 도로명 주소(좌표를 못 구할 때만 씀)는 저장 칸이 없어 넣지 않는다.
- 서버가 켜져 있다면 끝난 뒤 재시작해야 반영된다(장소 목록을 캐시한다).
"""
import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Optional

from pydantic import ValidationError
from sqlalchemy import delete

from . import checklist, config, db
from .admin import _apply_checklist
from .models import Place

# 양식의 '목록' 시트와 같다
CATEGORY_CODES = {
    "식당": "food",
    "카페·디저트": "cafe",
    "전통시장": "market",
    "상점가": "shop",
    "명소·산책": "sight",
    "문화·전시": "culture",
    "야간 콘텐츠": "night",
}
TAG_COLUMNS = {"할 거리": "activity", "분위기": "mood", "공간": "setting", "어울리는 시간": "time", "어울리는 동행": "companions"}
WEEKDAYS = "월화수목금토일"
# (머리글 이름, 화면에 보일 이름). 한 줄에서 비어 있는 필수 칸을 한꺼번에 알려 주려고 쓴다
REQUIRED_CELLS = [
    ("유형", "유형"), ("지역", "지역"), ("영업시간", "영업시간"), ("머무는시간(분)", "머무는 시간"),
    ("1인예상지출(원)", "1인 예상 지출"), ("할거리", "할 거리"), ("분위기", "분위기"), ("공간", "공간"),
]
PLACEHOLDER = (35.1460, 126.9230)  # 동구 중심(임시). --placeholder 일 때만 쓴다
_YES = {"o", "ㅇ", "예", "네", "y", "yes", "true", "1", "✓", "v"}
_NO = {"x", "아니오", "아니요", "n", "no", "false", "0"}


@dataclass
class Report:
    places: list[str] = field(default_factory=list)
    sheets: int = 0
    errors: list[str] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    removed: int = 0


# ---------- 칸 값 읽기 ----------


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _header(v: Any) -> str:
    """'★가게 이름' / '대표 메뉴·가격\\n[참고]' -> 비교용 이름 (공백·★ 제거, [참고] 는 그대로 남아 무시된다)."""
    return re.sub(r"[\s★]", "", _text(v))


def _split(v: Any) -> list[str]:
    return [x.strip() for x in re.split(r"[,，、/;\n]+", _text(v)) if x.strip()]


def _hm(v: Any) -> Optional[str]:
    """11:00 / 25:00 / 엑셀 시간 값 -> 'HH:MM'. 비어 있으면 None, 읽을 수 없으면 ValueError."""
    if v is None or _text(v) == "":
        return None
    if isinstance(v, datetime):
        v = v.time()
    if isinstance(v, time):
        return f"{v.hour:02d}:{v.minute:02d}"
    if isinstance(v, (int, float)):  # 엑셀이 시각을 하루의 비율로 저장한 경우 (25:00 은 1.04)
        minutes = round(float(v) * 1440)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    m = re.fullmatch(r"(\d{1,2})\s*:\s*(\d{2})(?::\d{2})?", _text(v))
    if not m:
        raise ValueError(f"'{_text(v)}' 은(는) 시각이 아닙니다 (예: 11:00, 25:00)")
    return f"{int(m[1]):02d}:{m[2]}"


def _hours(v: Any) -> tuple[Optional[str], Optional[str]]:
    """'11:30-22:00' · '11:30 ~ 22:00' · '24시간' -> ('11:30', '22:00'). 닫는 시각이 여는 시각보다 이르면 다음 날로 본다(18:00-03:00 -> 27:00).
    비어 있으면 (None, None), 읽을 수 없으면 ValueError."""
    t = _text(v)
    if not t:
        return None, None
    if "24시간" in t or t in ("상시", "상시개방"):
        return "00:00", "24:00"
    parts = [p.strip() for p in re.split(r"\s*[-~～–—]\s*", t) if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"영업시간: '{t}' 은(는) 읽을 수 없습니다 (예: 11:30-22:00, 자정을 넘기면 25:00)")
    o, c = _hm(parts[0]), _hm(parts[1])
    if o is None or c is None:
        raise ValueError(f"영업시간: '{t}' 은(는) 읽을 수 없습니다")
    if c != "24:00" and int(c[:2]) * 60 + int(c[3:]) <= int(o[:2]) * 60 + int(o[3:]):
        c = f"{int(c[:2]) + 24:02d}:{c[3:]}"
    return o, c


def _break(v: Any) -> tuple[Optional[str], Optional[str]]:
    """'15:00-17:00' · '15:00-17:00 (평일). 주말은 없음' -> ('15:00', '17:00'). 비었거나 '없음' 이면 (None, None)."""
    t = _text(v)
    m = re.search(r"(\d{1,2}\s*:\s*\d{2})\s*[-~～–—]\s*(\d{1,2}\s*:\s*\d{2})", t)
    if m:
        return _hm(m[1]), _hm(m[2])
    if not t or "없" in t:
        return None, None
    raise ValueError(f"브레이크타임: '{t}' 은(는) 읽을 수 없습니다 (예: 15:00-17:00, 없으면 비움)")


def _blank(what: str):
    raise ValueError(f"{what}: 비어 있습니다")


def _int(v: Any, what: str) -> int:
    t = re.sub(r"[,\s원분]", "", _text(v))
    if not t:
        raise ValueError(f"{what}: 비어 있습니다")
    try:
        return int(float(t))
    except ValueError:
        raise ValueError(f"{what}: '{_text(v)}' 은(는) 숫자가 아닙니다")


def _float(v: Any, what: str) -> Optional[float]:
    if _text(v) == "":
        return None
    try:
        return float(_text(v))
    except ValueError:
        raise ValueError(f"{what}: '{_text(v)}' 은(는) 숫자가 아닙니다")


def _closed_days(v: Any) -> list[int]:
    t = _text(v)
    if not t or t in ("없음", "연중무휴", "무휴"):
        return []
    days = []
    for part in _split(t):
        if part[0] not in WEEKDAYS:
            raise ValueError(f"휴무 요일: '{part}' (월, 화, 수, 목, 금, 토, 일 중에서 쉼표로)")
        days.append(WEEKDAYS.index(part[0]))
    return days


def _yes_no(v: Any) -> Optional[bool]:
    t = _text(v).lower()
    if not t:
        return None
    if t in _YES:
        return True
    if t in _NO:
        return False
    raise ValueError(f"'{_text(v)}' 은(는) O/X 가 아닙니다")


def _rows(ws, header_row: int = 1) -> tuple[dict[str, int], list[tuple[int, list]]]:
    """(머리글 이름 -> 열 번호, [(엑셀 줄 번호, 칸 값들)]). 완전히 빈 줄은 뺀다."""
    cols = {}
    for i, cell in enumerate(next(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))):
        name = _header(cell)
        if name and name not in cols:
            cols[name] = i
    out = []
    for n, values in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
        if any(_text(v) for v in values):
            out.append((n, list(values)))
    return cols, out


def _geocode(address: str) -> Optional[tuple[float, float]]:
    """카카오 주소 검색 -> (위도, 경도). KAKAO_REST_API_KEY 가 있어야 한다. 못 찾으면 None."""
    import httpx

    def search(query: str) -> Optional[tuple[float, float]]:
        r = httpx.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": query},
            headers={"Authorization": f"KakaoAK {config.KAKAO_REST_API_KEY}"},
            timeout=10,
        )
        r.raise_for_status()
        docs = r.json().get("documents", [])
        return (float(docs[0]["y"]), float(docs[0]["x"])) if docs else None

    found = search(address)
    if found:
        return found
    # '1, 2층', '101,102호' 처럼 도로명 번호 뒤에 붙은 층·호 표기가 있으면 카카오가 못 찾는다. 번호까지만 다시 찾는다.
    m = re.match(r".*?(?:로|길)(?:\d+번길)?\s*\d+(?:-\d+)?", address)
    return search(m.group(0)) if m and m.group(0) != address else None


# ---------- 가게정보 시트 ----------


def parse_stores(ws, report: Report, geocode: bool = False, placeholder: bool = False) -> dict[str, Place]:
    cols, rows = _rows(ws)
    required = ["가게이름", "유형", "지역", "영업시간", "머무는시간(분)", "1인예상지출(원)", "할거리", "분위기", "공간"]
    missing = [c for c in required if c not in cols]
    if missing:
        raise SystemExit(f"'가게정보' 시트의 머리글을 찾을 수 없습니다: {', '.join(missing)} (양식의 1행을 고치지 마세요)")
    get = lambda row, name: row[cols[name]] if name in cols and cols[name] < len(row) else None  # noqa: E731

    stores: dict[str, Place] = {}
    for n, row in rows:
        name = _text(get(row, "가게이름"))
        sid = _text(get(row, "id(수정금지)"))
        if not name or sid == "자동 번호":  # 아직 안 채운 줄과 2행 안내문
            continue
        label = f"가게정보 {n}행 '{name}'"
        try:
            if not re.fullmatch(r"[a-z0-9_]+", sid):
                raise ValueError(f"id(A열) '{sid}' 가 비었거나 형식이 틀립니다 (s_001 처럼 소문자·숫자·_ 만)")
            if sid in stores:
                raise ValueError(f"id '{sid}' 가 위 줄과 겹칩니다")
            blanks = [label for key, label in REQUIRED_CELLS if not _text(get(row, key))]
            if blanks:
                raise ValueError(f"필수 칸이 비어 있습니다: {', '.join(blanks)}")
            cat = _text(get(row, "유형"))
            if cat not in CATEGORY_CODES:
                raise ValueError(f"유형: '{cat}' 은(는) 목록에 없습니다 ({', '.join(CATEGORY_CODES)})")
            lat, lng = _float(get(row, "위도"), "위도"), _float(get(row, "경도"), "경도")
            if lat is None or lng is None:
                address = _text(get(row, "도로명주소"))
                found = _geocode(address) if geocode and address and config.KAKAO_REST_API_KEY else None
                if found:
                    lat, lng = found
                elif placeholder:
                    lat, lng = PLACEHOLDER
                    report.placeholders.append(f"{sid} {name}")
                else:
                    raise ValueError("좌표(위도·경도)가 없습니다. 칸에 적거나, --geocode(카카오 키 필요) / --placeholder 를 쓰세요")
            tags = {key: _split(get(row, _header(col))) for col, key in TAG_COLUMNS.items()}
            opens, closes = _hours(get(row, "영업시간"))
            # 예전 양식은 머리글이 '브레이크타임 [참고]'
            break_start, break_end = _break(get(row, "브레이크타임") or get(row, "브레이크타임[참고]"))
            place = Place(
                id=sid,
                name=name,
                category=CATEGORY_CODES[cat],
                area=_text(get(row, "지역")),
                lat=lat,
                lng=lng,
                description=_text(get(row, "한줄소개")),
                tags=tags,
                aliases=_split(get(row, "별칭")),
                open=opens or _blank("영업시간"),
                close=closes or _blank("영업시간"),
                break_start=break_start,
                break_end=break_end,
                closed_days=_closed_days(get(row, "휴무요일")),
                stay_min=_int(get(row, "머무는시간(분)"), "머무는 시간"),
                cost=_int(get(row, "1인예상지출(원)"), "1인 예상 지출"),
            )
        except ValidationError as e:
            report.errors.append(f"{label}: " + "; ".join(f"{'.'.join(map(str, x['loc']))} {x['msg']}" for x in e.errors()))
        except ValueError as e:
            report.errors.append(f"{label}: {e}")
        else:
            stores[sid] = place
    return stores


# ---------- 체크리스트 시트 ----------


def _item_keys(cols: dict[str, int]) -> dict[str, int]:
    """체크리스트 시트 머리글('[광주다움]\\n5·18 …') -> checklist.json 항목 key -> 열 번호."""
    out = {}
    for item in checklist.definition()["items"]:
        if item.get("auto"):
            continue
        want = re.sub(r"\s", "", item["label"])
        for header, i in cols.items():
            if header.endswith(want):  # 앞의 '[속성]' 은 떼고 비교
                out[item["key"]] = i
    return out


def parse_checklists(ws, known_ids: set[str], report: Report) -> list[tuple[str, str, dict[str, bool], dict[str, str]]]:
    cols, rows = _rows(ws)
    id_col, rater_col = cols.get("가게id"), cols.get("채점자")
    evidence_col = next((i for h, i in cols.items() if h.startswith("근거")), None)
    keys = _item_keys(cols)
    manual = checklist.manual_keys()
    if id_col is None or rater_col is None or set(keys) != set(manual):
        raise SystemExit(
            "'체크리스트' 시트의 머리글이 data/checklist.json 과 맞지 않습니다: "
            f"찾지 못한 항목 {sorted(set(manual) - set(keys))}"
        )
    out = []
    for n, row in rows:
        cell = lambda i: row[i] if i is not None and i < len(row) else None  # noqa: E731
        sid, rater = _text(cell(id_col)), _text(cell(rater_col))
        marks = {k: cell(i) for k, i in keys.items()}
        if not sid or sid.startswith("(") or "고르기" in sid:  # 2행 안내문 등
            continue
        if not rater and not any(_text(v) for v in marks.values()):  # id 만 미리 채워 둔 줄
            continue
        label = f"체크리스트 {n}행 {sid}"
        try:
            if sid not in known_ids:
                raise ValueError(f"가게정보에 없는 id 입니다 (가게정보에서 오류가 났거나 id 를 잘못 적음)")
            if not rater:
                raise ValueError("채점자 이름이 없습니다")
            checks, blank = {}, []
            for k, v in marks.items():
                value = _yes_no(v)
                if value is None:
                    blank.append(k)
                checks[k] = bool(value)
            if blank:
                raise ValueError(f"O/X 가 빈 항목이 {len(blank)}개 있습니다: {', '.join(blank)}")
            note = _text(cell(evidence_col))[:300]
            evidence = {k: note for k in checks} if note else {}
        except ValueError as e:
            report.errors.append(f"{label}: {e}")
        else:
            out.append((sid, rater, checks, evidence))
    return out


# ---------- DB 에 넣기 ----------

# 현장조사로 정해지는 값이라 엑셀의 가게정보가 덮어쓰지 않는다
_KEEP = {"gwangju_ness", "stay_inducement", "commerce_link", "is_local_commerce", "verified"}


def load(path: str, dry_run: bool = False, geocode: bool = False, placeholder: bool = False, replace: bool = False) -> Report:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    for sheet in ("가게정보", "체크리스트"):
        if sheet not in wb.sheetnames:
            raise SystemExit(f"'{sheet}' 시트가 없습니다. 시트 이름: {wb.sheetnames}")
    report = Report()
    stores = parse_stores(wb["가게정보"], report, geocode, placeholder)

    with db.session() as s:
        if replace:
            if report.errors:  # 지운 뒤 일부만 들어가는 일이 없도록, 고칠 곳이 남아 있으면 아무것도 바꾸지 않는다
                s.rollback()
                return report
            ids = [r.id for r in s.query(db.PlaceRow.id).filter(db.PlaceRow.kind == "candidate")]
            s.execute(delete(db.ChecklistRow).where(db.ChecklistRow.place_id.in_(ids)))
            s.execute(delete(db.TravelRow).where(db.TravelRow.from_id.in_(ids) | db.TravelRow.to_id.in_(ids)))
            s.execute(delete(db.PlaceRow).where(db.PlaceRow.id.in_(ids)))
            s.flush()
            report.removed = len(ids)
        existing = {r.id: r for r in s.query(db.PlaceRow).filter(db.PlaceRow.id.in_(list(stores) or [""]))}
        for sid, place in list(stores.items()):
            row = existing.get(sid)
            if row is not None and row.kind != "candidate":
                report.errors.append(f"가게정보 id '{sid}': 이미 Must Visit 목적지(anchor)가 쓰는 id 입니다")
                del stores[sid]
        known = set(stores) | {r.id for r in s.query(db.PlaceRow.id).filter(db.PlaceRow.kind == "candidate")}
        sheets = parse_checklists(wb["체크리스트"], known, report)

        for sid, place in stores.items():
            data = place.model_dump()
            row = existing.get(sid)
            if row is None:
                s.add(db.place_row(data, "candidate"))
            else:
                data["open_time"], data["close_time"] = data.pop("open"), data.pop("close")
                for key, value in data.items():
                    if key != "id" and key not in _KEEP:
                        setattr(row, key, value)
            report.places.append(f"{sid} {place.name}")
        s.flush()
        for sid, rater, checks, evidence in sheets:
            s.merge(db.ChecklistRow(place_id=sid, rater=rater, checks=checks, evidence=evidence))
        s.flush()
        for sid in {sid for sid, *_ in sheets}:  # 체크리스트가 있는 가게만 3속성 점수를 다시 계산
            _apply_checklist(s, s.get(db.PlaceRow, sid))
        report.sheets = len(sheets)
        s.rollback() if dry_run else s.commit()
    return report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="가게조사양식.xlsx 를 DB 에 넣는다")
    ap.add_argument("xlsx")
    ap.add_argument("--dry-run", action="store_true", help="검사만 하고 DB 는 바꾸지 않는다")
    ap.add_argument("--geocode", action="store_true", help="좌표가 빈 줄은 도로명 주소로 카카오에서 찾는다 (KAKAO_REST_API_KEY)")
    ap.add_argument("--placeholder", action="store_true", help="좌표가 빈 줄은 동구 중심의 임시 좌표로 넣는다 (나중에 관리 화면에서 고칠 것)")
    ap.add_argument("--replace", action="store_true", help="AI 추천 후보를 모두 지우고 이 파일로 바꾼다(Must Visit 목적지는 그대로). 고칠 곳이 있으면 아무것도 바꾸지 않는다")
    args = ap.parse_args(argv)

    r = load(args.xlsx, args.dry_run, args.geocode, args.placeholder, args.replace)
    if args.replace and r.errors:
        print("고쳐야 할 곳이 있어 아무것도 바꾸지 않았습니다 (--replace 는 오류가 없을 때만 지웁니다):")
        for e in r.errors:
            print("  -", e)
        return 1
    verb = "넣을 수 있음" if args.dry_run else "넣음"
    if args.replace:
        print(f"기존 AI 추천 후보 {r.removed}곳을 {'지울 예정' if args.dry_run else '지움'}")
    print(f"가게 {len(r.places)}곳 {verb}, 체크리스트 {r.sheets}줄 {verb}")
    for p in r.placeholders:
        print(f"  임시 좌표: {p}  <- 관리 화면에서 지도를 눌러 고치세요")
    if r.errors:
        print(f"\n고쳐야 할 곳 {len(r.errors)}개 (이 줄들은 넣지 않았습니다):")
        for e in r.errors:
            print("  -", e)
    if not args.dry_run and r.places:
        print("\n서버가 켜져 있다면 재시작하세요. 팀 공유용으로 남기려면 /api/admin/export 결과를 data/*.json 에 커밋합니다.")
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
