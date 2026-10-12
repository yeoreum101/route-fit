"""환경 설정과 추천 점수식 가중치."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
WEB_DIR = ROOT / "web"

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Weights:
    """추천 점수식: 취향 적합도 + 지역상권 기여도 - 이동 부담 - 시간 초과 페널티.

    초기값이며 검증되지 않았다. 중간발표 직후 보정 기간에 내부 테스트로 조정한다.
    """

    taste: float = 1.0  # 취향 적합도 (후보 내 0~1 정규화된 코사인 유사도)
    local: float = 0.6  # 지역상권 기여도 (0~1)
    travel_per_min: float = 0.012  # 이동 1분당 감점
    overtime_per_min: float = 0.05  # 종료 희망 시각 초과 1분당 감점
    stop_cost: float = 0.3  # 장소 1곳을 추가하려면 넘어야 하는 최소 가치


@dataclass(frozen=True)
class Limits:
    overtime_grace_min: int = 30  # 종료 희망 시각을 이만큼까지는 넘길 수 있다(감점)
    max_ai_stops: int = 6
    category_caps: tuple[tuple[str, int], ...] = (("food", 2), ("cafe", 2), ("night", 1))


WEIGHTS = Weights()
LIMITS = Limits()

DEFAULT_DAY_START = "10:00"
DEFAULT_DAY_END = "22:00"

LLM_MODE = os.getenv("ROUTEFIT_LLM", "auto").strip().lower()
LLM_PROVIDER = os.getenv("ROUTEFIT_LLM_PROVIDER", "gemini").strip().lower()
# 비우면 제공자 기본 모델 (llm.PROVIDERS). 쉼표로 여러 개 적으면 앞에서부터 시도한다.
LLM_MODEL = os.getenv("ROUTEFIT_LLM_MODEL", "").strip()
EMBEDDER = os.getenv("ROUTEFIT_EMBEDDER", "auto").strip().lower()
SBERT_MODEL = os.getenv("ROUTEFIT_SBERT_MODEL", "jhgan/ko-sroberta-multitask").strip()
DEFAULT_PLANNER = os.getenv("ROUTEFIT_PLANNER", "greedy").strip().lower()
