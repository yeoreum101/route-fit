"""장소 간 실제 이동시간을 카카오모빌리티 길찾기 API 로 채운다 (travel_times 테이블).

    python -m routefit.travel --dry-run     # 호출할 구간 수만 확인
    python -m routefit.travel               # 비어 있는 구간만 채움
    python -m routefit.travel --refresh     # 전부 다시 계산

.env 에 KAKAO_REST_API_KEY (카카오 개발자 > 내 애플리케이션 > REST API 키, 카카오모빌리티 사용 설정 필요).
걸어서 갈 거리(직선 1.2km 이하 추정)는 API 를 부르지 않고 지금처럼 도보 추정값을 쓴다.
자동차 기준이므로 승차·주차 시간(CAR_OVERHEAD_MIN)을 더한다. 대중교통 길찾기 API 는 공개돼 있지 않다.
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
from .data import haversine_km, load_anchors, load_places
from .models import Place

log = logging.getLogger(__name__)

API_URL = "https://apis-navi.kakaomobility.com/v1/directions"
WALK_KM = 1.2  # data.travel_minutes 의 도보 기준과 같게
CAR_OVERHEAD_MIN = 5


def needs_api(a: Place, b: Place) -> bool:
    return haversine_km(a.lat, a.lng, b.lat, b.lng) * 1.3 > WALK_KM


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


def pairs(places: list[Place], both_ways: bool) -> list[tuple[Place, Place]]:
    out = []
    for i, a in enumerate(places):
        for b in places[i + 1 :]:
            if needs_api(a, b):
                out.append((a, b))
                if both_ways:
                    out.append((b, a))
    return out


def build(client: httpx.Client, refresh: bool = False, both_ways: bool = False, pause_s: float = 0.1) -> dict:
    """구간별 이동시간을 저장한다. both_ways=False 면 a->b 결과를 b->a 에도 쓴다(호출 수 절반)."""
    todo = pairs(load_anchors() + load_places(), both_ways)
    with db.session() as s:
        have = {(r.from_id, r.to_id) for r in s.scalars(select(db.TravelRow))}
        if not refresh:
            todo = [(a, b) for a, b in todo if (a.id, b.id) not in have]
        saved = failed = 0
        for n, (a, b) in enumerate(todo, 1):
            try:
                minutes = fetch_minutes(client, a, b)
            except httpx.HTTPError as e:
                log.error("%s -> %s 호출 실패: %s", a.id, b.id, e)
                minutes = None
            if minutes is None:
                failed += 1
                continue
            for x, y in [(a, b)] if both_ways else [(a, b), (b, a)]:
                s.merge(db.TravelRow(from_id=x.id, to_id=y.id, minutes=minutes, mode="car"))
            saved += 1
            if n % 20 == 0:
                s.commit()
                log.info("%d / %d", n, len(todo))
            time.sleep(pause_s)
        s.commit()
    return {"called": len(todo), "saved": saved, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="API 를 부르지 않고 호출할 구간 수만 출력")
    parser.add_argument("--refresh", action="store_true", help="이미 있는 구간도 다시 계산")
    parser.add_argument("--both-ways", action="store_true", help="왕복을 따로 호출(일방통행 반영, 호출 수 2배)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    places = load_anchors() + load_places()
    todo = pairs(places, args.both_ways)
    print(f"장소 {len(places)}곳, 도보 거리를 뺀 API 호출 대상 {len(todo)}구간")
    if args.dry_run:
        return
    if not config.KAKAO_REST_API_KEY:
        raise SystemExit(".env 에 KAKAO_REST_API_KEY 를 넣어 주세요.")
    headers = {"Authorization": f"KakaoAK {config.KAKAO_REST_API_KEY}"}
    with httpx.Client(headers=headers, timeout=10) as client:
        print(build(client, refresh=args.refresh, both_ways=args.both_ways))
    print("서버를 재시작하면 반영됩니다.")


if __name__ == "__main__":
    main()
