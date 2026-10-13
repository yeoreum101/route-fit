"""코스 생성 요청 수 제한. /api/plan 은 LLM 을 호출하므로, 공개 시연에서 반복 호출로 무료 사용량이 바닥나지 않게 한다.

서버 프로세스 하나 안에서만 센다(메모리). 서버를 여러 대 띄우게 되면 Redis 같은 공용 저장소로 옮긴다.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from . import config

WINDOW_S = 60

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def _client(request: Request) -> str:
    # 프록시(배포 환경) 뒤에 있으면 실제 주소는 X-Forwarded-For 첫 값이다.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and config.TRUST_PROXY:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit_plan(request: Request) -> None:
    """FastAPI 의존성. 1분에 ROUTEFIT_PLAN_RATE 번을 넘으면 429."""
    limit = config.PLAN_RATE_PER_MIN
    if limit <= 0:
        return
    key = _client(request)
    now = time.monotonic()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > WINDOW_S:
            hits.popleft()
        if len(hits) >= limit:
            retry = int(WINDOW_S - (now - hits[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"요청이 너무 많습니다. {retry}초 뒤에 다시 시도해 주세요.",
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)
        if len(_hits) > 10_000:  # 오래된 주소 정리
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW_S]:
                del _hits[k]


def reset() -> None:
    with _lock:
        _hits.clear()
