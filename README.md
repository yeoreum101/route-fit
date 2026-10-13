# Route-Fit

광주에 온 하나의 이유를 하루로 확장하는 AI 여행 조합 생성 플랫폼 (팀 센티멘트 · 2026 마이AI랩 AI-이음 프로젝트)

사용자가 정한 **Must Visit** 은 고정하고, 나머지 하루를 취향·시간·예산·동선·지역상권 기여도를 함께 계산해 원도심 장소로 채운다.

## 실행

저장소를 받은 뒤 아래 **A, B 중 하나**로 켜고 브라우저에서 http://localhost:8000 을 연다.
서버 하나가 화면과 API 를 함께 제공하므로 프론트엔드를 따로 켤 필요는 없다. 지도는 인터넷에서 불러오므로 인터넷 연결이 필요하다.

```bash
git clone https://github.com/yeoreum101/route-fit.git
cd route-fit
```

### A. Docker 로 켜기 (시연과 같은 환경, PostgreSQL)

[Docker Desktop](https://www.docker.com/products/docker-desktop/) 을 설치하고 실행해 둔다(엔진이 켜질 때까지 기다린다). Python 설치는 필요 없다.

```bash
docker compose up -d --build     # 켜기 (코드를 고친 뒤에도 이 명령으로 다시 빌드)
docker compose logs -f app       # 서버 로그 보기 (Ctrl+C 로 빠져나옴, 서버는 계속 켜져 있음)
docker compose down              # 끄기 (데이터는 남는다)
docker compose down -v           # 끄고 DB 데이터까지 지우기 (처음 상태로)
```

### B. Python 으로 켜기 (개발용, SQLite)

Python 3.11 이상이 필요하다. 처음 한 번만 가상환경을 만든다.

```bash
# Windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# macOS / Linux
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

켜기 (코드를 고치면 자동으로 다시 시작된다. 끄기는 Ctrl+C):

```bash
.venv\Scripts\python -m uvicorn routefit.api:app --reload      # Windows
.venv/bin/python -m uvicorn routefit.api:app --reload          # macOS / Linux
```

DB 는 `data/routefit.db` 파일로 자동으로 만들어진다. A 와 B 는 DB 가 따로라서 데이터가 공유되지 않는다.

### 자주 막히는 곳

| 증상 | 해결 |
|---|---|
| `port is already allocated` · `address already in use` (8000) | A 와 B 를 동시에 켰다. 하나를 끈다 |
| `port 5433 … already allocated` | 다른 프로그램이 5433 을 쓰는 중. `docker-compose.yml` 의 `"5433:5432"` 앞 숫자를 바꾼다 |
| `docker: … cannot find the file specified` · `Cannot connect to the Docker daemon` | Docker Desktop 이 꺼져 있거나 엔진이 아직 시작 중 |
| 장소 데이터가 꼬였다 | 장소 관리 화면의 **예시 데이터로 초기화**, 또는 `python -m routefit.db reset` |
| 같은 와이파이의 다른 기기에서 보고 싶다 | `http://<내 PC IP>:8000`. B 는 `--host 0.0.0.0` 을 붙여 켠다. 이때는 `.env` 에 `ROUTEFIT_ADMIN_TOKEN` 을 꼭 설정 |

### 화면

| 주소 | |
|---|---|
| http://localhost:8000 | 조건 입력 → 코스 → 지도. 공유 링크 · 별점 · 한줄평 |
| http://localhost:8000/stats.html | 실증 통계: 생성기 비교, 지역상권 비율, 많이 추천된 장소, 최근 코스 · 한줄평 |
| http://localhost:8000/admin.html | 장소 관리 · 현장조사 입력: 장소 추가/수정(지도 클릭으로 좌표), 팀원별 채점, JSON 내보내기 |
| http://localhost:8000/docs | API 문서 |

### 설정 (.env)

API 키가 없어도 끝까지 동작한다(아래 "대체 경로"). 키·관리자 토큰 등을 넣으려면 `.env.example` 을 `.env` 로 복사해 채운다.
`.env` 는 저장소에 올라가지 않으므로 키는 팀 채널로 따로 공유한다. A 는 `.env` 를 고친 뒤 `docker compose up -d` 를 다시 실행해야 반영된다.

### 테스트

```bash
.venv\Scripts\python -m pytest
```

### 데이터베이스

설정이 없으면 `data/routefit.db` (SQLite) 를 만들어 쓰므로 설치할 것이 없다. 처음 실행할 때 `data/places.json` · `anchors.json` 으로 채워진다.
시연은 PostgreSQL 로 한다(위 A). DB 만 Docker 로 띄우고 서버는 B 로 돌리려면 `docker compose up -d db` 후 `.env` 에
`DATABASE_URL=postgresql+psycopg://routefit:routefit@localhost:5433/routefit`.

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
  admin.py       관리자 API (장소 CRUD · 현장조사 채점 · 이동시간 · 피드백 · 가져오기/내보내기)
  travel.py      카카오모빌리티 길찾기로 장소 간 이동시간 채우기 (python -m routefit.travel)
  ratelimit.py   /api/plan 요청 수 제한
  api.py         FastAPI 공개 API
  config.py      가중치 · 상한 · 환경 변수
data/
  places.json    AI Discover 후보 (원도심 장소 데이터셋) — DB 시드
  anchors.json   Must Visit 목적지 (야구장·공연장·컨벤션센터) — DB 시드
web/             정적 파일 (Leaflet 지도)
  index.html     코스 만들기         app.js
  stats.html     실증 통계           stats.js
  admin.html     장소 관리           admin.js
  common.js      공통 도우미 (관리자 토큰, 오류 문구)
```

### API

전체 명세와 직접 호출은 `/docs`.

| | |
|---|---|
| `POST /api/plan` | 코스 생성. 응답의 `id` 로 저장됨. 조건은 화면 입력 > 문장 > 기본값 순으로 쓰고, 각 조건의 출처와 덮어쓴 내용을 `constraints.sources` · `constraints.notes` 로 돌려준다 |
| `GET /api/courses` · `/api/courses/{id}` | 최근 코스 목록 · 저장된 코스(공유 링크) |
| `POST /api/courses/{id}/feedback` | 별점 `{"rating": 1~5, "comment": ""}` |
| `GET /api/stats` | 실증 지표: 생성기별 평균(장소 수·이동·지역상권 비율·점수), 평균 별점, 많이 추천된 장소 |
| `GET /api/places` · `/api/anchors` · `/api/health` | 장소 목록 · 상태 |
| `GET/POST /api/admin/places`, `GET/PUT/PATCH/DELETE /api/admin/places/{id}` | 장소 관리. 저장 즉시 추천에 반영(재시작 불필요) |
| `GET/PUT /api/admin/places/{id}/ratings`, `DELETE …/ratings/{rater}` | 현장조사 채점 `{"rater", "gwangju_ness", "stay_inducement", "commerce_link"}` |
| `GET/PUT /api/admin/travel-times` | 이동시간 일괄 저장 `[{"from_id", "to_id", "minutes"}]` |
| `GET /api/admin/feedback` | 최근 별점 · 한줄평 |
| `GET /api/admin/export` · `POST /api/admin/import` | DB → JSON 내보내기(저장소 커밋용) · JSON → DB 초기화 |

`ROUTEFIT_ADMIN_TOKEN` 을 설정하면 `/api/admin/*` 에 `X-Admin-Token` 헤더가 필요하다(관리 화면은 처음에 토큰을 묻는다). 외부에 공개하는 시연에서는 반드시 설정한다.
`/api/plan` 은 접속 주소당 1분에 `ROUTEFIT_PLAN_RATE`(기본 20)번까지 받는다.

### 이동시간 채우기

```bash
.venv\Scripts\python -m routefit.travel --dry-run   # 호출할 구간 수 확인
.venv\Scripts\python -m routefit.travel             # 비어 있는 구간만 카카오 길찾기로 채움
```

`.env` 에 `KAKAO_REST_API_KEY` 가 필요하다. 직선 1.2km 이하는 도보 추정값을 그대로 쓰고, 나머지는 자동차 시간 + 승차·주차 5분.
같은 구간은 한 방향만 불러 양방향에 쓴다(`--both-ways` 로 따로). 끝나면 서버를 재시작한다.

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
- 이동시간은 `python -m routefit.travel`(카카오 키 필요), `PUT /api/admin/travel-times`, `data/travel_matrix.json` (`{"출발id|도착id": 분}`) 중 하나로 넣으면 직선거리 추정 대신 쓰인다.
- `config.py` 의 가중치는 검증되지 않은 초기값이다.
- 임베딩 API 를 쓰려면 `embedding.py` 에 `Embedder` 구현을 하나 추가하고 `get_embedder()` 에 연결한다.
- 지도는 OSM 타일이다. 카카오/네이버 지도로 바꿀 때는 `web/app.js` 의 지도 초기화와 `drawMap` 만 바꾸면 된다.
