# Route-Fit 화면 (React)

`web/` 의 HTML·JS·CSS 화면을 React(Vite)로 옮긴 것이다. `web/` 은 그대로 두었고, 백엔드(`routefit/`)도 바꾸지 않았다.
주소·화면·동작은 원래와 같다: `/` 코스 만들기, `/stats.html` 실증 통계, `/admin.html` 장소 관리.

## 실행

백엔드를 먼저 띄운다(8000). 그다음 화면:

```bash
cd fe
npm install
npm run dev      # http://localhost:5173  (/api 는 8000 으로 넘어간다)
```

빌드: `npm run build` → `fe/dist/`. 이 폴더를 FastAPI가 서빙하게 하려면 `routefit/config.py` 의 `WEB_DIR` 를 `ROOT / "fe" / "dist"` 로 바꾸고,
Dockerfile 에 node 빌드 단계를 추가한다(지금은 건드리지 않았다).

## 구조

```
index.html · stats.html · admin.html   페이지 3개 (Vite 다중 엔트리)
src/
  style.css                 web/style.css 그대로
  common.js                 공통 도우미 (관리자 토큰, 오류 문구, 라벨)       <- web/common.js
  entries/                  페이지별 진입점
  pages/PlanPage.jsx        코스 만들기: 입력 상태, 코스·지도 연결          <- web/app.js
  pages/StatsPage.jsx       실증 통계                                    <- web/stats.js
  pages/AdminPage.jsx       장소 관리 · 체크리스트                         <- web/admin.js
  components/TimePicker     오전/오후·시·분 선택기
  components/MustVisitList  필수 방문지 여러 곳 + 시간 겹침 검사
  components/CourseView     인식된 조건 · 타임라인 · 공유/별점
  components/CourseMap      지도 패널 (카카오맵/OSM)
  components/MiniMap        장소 관리의 좌표 고르기 지도
  map/mapView.js            지도 엔진 어댑터                              <- web/map.js
```
