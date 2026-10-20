"""① 조건 파싱 품질 비교: 정규식 파서와 LLM 파서를 같은 문장으로 돌려 정답과 맞춰 본다.

    python -m routefit.evaluate            # 정규식 파서만 (키 없이)
    python -m routefit.evaluate --llm      # LLM 파서도 (GEMINI_API_KEY 필요)

CASES 에 문장과 정답을 더하면 된다. 정답에 적은 항목만 채점한다(적지 않은 항목은 보지 않는다).
"""
import argparse

from . import llm
from .data import load_anchors, load_places
from .parser import parse_rule_based, sanitize
from .models import ParsedQuery

CASES: list[tuple[str, dict]] = [
    ("일요일 오후 2시부터 밤 9시까지 친구랑 5만원으로 챔필", dict(day_start="14:00", day_end="21:00", budget=50000, weekday=6, companions="친구", must="광주-기아 챔피언스 필드")),
    ("토요일 야구 보기 전에 사진 찍기 좋은 데랑 로컬 맛집 가고 싶어. 예산 10만원", dict(budget=100000, weekday=5, must="광주-기아 챔피언스 필드")),
    ("아이랑 주말에 산책", dict(companions="아이 동반", must=None)),
    ("아이스크림 먹고 싶어", dict(companions=None, must=None)),
    ("데이트 코스 추천해줘", dict(companions="연인")),
    ("오전 10시 반부터 저녁 8시까지 혼자 조용히", dict(day_start="10:30", day_end="20:00", companions="혼자")),
    ("월요일에 전시랑 미술관 보고 싶어", dict(weekday=0, must=None)),
    ("부모님 모시고 갈 건데 시장 구경이랑 한식", dict(companions="가족", must=None)),
    # 규칙 파서가 약한 문장: 장소 이름 없이 일정만 말하거나, 피하고 싶은 유형이 있다
    ("오늘 야구 보러 가는데 앞뒤로 시간 때울 곳", dict(must="광주-기아 챔피언스 필드")),
    ("카페는 싫고 걷는 건 좋아", dict(avoid=["cafe"])),
    ("여섯 시 반에 공연 보고 그 전에 밥", dict(must="광주예술의전당")),
]


def _score(parsed: ParsedQuery, want: dict) -> list[str]:
    """틀린 항목 이름 목록."""
    wrong = []
    for key in ("day_start", "day_end", "budget", "weekday", "companions"):
        if key in want and getattr(parsed, key) != want[key]:
            wrong.append(f"{key}={getattr(parsed, key)!r}(정답 {want[key]!r})")
    if "must" in want:
        got = [m.name for m in parsed.must_visits]
        if got != ([want["must"]] if want["must"] else []):
            wrong.append(f"must={got}")
    if "avoid" in want and sorted(parsed.avoid_categories) != sorted(want["avoid"]):
        wrong.append(f"avoid={parsed.avoid_categories}")
    return wrong


def run(use_llm: bool) -> None:
    from .parser import SYSTEM

    known = load_anchors() + load_places()
    names = "\n".join(f"- {p.name}" + (f" ({p.description})" if p.category == "venue" else "") for p in known)
    totals = {"rule": 0, "llm": 0}
    for query, want in CASES:
        print(f"\n{query}")
        results = {"rule": _score(parse_rule_based(query, known), want)}
        if use_llm:
            raw = llm.structured(SYSTEM, f"[알려진 목적지]\n{names}\n\n[사용자 문장]\n{query}", ParsedQuery)
            results["llm"] = _score(sanitize(raw, known), want) if raw else ["응답 없음"]
        for who, wrong in results.items():
            totals[who] += not wrong
            print(f"  {who:4} {'OK' if not wrong else 'X  ' + ', '.join(wrong)}")
    print(f"\n정답 문장 수 (총 {len(CASES)}): " + ", ".join(f"{k} {v}" for k, v in totals.items() if k == "rule" or use_llm))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    run(ap.parse_args().llm)
