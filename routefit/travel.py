"""장소 간 실제 이동시간을 길찾기 API 로 채운다 (travel_times 테이블).

    python -m routefit.travel --dry-run              # 호출할 구간 수만 확인
    python -m routefit.travel --transit --limit 10   # 대중교통(TMAP), 비어 있는 구간 중 10개만
    python -m routefit.travel                        # 자동차(카카오), 비어 있는 구간만 채움
    python -m routefit.travel --refresh              # 전부 다시 계산

- 대중교통(--transit): .env 에 TMAP_APP_KEY (SK open API 앱 키, TMAP 대중교통 상품 사용 신청).
  응답의 totalTime 은 걷기+탑승 시간이고 기다리는 시간이 없으므로 평균 대기(BUS_WAIT_MIN)를 더한다.
  Free 는 하루 10건이라 --limit 로 나눠 돌린다. 한도에 걸리면 멈추고, 다음에 돌리면 빈 구간부터 이어서 채운다.
- 자동차: .env 에 KAKAO_REST_API_KEY (카카오 개발자 > 내 애플리케이션 > REST API 키, 카카오모빌리티 사용 설정 필요).
  승차·주차 시간(CAR_OVERHEAD_MIN)을 더한다.
걸어서 갈 거리(도로 거리 1.2km, 약 16분 이하)는 API 를 부르지 않고 지금처럼 도보 추정값을 쓴다.
끝나면 서버를 재시작해야 반영된다(서버는 이동시간을 캐시한다).
"""
import argparse
import logging
import math
import time
from typing import Optional

import httpx
from sqlalchemy import select

from . import config, db
from .data import BUS_WAIT_MIN, CAR_OVERHEAD_MIN, ROAD_DETOUR, WALK_KM, haversine_km, load_anchors, load_places
from .models import Place

log = logging.getLogger(__name__)

API_URL = "https://apis-navi.kakaomobility.com/v1/directions"
TMAP_TRANSIT_URL = "https://apis.openapi.sk.com/transit/routes"


class QuotaExceeded(Exception):
    """하루 사용량을 다 썼다. 남은 구간은 다음에 이어서 채운다."""


def needs_api(a: Place, b: Place) -> bool:
    return haversine_km(a.lat, a.lng, b.lat, b.lng) * ROAD_DETOUR > WALK_KM


def fetch_minutes(client: httpx.Client, a: Place, b: Place) -> Optional[int]:
    """a -> b 자동차 이동시간(분, 승차·주차 포함). 경로가 없으면 None."""
    res = client.get(
        API_URL,
        params={"origin": f"{a.lng},{a.lat}", "destination": f"{b.lng},{b.lat}", "priority": "RECOMMEND"},
    )
    res.raise_for_status()
    route = (res.json().get("routes") or [{}])[0]
    if route.get("result_code") != 0:
        log.warning("%s -> %s 경로 없음: %s", a.id, b.id, route.get("result_msg"))
        return None
    return math.ceil(route["summary"]["duration"] / 60) + CAR_OVERHEAD_MIN


def fetch_transit_minutes(client: httpx.Client, a: Place, b: Place) -> Optional[int]:
    """a -> b 대중교통 이동시간(분, 평균 대기 포함). 경로가 없으면 None. 후보 경로 중 가장 빠른 것을 쓴다."""
    res = client.post(
        TMAP_TRANSIT_URL,
        json={"startX": str(a.lng), "startY": str(a.lat), "endX": str(b.lng), "endY": str(b.lat), "count": 3, "format": "json"},
    )
    if res.status_code in (403, 429):
        raise QuotaExceeded(res.text[:200])
    res.raise_for_status()
    data = res.json()
    itineraries = (data.get("metaData") or {}).get("plan", {}).get("itineraries") or []
    if not itineraries:
        log.warning("%s -> %s 경로 없음: %s", a.id, b.id, data.get("result"))
        return None
    seconds = min(it["totalTime"] for it in itineraries)
    return math.ceil(seconds / 60) + BUS_WAIT_MIN


def pairs(places: list[Place], both_ways: bool) -> list[tuple[Place, Place]]:
    out = []
    for i, a in enumerate(places):
        for b in places[i + 1 :]:
            if needs_api(a, b):
                out.append((a, b))
                if both_ways:
                    out.append((b, a))
    return out


def build(
    client: httpx.Client,
    refresh: bool = False,
    both_ways: bool = False,
    pause_s: float = 0.1,
    mode: str = "car",
    limit: Optional[int] = None,
) -> dict:
    """구간별 이동시간을 저장한다. both_ways=False 면 a->b 결과를 b->a 에도 쓴다(호출 수 절반).
    mode 가 다른 값(예: 자동차)으로 채워진 구간은 빈 구간으로 보고 다시 채운다."""
    fetch = fetch_transit_minutes if mode == "transit" else fetch_minutes
    todo = pairs(load_anchors() + load_places(), both_ways)
    with db.session() as s:
        have = {(r.from_id, r.to_id) for r in s.scalars(select(db.TravelRow).where(db.TravelRow.mode == mode))}
        if not refresh:
            todo = [(a, b) for a, b in todo if (a.id, b.id) not in have]
        remaining = len(todo)
        if limit is not None:
            todo = todo[:limit]
        called = saved = failed = 0
        for n, (a, b) in enumerate(todo, 1):
            called += 1
            try:
                minutes = fetch(client, a, b)
            except QuotaExceeded as e:
                log.warning("사용량 한도에 걸려 멈춥니다 (%d / %d 구간에서): %s", n - 1, len(todo), e)
                break
            except httpx.HTTPError as e:
                log.error("%s -> %s 호출 실패: %s", a.id, b.id, e)
                minutes = None
            if minutes is None:
                failed += 1
                continue
            for x, y in [(a, b)] if both_ways else [(a, b), (b, a)]:
                s.merge(db.TravelRow(from_id=x.id, to_id=y.id, minutes=minutes, mode=mode))
            saved += 1
            if n % 20 == 0:
                s.commit()
                log.info("%d / %d", n, len(todo))
            time.sleep(pause_s)
        s.commit()
    return {"called": called, "saved": saved, "failed": failed, "remaining": remaining - saved}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="API 를 부르지 않고 호출할 구간 수만 출력")
    parser.add_argument("--refresh", action="store_true", help="이미 있는 구간도 다시 계산")
    parser.add_argument("--both-ways", action="store_true", help="왕복을 따로 호출(일방통행 반영, 호출 수 2배)")
    parser.add_argument("--transit", action="store_true", help="자동차(카카오) 대신 대중교통(TMAP)으로 채운다")
    parser.add_argument("--limit", type=int, help="이번에 호출할 최대 구간 수 (TMAP Free 는 하루 10건)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    places = load_anchors() + load_places()
    todo = pairs(places, args.both_ways)
    print(f"장소 {len(places)}곳, 도보 거리를 뺀 API 호출 대상 {len(todo)}구간")
    if args.dry_run:
        return
    if args.transit:
        if not config.TMAP_APP_KEY:
            raise SystemExit(".env 에 TMAP_APP_KEY 를 넣어 주세요.")
        headers, mode = {"appKey": config.TMAP_APP_KEY, "Accept": "application/json"}, "transit"
    else:
        if not config.KAKAO_REST_API_KEY:
            raise SystemExit(".env 에 KAKAO_REST_API_KEY 를 넣어 주세요.")
        headers, mode = {"Authorization": f"KakaoAK {config.KAKAO_REST_API_KEY}"}, "car"
    with httpx.Client(headers=headers, timeout=20) as client:
        print(build(client, refresh=args.refresh, both_ways=args.both_ways, mode=mode, limit=args.limit))
    print("서버를 재시작하면 반영됩니다.")


if __name__ == "__main__":
    main()
