import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(s.getsockname()[1])


def _wait_for_health(base_url: str, timeout_s: float = 20.0) -> None:
    import urllib.request

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1.5) as res:
                if res.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("uvicorn server did not become healthy in time")


@pytest.mark.ui
def test_agent_editor_playwright_smoke_status_changes_on_click():
    sync_api = pytest.importorskip("playwright.sync_api")
    sync_playwright = sync_api.sync_playwright

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    backend_dir = Path(__file__).resolve().parents[1]

    server = subprocess.Popen(
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=backend_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_for_health(base_url)

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:
                msg = str(exc)
                if "error while loading shared libraries" in msg:
                    pytest.skip("Playwright browser dependencies are missing in this environment")
                raise
            page = browser.new_page()
            page.goto(f"{base_url}/app/agent/1/edit", wait_until="domcontentloaded")

            expect_text = page.locator("h1")
            heading = (expect_text.text_content() or "").strip()
            assert heading in {"에이전트 편집기", "Agent Editor"}

            page.get_by_role("button", name="버전 리포트").click()
            page.wait_for_function(
                "() => document.getElementById('versionStatus')?.textContent?.includes('JWT 토큰을 입력하세요.')"
            )

            page.get_by_role("button", name="조회 조건 초기화").click()
            page.wait_for_function(
                "() => document.getElementById('versionStatus')?.textContent?.includes('조회 조건을 기본값')"
            )
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
