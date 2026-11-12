"""데이터셋 · 요청 · 응답 스키마."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from . import tags as tag_vocab

# lodging·etc 는 필수 방문지 검색(카카오)으로 고른 장소에만 쓴다. AI 추천 후보와 장소 관리에는 없다.
Category = Literal["sight", "culture", "market", "food", "cafe", "shop", "night", "venue", "lodging", "etc"]

CATEGORY_KO = {
    "sight": "명소·산책",
    "culture": "문화·전시",
    "market": "전통시장",
    "food": "식당",
    "cafe": "카페·디저트",
    "shop": "상점가",
    "night": "야간 콘텐츠",
    "venue": "행사장",
    "lodging": "숙소",
    "etc": "기타",
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
    description: str = ""  # 한줄 소개. 추천 이유·조건 파싱의 사실 자료로만 쓰고, 취향 매칭에는 쓰지 않는다
    tags: dict[str, list[str]] = {}  # data/tags.json 의 정해진 태그. 취향 매칭은 이것으로 한다
    aliases: list[str] = []
    open: str = Field(default="00:00", pattern=HM_PATTERN)
    close: str = Field(default="24:00", pattern=HM_PATTERN)
    # 브레이크 타임. 이 사이에는 머무를 수 없다(둘 다 적거나 둘 다 비운다)
    break_start: Optional[str] = Field(default=None, pattern=HM_PATTERN)
    break_end: Optional[str] = Field(default=None, pattern=HM_PATTERN)
    closed_days: list[int] = []  # 0=월 ... 6=일
    stay_min: int = Field(default=60, ge=5, le=600)
    cost: int = Field(default=0, ge=0)  # 1인 예상 지출(원)
    # 현장조사 3속성 (1~5점, 팀원 3인 독립 채점 평균)
    gwangju_ness: float = Field(default=3.0, ge=1, le=5)  # 광주다움
    stay_inducement: float = Field(default=3.0, ge=1, le=5)  # 체류 유도성
    commerce_link: float = Field(default=3.0, ge=1, le=5)  # 상권 연계성
    is_local_commerce: bool = False  # 전통시장·골목상권·로컬카페 여부
    verified: bool = False  # 현장 검증 완료 여부

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        return tag_vocab.validate(v)

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
        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("브레이크 타임은 시작과 끝을 함께 적어야 합니다")
        if self.break_start is not None and not (
            to_min(self.open) < to_min(self.break_start) < to_min(self.break_end) < to_min(self.close)
        ):
            raise ValueError("브레이크 타임은 영업시간 안에 있어야 하고, 끝이 시작보다 늦어야 합니다")
        return self

    @property
    def local_score(self) -> float:
        """지역상권 기여도(0~1) = 지역성 + 체류 유도성."""
        locality = (self.gwangju_ness + self.commerce_link) / 2
        return ((locality - 1) / 4 + (self.stay_inducement - 1) / 4) / 2

    @property
    def embed_text(self) -> str:
        """취향 매칭(임베딩)에 넣는 문장. 태그가 있으면 태그 문장만, 없으면 예전처럼 소개 문장을 쓴다."""
        detail = tag_vocab.sentence(self.tags) if self.tags else self.description
        return f"{self.name}. {CATEGORY_KO[self.category]}. {self.area}. {detail}"


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
    skip_meals: list[str]  # 이 코스에서 먹지 않을 끼니: "점심" | "저녁" (예: "점심은 먹고 올 거야")
    avoid_keywords: list[str]  # 싫다고 한 음식·장소 낱말 (예: "훠궈 싫어" -> ["훠궈"])


# ---------- API ----------


class MustVisitInput(BaseModel):
    id: Optional[str] = None  # anchors/places 의 id, 또는 검색으로 고른 카카오 장소 'kakao_<id>'
    name: Optional[str] = None
    start: Optional[str] = None
    stay_min: Optional[int] = None
    # 카카오 장소만: DB 에 없으니 화면이 검색 결과를 그대로 보낸다(공유 링크로 다시 열 때도 쓴다)
    category: Optional[Category] = None
    area: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    description: Optional[str] = None  # 카카오 업종 이름("문화,예술 > 영화,영상 > 영화관"). 같은 종류 추천을 거를 때 쓴다


class PlanRequest(BaseModel):
    """화면에서 입력한 값은 문장에서 읽은 값보다 우선한다. 비워 두면(null) 문장 → 기본값 순으로 쓴다."""

    query: str = Field(min_length=1, description="취향·조건 자유 문장")
    must_visits: list[MustVisitInput] = []
    start: Optional[MustVisitInput] = None  # 출발 위치(선택). 등록된 장소의 id, 또는 카카오로 고른 장소 정보
    exclude_ids: list[str] = []  # 추천에서 뺄 장소(등록된 장소의 id)
    day_start: Optional[str] = Field(default=None, pattern=HM_PATTERN)
    day_end: Optional[str] = Field(default=None, pattern=HM_PATTERN)
    budget: Optional[int] = Field(default=None, ge=0)
    visit_date: Optional[date] = None  # 방문 날짜. 요일을 정해 휴무일을 거른다
    planner: Optional[Literal["greedy", "ortools"]] = None
    # '다른 곳으로 바꾸기' 로 다시 짤 때만: AI 추천 장소를 이 장소들로만 채운다(모두 넣는다). 화면 입력칸은 쓰지 않는다
    only_ids: Optional[list[str]] = None


ConditionSource = Literal["화면", "문장", "기본값", "고정 일정"]


class Constraints(BaseModel):
    taste: str
    day_start: str
    day_end: str
    budget: Optional[int]
    companions: Optional[str]
    weekday: Optional[int]  # 0=월 ... 6=일. 모르면 None 이고 휴무일을 거르지 않는다
    avoid_categories: list[str]
    skip_meals: list[str] = []  # 식당을 넣지 않을 끼니("점심"·"저녁"). 예전에 저장된 코스에는 없다
    avoid_keywords: list[str] = []  # 싫다고 한 낱말. 이 낱말이 들어간 장소는 추천하지 않는다
    excluded_places: list[str] = []  # 화면에서 뺀 장소 이름
    walk_only: bool = False  # 대중교통을 타지 않겠다고 했다: 걸어서 닿는 곳끼리 고른다
    # 문장에서 말한 하루 장소 수(꼭 갈 곳 포함, 출발 위치 제외). "3곳만" -> 3, 3 / "4곳 이상" -> 4, None
    min_places: Optional[int] = None
    max_places: Optional[int] = None
    start_place: Optional[str] = None  # 출발 위치 이름
    visit_date: Optional[date] = None
    must_visits: list[str] = []  # 필수 방문지 이름
    # 각 조건을 어디서 가져왔는지 (day_start, day_end, budget, weekday, must_visits). 화면에 "인식된 조건"으로 보여 준다
    sources: dict[str, ConditionSource] = {}
    notes: list[str] = []  # 화면 입력이 문장을 덮어쓴 경우 등 사용자에게 알릴 것


class Stop(BaseModel):
    order: int
    place_id: str
    name: str
    kind: Literal["start", "must", "ai"]  # start: 출발 위치(머무는 시간 0, 하루 시작 시각)
    category: Category
    area: str
    lat: float
    lng: float
    arrive: str
    start: str
    end: str
    travel_min: int  # 직전 장소에서의 이동시간
    # 직전 장소에서 무엇으로 오는지: walk(도보) | transit(대중교통) | car. 첫 장소와 예전에 저장된 코스는 None
    travel_mode: Optional[Literal["walk", "transit", "car"]] = None
    stay_min: int
    cost: int
    similarity: Optional[float] = None  # 취향 코사인 유사도(원값)
    local_score: Optional[float] = None
    is_local_commerce: bool = False
    reason: str = ""


class Alternative(BaseModel):
    """코스의 AI 추천 장소 하나를 바꿀 때 보여 주는 후보 (같은 역할: 같은 유형, 식당은 같은 끼니)."""

    place_id: str
    name: str
    category: Category
    area: str
    cost: int
    is_local_commerce: bool = False
    similarity: float  # 취향 코사인 유사도(원값)
    taste: float  # 지금 코스의 후보들 안에서 0~1 로 다시 매긴 취향 적합도
    travel_from_prev: Optional[int] = None  # 앞 장소에서 오는 이동시간(분). 첫 장소면 None
    travel_to_next: Optional[int] = None  # 다음 장소까지 이동시간(분). 마지막 장소면 None
    description: str = ""


class SwapIn(BaseModel):
    order: int = Field(ge=1)  # 바꿀 장소의 Stop.order
    place_id: str = Field(min_length=1, max_length=64)


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
    # 이 코스를 만든 요청. 저장된 코스(GET /api/courses/{id})에만 채워, 공유 링크로 열 때 입력칸을 복원한다
    request: Optional[PlanRequest] = None


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
    n_ratings: int = 0  # 체크리스트를 낸 팀원 수. 1명 이상이면 3속성·지역상권 여부는 체크리스트로 계산된다
    missing_tags: list[str] = []  # 비어 있는 필수 태그 그룹 (AI 추천 후보만)
    local_contribution: Optional[float] = None  # 지역상권 기여도 0~1 (Place.local_score)


class ChecklistIn(BaseModel):
    """팀원 1명의 현장조사 체크리스트. checks 는 수동 항목만 (자동 항목은 서버가 계산)."""

    rater: str = Field(min_length=1, max_length=50)
    checks: dict[str, bool] = {}
    evidence: dict[str, str] = {}  # {항목 key: 근거 링크·메모}

    @field_validator("evidence")
    @classmethod
    def _evidence(cls, v: dict[str, str]) -> dict[str, str]:
        if any(len(text) > 300 for text in v.values()):
            raise ValueError("근거는 항목당 300자까지")
        return {k: text.strip() for k, text in v.items() if text.strip()}


class ChecklistSheet(ChecklistIn):
    updated_at: datetime


class ChecklistView(BaseModel):
    sheets: list[ChecklistSheet]
    evaluation: dict  # checklist.evaluate 결과: 항목별 값·팀원별 체크·불일치, 속성 점수, 지역상권 여부


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
