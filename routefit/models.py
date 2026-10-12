"""데이터셋 · 요청 · 응답 스키마."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["sight", "culture", "market", "food", "cafe", "shop", "night", "venue"]

CATEGORY_KO = {
    "sight": "명소·산책",
    "culture": "문화·전시",
    "market": "전통시장",
    "food": "식당",
    "cafe": "카페·디저트",
    "shop": "상점가",
    "night": "야간 콘텐츠",
    "venue": "행사장",
}


def to_min(hm: str) -> int:
    """'18:30' -> 1110. 자정을 넘기는 영업은 '25:00'처럼 적는다."""
    h, m = hm.strip().split(":")
    return int(h) * 60 + int(m)


def to_hm(minutes: int) -> str:
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


class Place(BaseModel):
    """광주 여행 경험 데이터셋의 장소 1건 (data/places.json, data/anchors.json)."""

    id: str
    name: str
    category: Category
    area: str
    lat: float
    lng: float
    description: str = ""
    aliases: list[str] = []
    open: str = "00:00"
    close: str = "24:00"
    closed_days: list[int] = []  # 0=월 ... 6=일
    stay_min: int = 60
    cost: int = 0  # 1인 예상 지출(원)
    # 현장조사 3속성 (1~5점, 팀원 3인 독립 채점 평균)
    gwangju_ness: float = 3.0  # 광주다움
    stay_inducement: float = 3.0  # 체류 유도성
    commerce_link: float = 3.0  # 상권 연계성
    is_local_commerce: bool = False  # 전통시장·골목상권·로컬카페 여부
    verified: bool = False  # 현장 검증 완료 여부

    @property
    def local_score(self) -> float:
        """지역상권 기여도(0~1) = 지역성 + 체류 유도성."""
        locality = (self.gwangju_ness + self.commerce_link) / 2
        return ((locality - 1) / 4 + (self.stay_inducement - 1) / 4) / 2

    @property
    def embed_text(self) -> str:
        return f"{self.name}. {CATEGORY_KO[self.category]}. {self.area}. {self.description}"


# ---------- ① 조건 파싱 결과 ----------


class ParsedMustVisit(BaseModel):
    name: str
    start: Optional[str]  # 'HH:MM' 고정 시작 시각 (경기·공연 시작 등)
    stay_min: Optional[int]


class ParsedQuery(BaseModel):
    """자유 문장에서 뽑아낸 구조화 제약조건. 문장에 없는 값은 null."""

    taste: str  # 취향을 임베딩하기 좋게 정리한 한 문장
    day_start: Optional[str]
    day_end: Optional[str]
    budget: Optional[int]  # 원
    companions: Optional[str]
    weekday: Optional[int]  # 0=월 ... 6=일
    must_visits: list[ParsedMustVisit]
    avoid_categories: list[str]


# ---------- API ----------


class MustVisitInput(BaseModel):
    id: Optional[str] = None  # anchors/places 의 id
    name: Optional[str] = None
    start: Optional[str] = None
    stay_min: Optional[int] = None


class PlanRequest(BaseModel):
    query: str = Field(min_length=1, description="취향·조건 자유 문장")
    must_visits: list[MustVisitInput] = []
    day_start: Optional[str] = None
    day_end: Optional[str] = None
    budget: Optional[int] = None
    planner: Optional[Literal["greedy", "ortools"]] = None


class Constraints(BaseModel):
    taste: str
    day_start: str
    day_end: str
    budget: Optional[int]
    companions: Optional[str]
    weekday: Optional[int]
    avoid_categories: list[str]


class Stop(BaseModel):
    order: int
    place_id: str
    name: str
    kind: Literal["must", "ai"]
    category: Category
    area: str
    lat: float
    lng: float
    arrive: str
    start: str
    end: str
    travel_min: int  # 직전 장소에서의 이동시간
    stay_min: int
    cost: int
    similarity: Optional[float] = None  # 취향 코사인 유사도(원값)
    local_score: Optional[float] = None
    is_local_commerce: bool = False
    reason: str = ""


class Metrics(BaseModel):
    """실증(A/B) 비교 지표."""

    n_places: int
    n_ai_places: int
    stay_min: int  # 계획된 체류시간 합
    travel_min: int
    total_cost: int
    local_commerce_count: int
    local_commerce_ratio: float  # AI 추천 장소 중 지역상권 비율
    score: float


class Course(BaseModel):
    stops: list[Stop]
    summary: str
    metrics: Metrics
    constraints: Constraints
    engine: dict[str, str]  # 실제로 쓰인 parser / embedder / planner / explainer
