"""데이터셋 · 요청 · 응답 스키마."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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


HM_PATTERN = r"^\d{1,2}:[0-5]\d$"  # 'HH:MM', 자정을 넘기면 '25:00'


class Place(BaseModel):
    """광주 여행 경험 데이터셋의 장소 1건 (data/places.json, data/anchors.json)."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)
    category: Category
    area: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    description: str = ""
    aliases: list[str] = []
    open: str = Field(default="00:00", pattern=HM_PATTERN)
    close: str = Field(default="24:00", pattern=HM_PATTERN)
    closed_days: list[int] = []  # 0=월 ... 6=일
    stay_min: int = Field(default=60, ge=5, le=600)
    cost: int = Field(default=0, ge=0)  # 1인 예상 지출(원)
    # 현장조사 3속성 (1~5점, 팀원 3인 독립 채점 평균)
    gwangju_ness: float = Field(default=3.0, ge=1, le=5)  # 광주다움
    stay_inducement: float = Field(default=3.0, ge=1, le=5)  # 체류 유도성
    commerce_link: float = Field(default=3.0, ge=1, le=5)  # 상권 연계성
    is_local_commerce: bool = False  # 전통시장·골목상권·로컬카페 여부
    verified: bool = False  # 현장 검증 완료 여부

    @field_validator("closed_days")
    @classmethod
    def _weekdays(cls, v: list[int]) -> list[int]:
        if any(d not in range(7) for d in v):
            raise ValueError("휴무 요일은 0(월)~6(일)이어야 합니다")
        return sorted(set(v))

    @model_validator(mode="after")
    def _hours(self) -> "Place":
        if to_min(self.open) >= to_min(self.close):
            raise ValueError("닫는 시각은 여는 시각보다 늦어야 합니다 (자정을 넘기면 '25:00'처럼 적습니다)")
        return self

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
    id: Optional[str] = None  # 저장된 코스 id (공유 링크 /?course=<id>). 저장에 실패하면 None
    stops: list[Stop]
    summary: str
    metrics: Metrics
    constraints: Constraints
    engine: dict[str, str]  # 실제로 쓰인 parser / embedder / planner / explainer


class CourseSummary(BaseModel):
    id: str
    created_at: datetime
    query: str
    planner: str
    n_places: int
    local_commerce_ratio: float
    score: float


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)


class Feedback(FeedbackIn):
    id: int
    course_id: str
    created_at: datetime


# ---------- 관리자 (현장조사 데이터 입력) ----------

PlaceKind = Literal["candidate", "anchor"]


class PlaceRecord(Place):
    """관리자 API 의 장소. kind: candidate(AI 추천 후보) | anchor(Must Visit 목적지)."""

    kind: PlaceKind = "candidate"
    # 아래는 응답 전용 (입력해도 무시)
    updated_at: Optional[datetime] = None
    n_ratings: int = 0
    local_contribution: Optional[float] = None  # 지역상권 기여도 0~1 (Place.local_score)


class RatingIn(BaseModel):
    rater: str = Field(min_length=1, max_length=50)
    gwangju_ness: float = Field(ge=1, le=5)
    stay_inducement: float = Field(ge=1, le=5)
    commerce_link: float = Field(ge=1, le=5)


class Rating(RatingIn):
    place_id: str
    updated_at: datetime


class TravelTime(BaseModel):
    from_id: str
    to_id: str
    minutes: int = Field(ge=0, le=600)
    mode: Optional[str] = None  # walk | transit | car ...


# ---------- 통계 ----------


class PlannerStats(BaseModel):
    courses: int
    avg_places: float
    avg_ai_places: float
    avg_travel_min: float
    avg_local_commerce_ratio: float
    avg_score: float


class Stats(BaseModel):
    courses: int
    feedback: int
    avg_rating: Optional[float]
    by_planner: dict[str, PlannerStats]
    top_places: list[dict]  # AI 가 가장 많이 추천한 장소 [{"place_id", "name", "count"}]
