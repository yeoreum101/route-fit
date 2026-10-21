import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(snippet: str) -> str:
    out = subprocess.run([sys.executable, "-c", textwrap.dedent(snippet)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_server_starts_and_explains_when_ui_is_not_built():
    # 화면을 빌드하지 않은 환경(fe/dist 없음)에서도 서버·API 는 동작하고, 화면 자리에 빌드 안내가 나온다.
    out = _run(
        """
        import os, tempfile
        os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mkdtemp() + "/t.db"
        os.environ["ROUTEFIT_LLM"] = "off"
        from pathlib import Path
        from routefit import config
        config.WEB_DIR = Path("/nonexistent/fe/dist")
        from fastapi.testclient import TestClient
        from routefit.api import app
        c = TestClient(app)
        page = c.get("/")
        print(page.status_code, "npm run build" in page.text, c.get("/stats.html").status_code,
              c.get("/api/health").status_code, c.get("/api/nope").status_code, c.get("/api/nope").headers["content-type"][:16])
        """
    )
    assert out == "503 True 503 200 404 application/json"
