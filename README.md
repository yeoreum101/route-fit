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
  pipeline.py    ①→②→③→④ 연결, 실증 지표 계산, 매칭 로그(logs/plans.jsonl)
  api.py         FastAPI (POST /api/plan, GET /api/places, GET /api/anchors)
  config.py      가중치 · 상한 · 환경 변수
data/
  places.json    AI Discover 후보 (원도심 장소 데이터셋)
  anchors.json   Must Visit 목적지 (야구장·공연장·컨벤션센터)
web/             입력 UI · 코스 타임라인 · 지도 (정적 파일, Leaflet)
```

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

- **`data/places.json` 은 예시 데이터다.** 좌표·영업시간·체류시간·비용·3속성 점수 모두 임의로 넣은 값이고 전부 `verified: false` 다. 현장조사 결과로 교체한다.
- `data/travel_matrix.json` (`{"출발id|도착id": 분}`) 을 만들면 지도 API 실거리 이동시간이 직선거리 추정 대신 쓰인다.
- `config.py` 의 가중치는 검증되지 않은 초기값이다.
- 임베딩 API 를 쓰려면 `embedding.py` 에 `Embedder` 구현을 하나 추가하고 `get_embedder()` 에 연결한다.
- 지도는 OSM 타일이다. 카카오/네이버 지도로 바꿀 때는 `web/app.js` 의 지도 초기화와 `drawMap` 만 바꾸면 된다.
