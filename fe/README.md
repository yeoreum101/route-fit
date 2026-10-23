# Route-Fit 화면 (React)

Route-Fit 의 화면 전체다(React + Vite). 예전 정적 화면(`web/`)을 옮겨 온 것이며 `web/` 은 지웠다(필요하면 git 기록에서 볼 수 있다).
주소: `/` 코스 만들기, `/stats.html` 실증 통계, `/admin.html` 장소 관리.

## 실행

Node.js 22 이상이 필요하다.

**서버로 보기 (시연과 같은 방식)** — 빌드하면 FastAPI 서버(8000)가 `fe/dist/` 를 내보낸다.

```bash
cd fe
npm install
npm run build        # → fe/dist/
cd ..
.venv/bin/python -m uvicorn routefit.api:app --reload --reload-dir routefit      # http://localhost:8000
```

**화면을 고치는 중** — 백엔드를 먼저 띄운(8000) 상태에서:

```bash
cd fe
npm run dev          # http://localhost:5173  (/api 는 8000 으로 넘어간다)
```

Docker(`docker compose up -d --build`)는 이미지를 만들 때 Node 단계에서 자동으로 빌드하므로 따로 할 일이 없다.
`fe/dist/` 가 없으면 서버는 켜지고 API 는 동작하지만, 화면 자리에는 "빌드하세요" 안내가 나온다.

## 구조

```
index.html · stats.html · admin.html   페이지 3개 (Vite 다중 엔트리)
src/
  style.css                 전체 스타일
  common.js                 공통 도우미 (관리자 토큰, 오류 문구, 라벨)
  entries/                  페이지별 진입점
  pages/PlanPage.jsx        코스 만들기: 입력 상태, 코스·지도 연결
  pages/StatsPage.jsx       실증 통계
  pages/AdminPage.jsx       장소 관리 · 체크리스트
  components/TimePicker     오전/오후·시·분 선택기
  components/MustVisitList  필수 방문지 여러 곳 + 시간 겹침 검사
  components/CourseView     인식된 조건 · 타임라인 · 공유/별점
  components/CourseMap      지도 패널 (카카오맵/OSM)
  components/MiniMap        장소 관리의 좌표 고르기 지도
  map/mapView.js            지도 엔진 어댑터
```
