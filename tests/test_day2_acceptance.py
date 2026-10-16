"""Dashboard acceptance for Day 2 when no Gemini key is configured."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

WORD = "Write a Word document about simple 2BHK interior design ideas"
PAYMENT = "Buy a sofa and pay with my credit card at checkout"
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


async def test_dashboard_asks_for_the_gemini_key_and_still_blocks_payment(tmp_path):
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
            "GEMINI_API_KEY": "",
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
                accept_downloads=False,
                viewport={"width": 1280, "height": 900},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = dashboard.pages[0] if dashboard.pages else await dashboard.new_page()
            await page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
            banner = page.locator("[data-testid='gemini-setup']")
            await banner.wait_for()
            banner_text = await banner.inner_text()
            assert "GEMINI_API_KEY" in banner_text
            assert "aistudio.google.com/apikey" in banner_text
            assert "start.bat" in banner_text
            await page.locator("[data-testid='instruction']").fill(WORD)
            await page.locator("[data-testid='send']").click()
            await page.wait_for_function(
                """() => {
                    const status = document.querySelector("[data-testid='task-status']");
                    return status && status.textContent === "Needs a key";
                }""",
                timeout=10000,
            )
            summary = await page.locator("[data-testid='task-summary']").first.inner_text()
            assert "GEMINI_API_KEY" in summary
            assert await page.locator("[data-testid='document']").count() == 0
            await page.locator("[data-testid='instruction']").fill(PAYMENT)
            await page.locator("[data-testid='send']").click()
            await page.wait_for_function(
                """() => [...document.querySelectorAll("[data-testid='task-status']")]
                    .some((node) => node.textContent === "Blocked")""",
                timeout=10000,
            )
            evidence = Path("/opt/cursor/artifacts")
            if evidence.is_dir():
                await page.screenshot(
                    path=str(evidence / "day2_dashboard_needs_key.png"),
                    full_page=True,
                )
            await dashboard.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_handle.close()
