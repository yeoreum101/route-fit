import os
import tempfile
from pathlib import Path

# 테스트는 네트워크·모델 없이 돈다.
os.environ["ROUTEFIT_LLM"] = "off"
os.environ["ROUTEFIT_EMBEDDER"] = "hashing"
# 테스트 실행마다 비어 있는 SQLite 에서 시작한다(첫 접근 때 data/*.json 으로 시드). PostgreSQL 로 돌리려면
# ROUTEFIT_TEST_DATABASE_URL 에 비어 있어도 되는 DB 주소를 준다.
os.environ["ROUTEFIT_ADMIN_TOKEN"] = ""
os.environ["ROUTEFIT_PLAN_RATE"] = "0"  # 요청 제한은 test_rate_limit 에서만 켠다
os.environ["DATABASE_URL"] = os.getenv("ROUTEFIT_TEST_DATABASE_URL") or (
    "sqlite:///" + (Path(tempfile.mkdtemp(prefix="routefit-test-")) / "test.db").as_posix()
)
