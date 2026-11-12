"""환경 설정과 추천 점수식 가중치."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
# 화면(React)을 빌드한 결과. 없으면 `cd fe && npm install && npm run build` (Docker 는 이미지를 만들 때 알아서 빌드한다)
WEB_DIR = ROOT / "fe" / "dist"

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Weights:
    """추천 점수식: 취향 적합도 + 지역상권 기여도 + 동행 적합도 + 끼니 - 이동 부담 - 빈 시간 - 시간 초과 페널티.

    초기값이며 검증되지 않았다. 중간발표 직후 보정 기간에 내부 테스트로 조정한다.
    """

    taste: float = 1.0  # 취향 적합도 (후보 내 0~1 정규화된 코사인 유사도)
    local: float = 0.6  # 지역상권 기여도 (0~1)
    companion: float = 0.3  # 문장의 동행이 장소의 '어울리는 동행' 태그에 있으면 더한다
    # 문장에서 콕 집어 말한 할 거리("전시 좀 보고")가 장소의 '할 거리' 태그에 있으면 더한다. 취향 점수는 후보 안에서
    # 0~1 로 다시 매겨 차이가 작아서, '전시'를 말했는데 전시가 없는 극장이 지역상권 점수로 뽑힌 적이 있다.
    activity: float = 0.5
    # 이동 1분당 감점. 0.012 일 때는 멀리 있는 필수 방문지(예: 상무지구 호텔)를 하루 가운데에 두고 갔다가 돌아오는
    # 코스가 나와 0.025 로 올렸다(그 예에서 이동 126분 -> 82분). 0.04 는 장소를 거의 넣지 않을 만큼 세다.
    travel_per_min: float = 0.025
    overtime_per_min: float = 0.05  # 종료 희망 시각 초과 1분당 감점
    wait_per_min: float = 0.006  # 일정 사이 빈 시간 1분당 감점 (식당이 식사 시간대를 기다리며 생기는 공백)
    # 점심·저녁 시간대(meal_windows)에 식당이 있으면 끼니마다 더한다. 장소 하나의 가치(최대 1.6)에 식사 시간대를
    # 기다리는 감점까지 넘도록 커서, 하루가 식사 시간대에 걸치면 취향 점수가 가장 낮은 식당이라도 그 끼니에 넣는다.
    # 식당을 피한다고 했으면 후보가 없어 더하지 않는다.
    meal: float = 2.0
    stop_cost: float = 0.3  # 장소 1곳을 추가하려면 넘어야 하는 최소 가치


@dataclass(frozen=True)
class Limits:
    overtime_grace_min: int = 30  # 종료 희망 시각을 이만큼까지는 넘길 수 있다(감점)
    # 장소 수를 말하지 않았을 때의 하루 장소 상한(꼭 갈 곳 포함, 출발 위치 제외): 하루 길이 minutes_per_place 분에
    # 1곳, 많아야 max_places 곳(기본 하루 11~21시 6곳, 9시간 5곳, 6시간 3곳). 짧은 하루에 6곳을 채우면 빡빡했다.
    # AI 추천은 이 안에서 꼭 갈 곳을 뺀 만큼 넣는다. 문장에서 "8곳 이상" 처럼 말하면 그 수를 따른다
    max_places: int = 6
    minutes_per_place: int = 100
    # 장소 수를 줄여 하루가 일찍 끝나면 남는 시간만큼 AI 가 고른 곳에 더 머문다. 원래 머무는 시간의 이 배까지
    stretch_max: float = 1.5
    max_ai_stops: int = 6
    # AI 추천 장소를 이만큼은 넣는다. 기본은 없음. 문장에서 "4곳 이상" 처럼 말하면 요청마다 바꾼다(dataclasses.replace)
    min_ai_stops: int = 0
    fewer_places: int = 4  # 수 없이 "장소 너무 많아"·"몇 군데만" 이라고 하면 하루 장소를 이만큼까지
    category_caps: tuple[tuple[str, int], ...] = (("food", 2), ("cafe", 2), ("night", 1))
    min_cafe_stay: int = 90  # 카페는 이보다 짧게 머물지 않는다 (장소의 머무는 시간이 더 길면 그것을 쓴다)
    min_meal_stay: int = 70  # 식당도 마찬가지. 60분이면 밥이 빠듯하다는 설문 의견
    # AI 가 고른 식당은 식사 시간대 안에서 시작하고, 한 끼에 한 곳만 넣는다. (이름, 시작 가능 구간, 자정 기준 분)
    meal_windows: tuple[tuple[str, int, int], ...] = (("점심", 11 * 60, 13 * 60 + 30), ("저녁", 17 * 60, 19 * 60 + 30))
    # 나가는 시각을 이 단위(분)로 맞춘다. 분 단위 일정은 따르기 어렵다는 설문 의견. 도착은 실제 시각 그대로 보여 준다
    time_step: int = 10
    # 시작 시각은 이 단위로 올린다(최대 4분 기다림). 나가는 시각이 10분 단위라 머무는 시간이 5분 단위로 보인다
    start_step: int = 5
    # 대중교통을 타지 않겠다고 하면 코스를 고를 때 걸어서 못 가는 구간을 이만큼 더 걸리는 것으로 본다(이동 감점과
    # 하루 시간을 함께 늘려 걸어서 닿는 곳끼리 고르게 한다). 꼭 갈 곳이 멀면 그 구간은 남는다. 시간표는 실제 이동시간으로 짠다
    no_transit_extra_min: int = 60
    min_meal_gap: int = 180  # 앞 식당에서 나온 뒤 이만큼 지나야 다음 식당에 들어간다 (둘 다 사용자가 고른 곳이면 예외)


WEIGHTS = Weights()
LIMITS = Limits()

DEFAULT_DAY_START = "11:00"  # 10시는 문 연 곳이 적어 첫 장소까지 기다리는 코스가 많았다
# 종료 시각을 말하지 않았을 때. 22시는 하루가 길어 늦게까지 끌려다니는 코스가 됐다. "저녁까지"(20시)보다 한 시간 뒤
DEFAULT_DAY_END = "21:00"

LLM_MODE = os.getenv("ROUTEFIT_LLM", "auto").strip().lower()
LLM_PROVIDER = os.getenv("ROUTEFIT_LLM_PROVIDER", "gemini").strip().lower()
# 비우면 제공자 기본 모델 (llm.PROVIDERS). 쉼표로 여러 개 적으면 앞에서부터 시도한다.
LLM_MODEL = os.getenv("ROUTEFIT_LLM_MODEL", "").strip()
# auto: OPENAI_API_KEY 가 있으면 OpenAI 임베딩 API, 없으면 sentence-transformers, 그것도 없으면 해싱
EMBEDDER = os.getenv("ROUTEFIT_EMBEDDER", "auto").strip().lower()
OPENAI_EMBED_MODEL = os.getenv("ROUTEFIT_OPENAI_EMBED_MODEL", "text-embedding-3-large").strip()
SBERT_MODEL = os.getenv("ROUTEFIT_SBERT_MODEL", "jhgan/ko-sroberta-multitask").strip()
DEFAULT_PLANNER = os.getenv("ROUTEFIT_PLANNER", "greedy").strip().lower()

# 비우면 data/routefit.db (SQLite). PostgreSQL: postgresql+psycopg://user:pass@host:5432/db
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{DATA_DIR / 'routefit.db'}"
# 설정하면 /api/admin/* 요청에 X-Admin-Token 헤더가 필요하다. 비우면 누구나 수정 가능(로컬 시연용).
ADMIN_TOKEN = os.getenv("ROUTEFIT_ADMIN_TOKEN", "").strip()
# /api/plan 요청 제한: 접속 주소 하나당 1분에 이 횟수까지. 0 이면 제한 없음.
PLAN_RATE_PER_MIN = int(os.getenv("ROUTEFIT_PLAN_RATE", "20") or 0)
# 배포 환경에서 리버스 프록시 뒤에 있으면 true (X-Forwarded-For 로 접속 주소를 판단)
TRUST_PROXY = os.getenv("ROUTEFIT_TRUST_PROXY", "false").strip().lower() == "true"
# 카카오모빌리티 길찾기 REST API 키 (python -m routefit.travel 로 이동시간을 채울 때만 필요)
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()
# SK open API TMAP 대중교통 앱 키 (python -m routefit.travel --transit 로 대중교통 이동시간을 채울 때만 필요)
TMAP_APP_KEY = os.getenv("TMAP_APP_KEY", "").strip()
# 카카오맵 JavaScript 키. 화면에 그대로 내려가는 공개용 키이며, 카카오 콘솔에 등록한 사이트 도메인에서만 동작한다.
# 비워 두면 코스 지도는 OpenStreetMap 으로 그린다.
KAKAO_JS_KEY = os.getenv("KAKAO_JS_KEY", "").strip()
