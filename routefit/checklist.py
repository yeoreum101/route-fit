"""현장조사 채점 체크리스트 (data/checklist.json).

속성(광주다움·상권 연계성·체류 유도성)마다 예/아니오 항목 4개, 점수 = 1 + 항목 값의 합 (1~5).
- 자동 항목: 장소 정보(체류시간·태그·영업시간·지출)로 계산한다. 아래 AUTO_RULES.
- 수동 항목: 팀원이 각자 체크한다. 항목 값 = 체크한 사람 비율 (2명 중 1명이면 0.5 → 불일치).
체크리스트를 한 명도 안 낸 장소는 직접 입력한 3속성 점수를 그대로 쓴다.
"""
import json
from functools import lru_cache
from typing import Callable

from .config import DATA_DIR
from .models import Place, to_min

AUTO_RULES: dict[str, Callable[[Place], bool]] = {
    "cost_gt_0": lambda p: p.cost > 0,
    "stay_min_ge_60": lambda p: p.stay_min >= 60,
    "activity_tags_ge_2": lambda p: len(p.tags.get("activity", [])) >= 2,
    "close_after_19": lambda p: to_min(p.close) > 19 * 60,
}


@lru_cache
def definition() -> dict:
    with open(DATA_DIR / "checklist.json", encoding="utf-8") as f:
        data = json.load(f)
    for item in data["items"]:
        if item.get("auto") and item["auto"] not in AUTO_RULES:
            raise ValueError(f"checklist.json: 없는 자동 규칙 '{item['auto']}' ({item['key']})")
    return data


def manual_keys() -> list[str]:
    return [i["key"] for i in definition()["items"] if not i.get("auto")]


def validate_checks(checks: dict[str, bool]) -> dict[str, bool]:
    unknown = set(checks) - set(manual_keys())
    if unknown:
        raise ValueError(f"직접 체크할 수 없는 항목: {', '.join(sorted(unknown))} (없는 항목이거나 자동 항목)")
    return {k: bool(checks.get(k, False)) for k in manual_keys()}


def evaluate(place: Place, sheets: list[dict]) -> dict:
    """sheets: [{"rater", "checks": {key: bool}}]. 항목별 값·속성 점수·지역상권 여부."""
    items = []
    for item in definition()["items"]:
        if item.get("auto"):
            value = float(AUTO_RULES[item["auto"]](place))
            votes = {}
        else:
            votes = {s["rater"]: bool(s["checks"].get(item["key"], False)) for s in sheets}
            value = sum(votes.values()) / len(votes) if votes else 0.0
        items.append({
            "key": item["key"],
            "attribute": item["attribute"],
            "auto": bool(item.get("auto")),
            "value": round(value, 3),
            "votes": votes,
            "disagree": 0 < value < 1 and not item.get("auto"),
        })
    scores = {
        a["key"]: round(1 + sum(i["value"] for i in items if i["attribute"] == a["key"]), 2)
        for a in definition()["attributes"]
    }
    by_key = {i["key"]: i["value"] for i in items}
    local = all(by_key[k] >= 0.5 for k in definition()["local_commerce"])
    return {"items": items, "scores": scores, "is_local_commerce": local}
