# Route-Fit

광주에 온 하나의 이유를 하루로 확장하는 AI 여행 조합 생성 플랫폼 (팀 센티멘트 · 2026 마이AI랩 AI-이음 프로젝트)

사용자가 정한 **Must Visit** 은 고정하고, 나머지 하루를 취향·시간·예산·동선·지역상권 기여도를 함께 계산해 원도심 장소로 채운다.

## 실행

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn routefit.api:app --reload
```

http://localhost:8000 에서 조건 입력 → 코스 → 지도를 한 화면에서 확인한다. API 문서는 `/docs`.

```bash
.venv\Scripts\python -m pytest
```

API 키와 임베딩 모델이 없어도 끝까지 동작한다(아래 "대체 경로"). 실제 AI를 붙이려면 `.env.example` 을 `.env` 로 복사해 채운다.

### 데이터베이스

설정이 없으면 `data/routefit.db` (SQLite) 를 만들어 쓰므로 설치할 것이 없다. 처음 실행할 때 `data/places.json` · `anchors.json` 으로 채워진다.
시연은 PostgreSQL 로 한다.

```bash
docker compose up -d --build
```

PostgreSQL 과 서버가 함께 뜬다 → http://localhost:8000. DB 만 띄우고 서버는 로컬에서 돌리려면 `docker compose up -d db` 후 `.env` 에
`DATABASE_URL=postgresql+psycopg://routefit:routefit@localhost:5432/routefit`.

```bash
.venv\Scripts\python -m routefit.db          # 연결된 DB 와 장소 수 확인
.venv\Scripts\python -m routefit.db reset    # 장소·이동시간을 data/*.json 기준으로 초기화 (코스·피드백은 유지)
```

| 테이블 | 내용 |
|---|---|
| `places` | 장소. `kind`: `candidate`(AI 추천 후보) / `anchor`(Must Visit 목적지) |
| `place_ratings` | 현장조사 채점 원점수 (팀원 × 장소). 저장하면 `places` 의 3속성이 평균으로 갱신된다 |
| `travel_times` | 지도 API 실거리 이동시간(분). 없는 구간은 직선거리로 추정 |
| `courses` | 생성된 코스 전체(공유 링크 `/?course=<id>`)와 집계용 지표 |
| `feedback` | 코스 별점(1~5) · 한줄평 |

테이블은 서버 시작 때 없으면 만든다(마이그레이션 도구 없음). **컬럼을 바꾸면 DB 를 지우고 다시 만든다**: `docker compose down -v` 또는 `data/routefit.db` 삭제.

## 구조

```
routefit/
  parser.py      ① LLM 자연어 조건 파싱      자유 문장 → ParsedQuery (시간·예산·동행·필수방문지·취향)
  embedding.py   ② 문장 임베딩 취향 매칭     장소 설명 벡터 × 취향 벡터 코사인 유사도
  planner/
    core.py        시간표 계산(실행 가능성 검사) · 추천 점수식 · 상한 제약
    greedy.py    ③-a 그리디 삽입 (Phase 1)
    ortools_planner.py  ③-b OR-Tools 제약 최적화 (Phase 2)
  explain.py     ④ LLM 추천 이유 생성        계산 결과만 넘겨 "왜 이 코스인가"를 문장으로
  pipeline.py    ①→②→③→④ 연결, 실증 지표 계산, 생성된 코스 저장
  db.py          테이블 정의 · 연결 · 시드 (SQLite / PostgreSQL)
  data.py        장소·이동시간 조회 (캐시, 수정 시 invalidate)
  courses.py     코스 저장·공유 · 피드백 · 실증 지표 집계
  admin.py       관리자 API (장소 CRUD · 현장조사 채점 · 이동시간 · 가져오기/내보내기)
  api.py         FastAPI 공개 API
  config.py      가중치 · 상한 · 환경 변수
data/
  places.json    AI Discover 후보 (원도심 장소 데이터셋) — DB 시드
  anchors.json   Must Visit 목적지 (야구장·공연장·컨벤션센터) — DB 시드
web/             입력 UI · 코스 타임라인 · 지도 (정적 파일, Leaflet)
```

### API

전체 명세와 직접 호출은 `/docs`.

| | |
|---|---|
| `POST /api/plan` | 코스 생성. 응답의 `id` 로 저장됨 |
| `GET /api/courses` · `/api/courses/{id}` | 최근 코스 목록 · 저장된 코스(공유 링크) |
| `POST /api/courses/{id}/feedback` | 별점 `{"rating": 1~5, "comment": ""}` |
| `GET /api/stats` | 실증 지표: 생성기별 평균(장소 수·이동·지역상권 비율·점수), 평균 별점, 많이 추천된 장소 |
| `GET /api/places` · `/api/anchors` · `/api/health` | 장소 목록 · 상태 |
| `GET/POST /api/admin/places`, `GET/PUT/PATCH/DELETE /api/admin/places/{id}` | 장소 관리. 저장 즉시 추천에 반영(재시작 불필요) |
| `GET/PUT /api/admin/places/{id}/ratings`, `DELETE …/ratings/{rater}` | 현장조사 채점 `{"rater", "gwangju_ness", "stay_inducement", "commerce_link"}` |
| `GET/PUT /api/admin/travel-times` | 이동시간 일괄 저장 `[{"from_id", "to_id", "minutes"}]` |
| `GET /api/admin/export` · `POST /api/admin/import` | DB → JSON 내보내기(저장소 커밋용) · JSON → DB 초기화 |

`ROUTEFIT_ADMIN_TOKEN` 을 설정하면 `/api/admin/*` 에 `X-Admin-Token` 헤더가 필요하다. 외부에 공개하는 시연에서는 반드시 설정한다.

### 추천 점수식 (`planner/core.py`, 가중치는 `config.py`)

```
코스 점수 = Σ(취향 적합도 + 지역상권 기여도 − 장소 추가 비용) − 이동 부담 − 시간 초과 페널티
지역상권 기여도 = 지역성((광주다움 + 상권 연계성) / 2) + 체류 유도성     → Place.local_score
```

두 생성기 모두 같은 `schedule()` 로 시간표를 만들기 때문에, 결과 코스는 항상 영업시간·고정 시각·이동시간을 지킨다.

### 대체 경로

| 단계 | 기본 | 없을 때 |
|---|---|---|
| ① 파싱 · ④ 이유 | `ROUTEFIT_LLM_PROVIDER`: `gemini`(무료 사용량, 기본) 또는 `openai`(유료). 호출부는 `llm.py` 한 곳 | 정규식 파서 · 템플릿 문장 |
| ② 임베딩 | sentence-transformers (`ROUTEFIT_SBERT_MODEL`) | 문자 n-gram 해싱 (글자 겹침만 봄, 개발용) |
| ③ 최적화 | 요청의 `planner` 값 | OR-Tools 실패 시 그리디 |

응답의 `engine` 필드와 화면 하단에 실제로 어떤 경로가 쓰였는지 표시된다.

## 지금 채워야 할 것

- **`data/places.json` 은 예시 데이터다.** 좌표·영업시간·체류시간·비용·3속성 점수 모두 임의로 넣은 값이고 전부 `verified: false` 다. 현장조사 결과로 교체한다(관리자 API 로 입력하거나 JSON 을 고쳐 `reset`). 고친 결과는 `/api/admin/export` 로 받아 `data/*.json` 에 커밋해 둔다.
- 이동시간은 `PUT /api/admin/travel-times` 나 `data/travel_matrix.json` (`{"출발id|도착id": 분}`) 으로 넣으면 직선거리 추정 대신 쓰인다.
- `config.py` 의 가중치는 검증되지 않은 초기값이다.
- 임베딩 API 를 쓰려면 `embedding.py` 에 `Embedder` 구현을 하나 추가하고 `get_embedder()` 에 연결한다.
- 지도는 OSM 타일이다. 카카오/네이버 지도로 바꿀 때는 `web/app.js` 의 지도 초기화와 `drawMap` 만 바꾸면 된다.
