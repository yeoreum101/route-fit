"""장소 태그: data/tags.json 의 정해진 목록에서만 고른다.

취향 매칭(임베딩)은 자유 설명 대신 태그로 만든 표준 문장을 쓴다. 쓰는 사람의 문체·단어 선택이
추천을 흔들지 않게 하기 위해서다.
"""
import json
from functools import lru_cache

from .config import DATA_DIR


@lru_cache
def groups() -> list[dict]:
    with open(DATA_DIR / "tags.json", encoding="utf-8") as f:
        return json.load(f)["groups"]


def validate(tags: dict[str, list[str]]) -> dict[str, list[str]]:
    """목록에 없는 값·그룹, 하나만 고르는 그룹에 여러 개를 막는다. 그룹 순서·값 순서를 목록 순서로 맞춘다."""
    by_key = {g["key"]: g for g in groups()}
    unknown = set(tags) - set(by_key)
    if unknown:
        raise ValueError(f"없는 태그 그룹: {', '.join(sorted(unknown))}")
    out = {}
    for key, g in by_key.items():
        chosen = tags.get(key) or []
        bad = [v for v in chosen if v not in g["values"]]
        if bad:
            raise ValueError(f"{g['label']}에 없는 태그: {', '.join(bad)}")
        if not g["multiple"] and len(chosen) > 1:
            raise ValueError(f"{g['label']}은(는) 하나만 고릅니다")
        if chosen:
            out[key] = [v for v in g["values"] if v in chosen]
    return out


def missing_required(tags: dict[str, list[str]]) -> list[str]:
    """비어 있는 필수 그룹 이름. 비어 있어도 저장은 되지만 관리 화면에서 경고한다."""
    return [g["label"] for g in groups() if g["required"] and not tags.get(g["key"])]


def sentence(tags: dict[str, list[str]]) -> str:
    """'할 거리: 사진 / 산책 | 분위기: 조용한 | 공간: 실외 …' 형태의 표준 문장.
    값에 쉼표·마침표를 붙이지 않는다. 글자 단위로 보는 임베딩에서 '술,' 이 '술' 과 다른 말이 되기 때문이다."""
    return " | ".join(f"{g['label']}: {' / '.join(tags[g['key']])}" for g in groups() if tags.get(g["key"]))
