"""Dashboard acceptance for a social post when Gemini is a labelled stand-in."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

SOCIAL = (
    "Machaa, prepare an Instagram content document for Vistaara Interiors "
    "about affordable premium-looking 2BHK interiors. Research design ideas, "
    "find a suitably licensed reference image, and create 3 captions with hashtags."
)
ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_health(port: int, proc: subprocess.Popen, log_path: Path) -> None:
    import urllib.request

    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(log_path.read_text(encoding="utf-8")[-4000:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(log_path.read_text(encoding="utf-8")[-4000:])


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return xml.replace("<", "\n")


async def test_instagram_content_document_on_the_dashboard(tmp_path):
    from playwright.async_api import async_playwright

    port = _free_port()
    data = tmp_path / "data"
    log_path = tmp_path / "server.log"
    env = os.environ.copy()
    env.pop("GEMINI_API_KEY", None)
    env.update(
        {
            "MACHAA_HOST": "127.0.0.1",
            "MACHAA_PORT": str(port),
            "MACHAA_DATA_DIR": str(data),
            "MACHAA_BROWSER_PROFILE": str(data / "browser-profile"),
            "MACHAA_HEADLESS": "true",
            "MACHAA_CHROMIUM_NO_SANDBOX": "true",
            "MACHAA_TASK_TIMEOUT_SECONDS": "120",
            "GEMINI_API_KEY": "",
            "MACHAA_GEMINI_FIXTURE": "1",
            "MACHAA_BRAVE_SEARCH_API_KEY": "",
            "MACHAA_GOOGLE_SEARCH_API_KEY": "",
            "MACHAA_GOOGLE_SEARCH_CX": "",
        }
    )
    log_handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "machaa"],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_health(port, proc, log_path)
        async with async_playwright() as playwright:
            dashboard = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(tmp_path / "dashboard-profile"),
                headless=True,
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = dashboard.pages[0] if dashboard.pages else await dashboard.new_page()
            await page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
            await page.locator("[data-testid='instruction']").fill(SOCIAL)
            await page.locator("[data-testid='send']").click()
            await page.wait_for_function(
                """() => {
                    const status = document.querySelector("[data-testid='task-status']");
                    return status && status.textContent === "Completed";
                }""",
                timeout=120000,
            )
            summary = await page.locator("[data-testid='task-summary']").first.inner_text()
            assert "Vistaara" in summary
            assert "stand-in" in summary
            plan = await page.locator("[data-testid='plan']").first.text_content()
            assert plan == "Plan"
            await page.locator("[data-testid='screenshot']").first.wait_for(timeout=10000)
            assert await page.locator("[data-testid='document']").count() == 1
            async with page.expect_download() as download_info:
                await page.locator("[data-testid='document']").click()
            download = await download_info.value
            saved = tmp_path / "vistaara.docx"
            await download.save_as(str(saved))
            text = _docx_text(saved)
            assert "Vistaara Interiors" in text
            assert "Instagram" in text
            assert text.count("Hashtags:") >= 3
            assert "#2BHK" in text
            reusable = "Licence:" in text and "placeholder" not in text.lower()
            placeholder = "placeholder" in text.lower() and "not a photograph" in text.lower()
            assert reusable or placeholder
            evidence = Path("/opt/cursor/artifacts")
            if evidence.is_dir():
                await page.screenshot(
                    path=str(evidence / "day2_social_dashboard.png"),
                    full_page=True,
                )
                target = evidence / "day2_social_vistaara.docx"
                target.write_bytes(saved.read_bytes())
            await dashboard.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_handle.close()
