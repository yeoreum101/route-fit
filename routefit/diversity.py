"""인기 장소 쏠림 측정: 정해 둔 여러 문장으로 코스를 만들어, AI 추천 장소가 얼마나 반복되는지 잰다.

    python -m routefit.diversity            # QUERIES 로 새로 만들어 잰다 (LLM·TMAP 없이, 저장은 임시 DB)
    python -m routefit.diversity --saved    # DB 에 저장된 코스로 잰다

지표
- 등장률: 그 장소가 AI 추천으로 들어간 코스 수 / 코스 수. 가장 높은 곳이 쏠림의 대표값
- 상위 5곳 점유율: AI 추천 자리 전체 중 가장 자주 나온 5곳이 차지한 비율
- 사용한 장소 비율: AI 추천으로 한 번이라도 나온 장소 수 / 후보 장소 수
"""
import argparse
import collections
import os
import tempfile
from pathlib import Path

# 문장마다 취향·동행·시간이 다르게. 같은 장소가 계속 나오면 쏠림이다
QUERIES = [
    "연인이랑 조용하고 아늑한 데이트, 맛있는 거 먹고 디저트 카페도 가고 싶어",
    "친구랑 동명동에서 맛집이랑 카페 투어",
    "혼자 조용히 전시 보고 책 읽고 싶어",
    "부모님 모시고 시장 구경이랑 한식",
    "아이랑 주말에 산책하고 체험할 수 있는 곳",
    "5·18 역사 공부하는 하루",
    "사진 찍기 좋은 레트로한 골목 위주로",
    "비 오는 날 실내에서만 놀고 싶어",
    "저녁에 술 한잔하고 야경 보고 싶어",
    "공방 체험하고 소품샵 구경",
    "오후 2시부터 저녁까지 가볍게 카페랑 산책",
    "점심 먹고 영화 한 편 보고 싶어",
    "양림동 쪽 한옥이랑 근대 건축 구경",
    "예산 3만원으로 알차게",
    "친구랑 쇼핑하고 길거리 음식 먹기",
    "연인이랑 저녁 데이트, 분위기 좋은 양식집",
    "혼자 여행 왔어. 광주다운 곳 위주로",
    "가족이랑 맛집 두 군데랑 구경거리",
    "전시랑 미술관 많이 보고 싶어",
    "조용한 카페에서 오래 쉬고 싶어",
    "로컬 맛집이랑 전통시장",
    "아침 일찍부터 부지런히 많이 돌아다니고 싶어",
    "저녁즘에 돌아갈 거야. 가볍게 구경하고 밥 먹기",
    "밤늦게까지 놀 거야",
    "서점이랑 소품샵 돌기",
]


def _stats(courses: list[list[str]], n_candidates: int) -> dict:
    count = collections.Counter(name for ai in courses for name in set(ai))
    slots = sum(len(ai) for ai in courses)
    top5 = sum(k for _, k in count.most_common(5))
    return {
        "courses": len(courses),
        "count": count,
        "top_rate": count.most_common(1)[0][1] / len(courses) if count else 0.0,
        "top5_share": top5 / slots if slots else 0.0,
        "coverage": len(count) / n_candidates if n_candidates else 0.0,
    }


def report(stats: dict, top: int = 12) -> str:
    n = stats["courses"]
    lines = [f"코스 {n}개 | 최다 등장률 {stats['top_rate']:.0%} | 상위 5곳 점유율 {stats['top5_share']:.0%} | 사용한 장소 {stats['coverage']:.0%}"]
    lines += [f"  {k:>2}/{n} ({k / n:4.0%})  {name}" for name, k in stats["count"].most_common(top)]
    return "\n".join(lines)


def measure(queries: list[str] = QUERIES, planner: str = "ortools", rounds: int = 1) -> dict:
    """queries 를 rounds 번 돌린다. 만든 코스는 (임시) DB 에 쌓여, 쏠림 감점은 앞서 만든 코스의 등장률로 매겨진다."""
    from .data import load_places
    from .models import PlanRequest
    from .pipeline import make_course

    courses = []
    for _ in range(rounds):
        for q in queries:
            c = make_course(PlanRequest(query=q, planner=planner))
            courses.append([s.name for s in c.stops if s.kind == "ai"])
    return _stats(courses, len(load_places()))


def measure_saved() -> dict:
    from sqlalchemy import select

    from . import db
    from .data import load_places

    with db.session() as s:
        rows = list(s.scalars(select(db.CourseRow)))
    courses = [[st["name"] for st in (r.course or {}).get("stops", []) if st["kind"] == "ai"] for r in rows]
    return _stats([c for c in courses if c], len(load_places()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--saved", action="store_true", help="DB 에 저장된 코스로 잰다")
    ap.add_argument("--planner", default="ortools")
    ap.add_argument("--rounds", type=int, default=1, help="문장 세트를 몇 번 돌릴지(쓸수록 쏠림 감점이 쌓인다)")
    ap.add_argument("--popularity", type=float, help="쏠림 감점 가중치(ROUTEFIT_POPULARITY). 0 이면 끈다")
    args = ap.parse_args()
    if args.popularity is not None:
        os.environ["ROUTEFIT_POPULARITY"] = str(args.popularity)
    if args.saved:
        print(report(measure_saved()))
    else:
        # 잴 때 만든 코스가 실제 통계에 섞이지 않게 임시 DB 에 저장하고, LLM·TMAP 은 부르지 않는다(같은 결과가 나오게)
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(tempfile.mkdtemp(prefix="routefit-div-")) / "d.db").as_posix()
        os.environ["ROUTEFIT_LLM"] = "off"
        os.environ["TMAP_APP_KEY"] = ""
        print(report(measure(planner=args.planner, rounds=args.rounds)))
