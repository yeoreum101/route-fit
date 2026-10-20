import shutil
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import delete, select

from routefit import db, xlsx_import
from routefit.data import invalidate

FORM = Path(__file__).resolve().parent.parent / "docs" / "가게조사양식.xlsx"

GOOD = {
    "A": "store_001", "B": "테스트 국밥", "C": "식당", "D": "동구 동명동", "F": 35.1495, "G": 126.9285,
    "H": "11:00", "I": "21:00", "J": "월", "K": 60, "L": "9,000", "P": "식사, 사진", "Q": "서민적, 활기찬",
    "R": "실내", "S": "오후, 저녁", "T": "혼자, 친구", "U": "테스트국밥집", "V": "2008년 개업.",
}
BAD = {**GOOD, "A": "store_002", "B": "잘못된 카페", "C": "술집", "H": "열한시", "P": "없는태그", "R": "실내, 실외"}
NO_COORDS = {**GOOD, "A": "store_003", "B": "좌표 없는 가게", "F": None, "G": None}


@pytest.fixture
def filled(tmp_path):
    path = tmp_path / "filled.xlsx"
    shutil.copy(FORM, path)
    wb = openpyxl.load_workbook(path)
    ws = wb["가게정보"]
    for i, data in enumerate((GOOD, BAD, NO_COORDS), start=3):
        for col, value in data.items():
            ws[f"{col}{i}"] = value
    sheet = wb["체크리스트"]
    marks = ["O", "x", "X", "o", "O", "O", "X", "O"]  # 수동 항목 8개
    for r, (rater, m) in enumerate((("홍길동", marks), ("김철수", ["X"] * 8)), start=3):
        sheet[f"A{r}"], sheet[f"C{r}"] = "store_001", rater
        for c, v in zip("DEFGHIJK", m):
            sheet[f"{c}{r}"] = v
        sheet[f"L{r}"] = "현장 확인"
    sheet["A5"], sheet["C5"] = "store_999", "홍길동"  # 가게정보에 없는 id
    wb.save(path)
    return path


def test_dry_run_reports_each_problem_without_writing(filled):
    report = xlsx_import.load(str(filled), dry_run=True)
    assert report.places == ["store_001 테스트 국밥"]
    text = "\n".join(report.errors)
    assert "가게정보 4행 '잘못된 카페'" in text and "유형" in text and "술집" in text
    assert "가게정보 5행 '좌표 없는 가게'" in text and "좌표" in text
    assert "체크리스트 5행 store_999" in text
    with db.session() as s:
        assert s.get(db.PlaceRow, "store_001") is None  # dry-run 은 DB 를 바꾸지 않는다


def test_import_writes_places_checklists_and_scores(filled):
    try:
        report = xlsx_import.load(str(filled), placeholder=True)
        assert report.placeholders == ["store_003 좌표 없는 가게"]
        assert report.sheets == 2
        with db.session() as s:
            row = s.get(db.PlaceRow, "store_001")
            assert (row.name, row.category, row.open_time, row.close_time, row.closed_days) == ("테스트 국밥", "food", "11:00", "21:00", [0])
            assert (row.cost, row.stay_min, row.aliases) == (9000, 60, ["테스트국밥집"])
            assert row.tags["activity"] == ["사진", "식사"] and row.tags["setting"] == ["실내"]
            assert row.verified is False
            sheets = s.scalars(select(db.ChecklistRow).where(db.ChecklistRow.place_id == "store_001")).all()
            assert {c.rater for c in sheets} == {"홍길동", "김철수"}
            honggildong = next(c for c in sheets if c.rater == "홍길동")
            assert honggildong.checks["history_site"] is True and honggildong.checks["heritage"] is False
            assert honggildong.evidence["history_site"] == "현장 확인"
            # 광주다움 수동 4항목 중 홍길동이 O 인 것은 2개(history_site, long_running), 김철수는 전부 X -> 항목마다 0.5
            assert row.gwangju_ness == 1 + 0.5 + 0.5
            # not_franchise·market_zone 이 둘 다 0.5 (>= 0.5) 이므로 지역상권 장소
            assert row.is_local_commerce is True
        # 같은 파일을 다시 넣어도 중복되지 않는다 (덮어씀)
        again = xlsx_import.load(str(filled), placeholder=True)
        with db.session() as s:
            assert len(s.scalars(select(db.PlaceRow).where(db.PlaceRow.id == "store_001")).all()) == 1
            assert len(s.scalars(select(db.ChecklistRow).where(db.ChecklistRow.place_id == "store_001")).all()) == 2
    finally:
        with db.session() as s:
            s.execute(delete(db.ChecklistRow).where(db.ChecklistRow.place_id.in_(["store_001", "store_003"])))
            s.execute(delete(db.PlaceRow).where(db.PlaceRow.id.in_(["store_001", "store_003"])))
            s.commit()
        invalidate()


@pytest.mark.parametrize(
    "value, want",
    [("11:00", "11:00"), ("25:00", "25:00"), (" 9:30 ", "09:30"), (0.4583333333, "11:00"), (1.0416666667, "25:00")],
)
def test_time_cells(value, want):
    assert xlsx_import._hm(value) == want


def test_time_cell_from_excel_time_object():
    from datetime import time

    assert xlsx_import._hm(time(21, 5)) == "21:05"
    with pytest.raises(ValueError):
        xlsx_import._hm("열한시")


def test_closed_days_and_lists():
    assert xlsx_import._closed_days("월, 화요일") == [0, 1]
    assert xlsx_import._closed_days("연중무휴") == [] and xlsx_import._closed_days(None) == []
    assert xlsx_import._split("식사, 사진 / 산책\n야경") == ["식사", "사진", "산책", "야경"]
    assert xlsx_import._yes_no("O") is True and xlsx_import._yes_no("x") is False and xlsx_import._yes_no("") is None
