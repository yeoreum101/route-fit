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
    """추천 점수식: 취향 적합도 + 지역상권 기여도 + 동행 적합도 - 이동 부담 - 빈 시간 - 시간 초과 페널티.

    초기값이며 검증되지 않았다. 중간발표 직후 보정 기간에 내부 테스트로 조정한다.
    """

    taste: float = 1.0  # 취향 적합도 (후보 내 0~1 정규화된 코사인 유사도)
    local: float = 0.6  # 지역상권 기여도 (0~1)
    companion: float = 0.3  # 문장의 동행이 장소의 '어울리는 동행' 태그에 있으면 더한다
    travel_per_min: float = 0.012  # 이동 1분당 감점
    overtime_per_min: float = 0.05  # 종료 희망 시각 초과 1분당 감점
    wait_per_min: float = 0.006  # 일정 사이 빈 시간 1분당 감점 (식당이 식사 시간대를 기다리며 생기는 공백)
    stop_cost: float = 0.3  # 장소 1곳을 추가하려면 넘어야 하는 최소 가치


@dataclass(frozen=True)
class Limits:
    overtime_grace_min: int = 30  # 종료 희망 시각을 이만큼까지는 넘길 수 있다(감점)
    max_ai_stops: int = 6
    category_caps: tuple[tuple[str, int], ...] = (("food", 2), ("cafe", 2), ("night", 1))
    min_cafe_stay: int = 90  # 카페는 이보다 짧게 머물지 않는다 (장소의 머무는 시간이 더 길면 그것을 쓴다)
    # AI 가 고른 식당은 식사 시간대 안에서 시작하고, 한 끼에 한 곳만 넣는다. (이름, 시작 가능 구간, 자정 기준 분)
    meal_windows: tuple[tuple[str, int, int], ...] = (("점심", 11 * 60, 13 * 60 + 30), ("저녁", 17 * 60, 19 * 60 + 30))


WEIGHTS = Weights()
LIMITS = Limits()

DEFAULT_DAY_START = "10:00"
DEFAULT_DAY_END = "22:00"

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
