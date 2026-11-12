import io

import openpyxl
from fastapi.testclient import TestClient

from routefit import xlsx_import, xlsx_template
from routefit.api import app

from test_xlsx_import import GOOD, _cleanup, _make

client = TestClient(app)
SCREEN_PLACE = {
    # 장소 관리 화면에서 새로 넣은 장소 (엑셀에는 없음)
    "id": "s_950", "name": "화면에서 넣은 분식", "category": "food", "area": "동구 충장로", "lat": 35.147, "lng": 126.917,
    "tags": {"activity": ["식사", "길거리 음식"], "mood": ["정겨운", "레트로한"], "setting": ["실내"], "time": ["오후", "저녁"]},
    "aliases": ["상추튀김"], "open": "11:00", "close": "21:00", "break_start": "15:00", "break_end": "16:00",
    "closed_days": [0, 6], "stay_min": 40, "cost": 9000, "kind": "candidate",
}


def _sheet(data: bytes, name="가게정보"):
    return openpyxl.load_workbook(io.BytesIO(data))[name]


def _row(ws, place_id):
    cols = xlsx_template._columns(ws)
    for r in range(3, ws.max_row + 1):
        if ws.cell(r, cols["id"]).value == place_id and ws.cell(r, cols["name"]).value:
            return {k: ws.cell(r, c).value for k, c in cols.items()}
    return None


def test_export_merges_into_team_file_and_keeps_reference_cells(tmp_path):
    team = {**GOOD, "menu": "국밥 9,000", "memo": "팀 메모", "link": "https://map.naver.com/p/entry/place/1"}
    not_in_db = {**GOOD, "id": "s_960", "name": "아직 안 넣은 가게"}
    path = _make(tmp_path, [team, not_in_db], [("s_901", "홍길동", None)])
    try:
        xlsx_import.load(path)  # s_901 만 들어가고 s_960 도 들어간다
        client.delete("/api/admin/places/s_960")  # 화면에서 지운 가게
        # 화면에서 고치기 · 새 장소 · 체크리스트
        rec = client.get("/api/admin/places/s_901").json()
        assert client.put("/api/admin/places/s_901", json={**rec, "cost": 12000, "name": "테스트 국밥 본점"}).status_code == 200
        assert client.post("/api/admin/places", json=SCREEN_PLACE).status_code == 201
        checks = {k: False for k in xlsx_import.checklist.manual_keys()}
        assert client.put("/api/admin/places/s_950/checklists", json={"rater": "김철수", "checks": {**checks, "seating": True}}).status_code == 200

        res = client.post("/api/admin/export.xlsx", content=open(path, "rb").read())
        assert res.status_code == 200, res.text
        assert res.headers["x-export-updated"] == "1"  # 이 엑셀에 있던 s_901 (나머지 예시 장소는 새 줄로 더해진다)
        ws = _sheet(res.content)
        row = _row(ws, "s_901")
        assert (row["name"], row["cost"]) == ("테스트 국밥 본점", 12000)
        assert (row["menu"], row["memo"], row["link"]) == ("국밥 9,000", "팀 메모", "https://map.naver.com/p/entry/place/1")
        assert _row(ws, "s_960")["name"] == "아직 안 넣은 가게"  # DB 에 없는 줄은 지우지 않는다
        new = _row(ws, "s_950")
        assert new["category"] == "식당" and new["hours"] == "11:00-21:00" and new["break"] == "15:00-16:00"
        assert new["closed"] == "월, 일" and new["activity"] == "식사, 길거리 음식" and new["aliases"] == "상추튀김"
        sheet = _sheet(res.content, "체크리스트")
        rows = {(sheet.cell(r, 1).value, sheet.cell(r, 3).value): r for r in range(3, sheet.max_row + 1) if sheet.cell(r, 3).value}
        assert ("s_901", "홍길동") in rows and ("s_950", "김철수") in rows
        assert len([k for k in rows if k[0] == "s_901"]) == 1  # 같은 채점자 줄을 또 더하지 않는다

        # 내보낸 파일을 다시 가져와도 그대로 들어간다(오류 없음)
        out = tmp_path / "out.xlsx"
        out.write_bytes(res.content)
        report = xlsx_import.load(str(out), dry_run=True)
        assert not report.errors, report.errors
        assert {"s_901 테스트 국밥 본점", "s_950 화면에서 넣은 분식"} <= set(report.places)
    finally:
        _cleanup(["s_901", "s_950", "s_960"])


def test_export_without_file_makes_new_template():
    res = client.post("/api/admin/export.xlsx")
    assert res.status_code == 200
    ws = _sheet(res.content)
    assert int(res.headers["x-export-added"]) > 0 and _row(ws, "s_001") is not None


def test_export_rejects_non_template_file():
    wb = openpyxl.Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    res = client.post("/api/admin/export.xlsx", content=buf.getvalue())
    assert res.status_code == 400 and "양식" in res.json()["detail"]
    assert client.post("/api/admin/export.xlsx", content=b"not a zip").status_code == 400
