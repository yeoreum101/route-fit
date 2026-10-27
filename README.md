# Route-Fit

광주에 온 하나의 이유를 하루로 확장하는 AI 여행 조합 생성 플랫폼 (팀 센티멘트 · 2026 마이AI랩 AI-이음 프로젝트)

사용자가 정한 **Must Visit** 은 고정하고, 나머지 하루를 취향·시간·예산·동선·지역상권 기여도를 함께 계산해 원도심 장소로 채운다.

## 실행

저장소를 받은 뒤 아래 **A, B 중 하나**로 켜고 브라우저에서 http://localhost:8000 을 연다.
서버 하나가 화면(React, `fe/`)과 API 를 함께 제공한다. A(Docker)는 이미지를 만들 때 화면을 자동으로 빌드하고, B(Python)는 화면을 **한 번 빌드**해 둬야 한다(아래). 지도는 인터넷에서 불러오므로 인터넷 연결이 필요하다.

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

화면은 React(Vite)라서 Node.js 22 이상이 필요하고, 처음 한 번(그리고 `fe/` 를 고친 뒤) 빌드한다. 빌드 결과는 `fe/dist/` 에 생긴다.

```bash
cd fe
npm install
npm run build
cd ..
```

빌드하지 않아도 서버와 API(`/docs`)는 켜지고, 화면 자리에는 빌드 안내가 나온다.
화면을 고치는 중이라면 서버(8000)를 켜 둔 채 `cd fe && npm run dev` 로 http://localhost:5173 을 열면 고칠 때마다 바로 반영된다.

켜기 (코드를 고치면 자동으로 다시 시작된다. 끄기는 Ctrl+C):

```bash
.venv\Scripts\python -m uvicorn routefit.api:app --reload --reload-dir routefit      # Windows
.venv/bin/python -m uvicorn routefit.api:app --reload --reload-dir routefit          # macOS / Linux
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
| http://localhost:8000/admin.html | 장소 관리 · 현장조사 입력: 장소 추가/수정(지도 클릭으로 좌표), 취향 태그, 채점 체크리스트, JSON 내보내기 |
| http://localhost:8000/docs | API 문서 |

### 배포 서버 (AWS EC2)

시연 서버는 AWS 서울 리전 EC2(Ubuntu, t3.small) 에서 위 **A(Docker)** 방식 그대로 돌고 있다. 주소·관리자 토큰·접속 키는 팀 채널에서 받는다.
Docker 이미지에는 sentence-transformers 가 없으므로, 서버 `.env` 에 `OPENAI_API_KEY` 가 있어야 취향 매칭이 해싱이 아닌 OpenAI 임베딩으로 돈다(화면 하단 `임베딩 openai:…` 로 확인).

- **보기만 할 때**: 브라우저로 `http://<서버 주소>:8000` 을 연다. 장소 관리(`/admin.html`)는 관리자 토큰을 입력해야 저장된다.
- **서버에 들어갈 때**: AWS 콘솔 → EC2 → 인스턴스 `route-fit` → **연결** → EC2 Instance Connect(브라우저, 키 파일 필요 없음).
  키 파일(`route-fit.pem`)을 받았다면 터미널에서 `ssh -i route-fit.pem ubuntu@<서버 주소>` 도 된다. 이때는 보안 그룹 SSH 규칙에 내 IP 를 추가해야 하고, 키 파일은 저장소·메신저에 올리지 않는다.

서버에 들어간 뒤 (`cd route-fit` 에서):

```bash
git pull && docker compose up -d --build   # main 의 최신 코드로 다시 켜기 (DB 데이터는 남는다)
docker compose ps                          # 켜져 있는지 확인
docker compose logs -f app                 # 서버 로그 (Ctrl+C 로 빠져나옴)
docker compose restart app                 # 엑셀 가져오기 등으로 DB 를 고친 뒤 다시 읽히기
nano .env                                  # 키 바꾸기. 저장 후 docker compose up -d
```

- 인스턴스가 재부팅돼도 `restart: unless-stopped` 라서 서버가 자동으로 다시 켜진다. **인스턴스를 '중지'하면 주소가 바뀌니** 탄력적 IP 를 쓰지 않는 한 함부로 중지하지 않는다.
- `docker compose down -v` 는 서버 DB(코스·한줄평 포함)를 지운다. 서버에서는 쓰지 않는다.
- 서버에서 넣은 장소를 팀 데이터로 남기려면 관리 화면의 **JSON 내보내기** 결과를 `data/*.json` 에 커밋한다.

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
| `places` | 장소. `kind`: `candidate`(AI 추천 후보) / `anchor`(Must Visit 목적지). `tags`: 취향 태그 |
| `place_checklists` | 현장조사 체크리스트 (팀원 × 장소). 저장하면 `places` 의 3속성·지역상권 여부를 다시 계산한다 ([체크리스트](docs/field-checklist.md)) |
| `travel_times` | 지도 API 실거리 이동시간(분). 없는 구간은 직선거리로 추정 |
| `courses` | 생성된 코스 전체(공유 링크 `/?course=<id>`)와 집계용 지표 |
| `feedback` | 코스 별점(1~5) · 한줄평 |

테이블은 서버 시작 때 없으면 만든다(마이그레이션 도구 없음). 나중에 추가한 컬럼(`places.tags`)은 `db._add_missing_columns()` 가 기존 DB 에 넣어 준다.
그 밖에 컬럼을 바꾸면 DB 를 지우고 다시 만든다: `docker compose down -v` 또는 `data/routefit.db` 삭제.

## 구조

```
routefit/
  parser.py      ① LLM 자연어 조건 파싱      자유 문장 → ParsedQuery (시간·예산·동행·필수방문지·취향)
  embedding.py   ② 문장 임베딩 취향 매칭     장소 설명 벡터 × 취향 벡터 코사인 유사도
  planner/
    core.py        시간표 계산(실행 가능성 검사) · 추천 점수식 · 상한 제약
    greedy.py    ③-a 그리디 삽입 (Phase 1, 화면 이름 "기본 추천")
    ortools_planner.py  ③-b OR-Tools 제약 최적화 (Phase 2, 화면 이름 "최적화 추천")
  explain.py     ④ LLM 추천 이유 생성        계산 결과만 넘겨 "왜 이 코스인가"를 문장으로
  pipeline.py    ①→②→③→④ 연결, 실증 지표 계산, 생성된 코스 저장
  db.py          테이블 정의 · 연결 · 시드 (SQLite / PostgreSQL)
  data.py        장소·이동시간 조회 (캐시, 수정 시 invalidate)
  courses.py     코스 저장·공유 · 피드백 · 실증 지표 집계
  admin.py       관리자 API (장소 CRUD · 현장조사 채점 · 이동시간 · 피드백 · 가져오기/내보내기)
  travel.py      카카오모빌리티 길찾기로 장소 간 이동시간 채우기 (python -m routefit.travel)
  ratelimit.py   /api/plan 요청 수 제한
  tags.py        장소 태그 검증 · 취향 매칭용 표준 문장
  checklist.py   체크리스트 → 3속성 점수·지역상권 여부 계산 (자동 항목 규칙)
  api.py         FastAPI 공개 API
  config.py      가중치 · 상한 · 환경 변수
data/
  places.json    AI Discover 후보 (원도심 장소 데이터셋) — DB 시드
  tags.json      장소 취향 태그 목록 (할 거리·분위기·공간·시간·동행)
  checklist.json 현장조사 채점 체크리스트 (docs/field-checklist.md)
  anchors.json   Must Visit 목적지 (야구장·공연장·컨벤션센터) — DB 시드
fe/              화면 (React + Vite). 빌드 결과 fe/dist 를 서버가 내보낸다 → fe/README.md
  index.html     코스 만들기         src/pages/PlanPage.jsx
  stats.html     실증 통계           src/pages/StatsPage.jsx
  admin.html     장소 관리           src/pages/AdminPage.jsx
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
| `GET/PUT /api/admin/places/{id}/checklists`, `DELETE …/checklists/{rater}` | 현장조사 체크리스트 `{"rater", "checks": {항목: bool}, "evidence": {항목: 근거}}` |
| `GET /api/checklist` · `GET /api/tags` | 체크리스트 항목 · 장소 태그 목록 |
| `GET/PUT /api/admin/travel-times` | 이동시간 일괄 저장 `[{"from_id", "to_id", "minutes"}]` |
| `GET /api/admin/feedback` | 최근 별점 · 한줄평 |
| `GET /api/admin/export` · `POST /api/admin/import` | DB → JSON 내보내기(저장소 커밋용) · JSON → DB 초기화 |

`ROUTEFIT_ADMIN_TOKEN` 을 설정하면 `/api/admin/*` 에 `X-Admin-Token` 헤더가 필요하다(관리 화면은 처음에 토큰을 묻는다). 외부에 공개하는 시연에서는 반드시 설정한다.
`/api/plan` 은 접속 주소당 1분에 `ROUTEFIT_PLAN_RATE`(기본 20)번까지 받는다.

### 이동시간 채우기

```bash
.venv\Scripts\python -m routefit.travel --dry-run              # 호출할 구간 수 확인
.venv\Scripts\python -m routefit.travel --transit --limit 10   # 대중교통(TMAP): 빈 구간 중 10개만 채움
.venv\Scripts\python -m routefit.travel                        # 자동차(카카오 길찾기)로 빈 구간을 채움
```

대중교통은 `.env` 의 `TMAP_APP_KEY`(SK open API 앱 키, **TMAP 대중교통** 상품 사용 신청)로 TMAP 대중교통 길찾기를 부른다.
후보 경로 중 가장 빠른 것의 걷기+탑승 시간에 평균 대기 7분을 더해 저장한다(TMAP 응답에는 기다리는 시간이 없다).
Free 는 하루 10건이라 `--limit` 로 나눠 돌리고, 한도에 걸리면 멈춘다. 다시 돌리면 빈 구간부터 이어서 채운다.
Docker 서버에서는 `docker compose exec app python -m routefit.travel --transit --limit 10` 후 `docker compose restart app`.

실측값이 없는 구간은 추정치를 쓴다(`data.travel_minutes`): 도로 거리(직선 × 1.3) 1.2km 이하는 걸어서 시속 4.5km,
그보다 멀면 시내버스로 보고 정류장 오가는 걸음 6분 + 평균 대기 7분 + 시속 15km.
ODsay 대중교통 실측 29구간과 비교해 평균 2.2분(최대 6분) 차이라서, 지금은 구간별 실측 없이 이 추정치를 기본으로 쓴다.
(ODsay 무료 사용량은 하루 30건 안팎이라 장소 쌍 전부를 재기는 어렵다.)

`.env` 에 `KAKAO_REST_API_KEY` 가 필요하다. 카카오는 자동차 길찾기만 공개하므로, 채운 값은 자동차 시간 + 승차·주차 5분이다(택시 기준).
도보 거리 구간은 API 를 부르지 않는다.
같은 구간은 한 방향만 불러 양방향에 쓴다(`--both-ways` 로 따로). 끝나면 서버를 재시작한다.

### 가게 엑셀 가져오기

현장조사는 [`docs/가게조사양식.xlsx`](docs/가게조사양식.xlsx) 에 적고, 아래 명령으로 DB 에 넣는다. 같은 id 는 덮어쓰므로 파일을 고쳐 다시 실행해도 된다.
양식의 드롭다운·목록은 `data/tags.json` · `data/checklist.json` 에서 만들어지므로, 목록을 바꾸면 `python -m routefit.xlsx_template docs/가게조사양식.xlsx` 로 양식을 다시 만든다.

```bash
.venv/bin/python -m routefit.xlsx_import 파일.xlsx --dry-run   # 검사만. 틀린 줄은 '몇 행 어느 칸'인지 알려 준다
.venv/bin/python -m routefit.xlsx_import 파일.xlsx             # DB 에 넣기. 끝나면 서버를 재시작한다
.venv/bin/python -m routefit.xlsx_import 파일.xlsx --replace   # AI 추천 후보를 모두 지우고 이 파일로 바꾸기
```

- `가게정보` 시트의 한 줄이 장소 1곳, `체크리스트` 시트의 한 줄이 팀원 1명의 O/X 이다. 넣은 뒤 3속성 점수와 지역상권 여부를 다시 계산한다.
- `--replace` 는 AI 추천 후보(`candidate`)와 그 체크리스트·이동시간을 지우고 파일의 가게로 바꾼다. Must Visit 목적지(`anchor`)는 그대로 둔다. 고칠 곳이 하나라도 있으면 아무것도 지우지 않는다.
- 필수 칸(★)이 비면 그 줄은 넣지 않고 어느 칸이 비었는지 알려 준다. 영업시간은 `11:30-22:00` 형식(자정을 넘기면 `25:00`).
- 좌표(위도·경도)가 빈 줄은 기본적으로 넣지 않는다. `--geocode`(`.env` 의 `KAKAO_REST_API_KEY` 로 도로명 주소 검색) 또는 `--placeholder`(동구 중심 임시 좌표, 나중에 장소 관리 화면에서 지도를 눌러 고침)를 쓴다.
- [참고] 열(브레이크타임·라스트 오더·휴무 예외·메뉴·편의·네이버 링크·확인한 날짜·조사자·메모)은 저장 칸이 없어 넣지 않는다. 가져온 장소는 `verified=false` 이다.
- DB 에만 들어가므로 팀과 나누려면 `/api/admin/export` 결과를 `data/*.json` 에 커밋한다(`python -m routefit.db reset` 은 JSON 기준으로 되돌린다).
- 분위기 값을 바꾼 뒤 예전 DB 를 쓰고 있다면 `python -m routefit.db reset`(또는 Docker 는 `docker compose down -v`)으로 다시 채워야 한다. 예전 값을 가진 장소는 읽을 때 오류가 난다.

### 장소 태그 (취향 매칭)

취향 매칭(②)은 자유 설명이 아니라 `data/tags.json` 의 정해진 태그로 만든 문장을 쓴다. 쓰는 사람의 문체·단어 선택이 추천을 흔들지 않게 하기 위해서다.

```
국립아시아문화전당(ACC). 문화·전시. 동구 광산동. 할 거리: 사진 / 전시 관람 / 건축 구경 | 분위기: 조용한 / 현대적인 / 아늑한 | 공간: 실내외 | …
```

- 장소 관리 화면에서 태그를 고른다. 할 거리·분위기·공간은 필수(비어 있으면 목록에 "태그 부족")
- `description`(한줄 소개)은 추천 이유·조건 파싱의 사실 자료로만 쓰고 매칭에는 쓰지 않는다
- 태그가 하나도 없는 장소는 예전처럼 소개 문장으로 매칭한다
- 태그 목록을 바꾸면 서버를 재시작한다. `GET /api/tags` 로 현재 목록을 본다

### 추천 점수식 (`planner/core.py`, 가중치는 `config.py`)

```
코스 점수 = Σ(취향 적합도 + 지역상권 기여도 + 동행 적합도 − 장소 추가 비용) − 이동 부담 − 시간 초과 페널티
지역상권 기여도 = 지역성((광주다움 + 상권 연계성) / 2) + 체류 유도성     → Place.local_score
동행 적합도 = 문장의 동행(혼자·친구·연인·가족·아이 동반)이 장소의 '어울리는 동행' 태그에 있으면 1, 아니면 0
3속성 점수 = 1 + 체크리스트 항목 값 합계 (docs/field-checklist.md)
```

두 생성기 모두 같은 `schedule()` 로 시간표를 만들기 때문에, 결과 코스는 항상 영업시간·고정 시각·이동시간을 지킨다.

### 대체 경로

| 단계 | 기본 | 없을 때 |
|---|---|---|
| ① 파싱 · ④ 이유 | `ROUTEFIT_LLM_PROVIDER`: `gemini`(무료 사용량, 기본) 또는 `openai`(유료). 호출부는 `llm.py` 한 곳 | 정규식 파서 · 템플릿 문장 |
| ② 임베딩 | `OPENAI_API_KEY` 가 있으면 OpenAI 임베딩 API (`ROUTEFIT_OPENAI_EMBED_MODEL`), 없으면 sentence-transformers (`ROUTEFIT_SBERT_MODEL`) | 문자 n-gram 해싱 (글자 겹침만 봄, 개발용) |
| ③ 최적화 | 요청의 `planner` 값 | OR-Tools 실패 시 그리디 |

응답의 `engine` 필드와 화면 하단에 실제로 어떤 경로가 쓰였는지 표시된다.

## 지금 채워야 할 것

- **`data/places.json` 은 예시 데이터다.** 좌표·영업시간·체류시간·비용·3속성 점수 모두 임의로 넣은 값이고 전부 `verified: false` 다. 현장조사 결과로 교체한다(관리자 API 로 입력하거나 JSON 을 고쳐 `reset`). 고친 결과는 `/api/admin/export` 로 받아 `data/*.json` 에 커밋해 둔다.
- 이동시간은 `python -m routefit.travel`(카카오 키 필요), `PUT /api/admin/travel-times`, `data/travel_matrix.json` (`{"출발id|도착id": 분}`) 중 하나로 넣으면 직선거리 추정 대신 쓰인다.
- `config.py` 의 가중치는 검증되지 않은 초기값이다.
- 지도는 `KAKAO_JS_KEY` 가 있으면 카카오맵, 없으면 OSM 타일이다. 지도 엔진을 바꿀 때는 `fe/src/map/mapView.js` 만 바꾸면 된다.
