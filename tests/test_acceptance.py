"""Day 1 acceptance: search from the dashboard, and block a payment."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

ACCEPTANCE = "Open Google and search for simple 2BHK interior design ideas"
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


async def test_dashboard_search_and_payment_block(tmp_path):
    from playwright.async_api import async_playwright

    port = _free_port()
    data = tmp_path / "data"
    log_path = tmp_path / "server.log"
    env = os.environ.copy()
    env.pop("MACHAA_GEMINI_FIXTURE", None)
    env["GEMINI_API_KEY"] = ""
    env.update(
        {
            "MACHAA_HOST": "127.0.0.1",
            "MACHAA_PORT": str(port),
            "MACHAA_DATA_DIR": str(data),
            "MACHAA_BROWSER_PROFILE": str(data / "browser-profile"),
            "MACHAA_HEADLESS": "true",
            "MACHAA_CHROMIUM_NO_SANDBOX": "true",
            "MACHAA_TASK_TIMEOUT_SECONDS": "120",
            "MACHAA_NAVIGATION_TIMEOUT_MS": "30000",
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
                accept_downloads=False,
                viewport={"width": 1280, "height": 900},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = dashboard.pages[0] if dashboard.pages else await dashboard.new_page()
            await page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
            assert await page.title() == "MACHAA"
            await page.locator("[data-testid='instruction']").fill(ACCEPTANCE)
            await page.locator("[data-testid='send']").click()
            await page.wait_for_function(
                """() => {
                    const status = document.querySelector("[data-testid='task-status']");
                    return status && ["Completed", "Failed", "Blocked", "Needs human"].includes(status.textContent);
                }""",
                timeout=150000,
            )
            status = await page.locator("[data-testid='task-status']").first.text_content()
            summary = await page.locator("[data-testid='task-summary']").first.inner_text()
            report_text = ""
            reports = list((data / "artifacts").glob("*/report.md"))
            if reports:
                report_text = reports[0].read_text(encoding="utf-8")
            shots = list((data / "artifacts").glob("*/screenshot.png"))
            assert shots and shots[0].read_bytes().startswith(b"\x89PNG")
            assert shots[0].stat().st_size > 1000
            await page.locator("[data-testid='screenshot']").wait_for(timeout=10000)
            evidence = Path("/opt/cursor/artifacts")
            if evidence.is_dir():
                shutil.copy(shots[0], evidence / "acceptance_search_results_screenshot.png")
                await page.screenshot(
                    path=str(evidence / "acceptance_search_dashboard.png"),
                    full_page=True,
                )
            assert "simple 2BHK interior design ideas" in report_text
            result_urls = [
                url
                for url in re.findall(r"https://[^\s)>\]]+", report_text)
                if _is_public_result(url)
            ]
            assert len(result_urls) >= 3, report_text[:4000]
            profile = data / "browser-profile"
            assert profile.is_dir()
            assert "google-chrome" not in str(profile)

            await page.locator("[data-testid='instruction']").fill(PAYMENT)
            await page.locator("[data-testid='send']").click()
            await page.wait_for_function(
                """() => [...document.querySelectorAll("[data-testid='task-status']")]
                    .some((node) => node.textContent === "Blocked")""",
                timeout=10000,
            )
            blocked = page.locator("[data-testid='task']").nth(1)
            assert (await blocked.locator("[data-testid='task-status']").text_content()) == "Blocked"
            blocked_summary = await blocked.locator("[data-testid='task-summary']").inner_text()
            assert "blocked" in blocked_summary.lower()
            assert await blocked.locator("[data-testid='screenshot']").count() == 0
            await dashboard.close()
            assert status == "Completed", summary + "\n" + report_text[:2000]
            assert "2BHK" in summary
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_handle.close()


def _is_public_result(url: str) -> bool:
    lowered = url.lower()
    if "google.com/sorry" in lowered or "/sorry/" in lowered:
        return False
    if "duckduckgo.com" in lowered or "google.com/search" in lowered:
        return False
    if "googleapis.com" in lowered or "api.search.brave.com" in lowered:
        return False
    host = lowered.split("/")[2]
    if host == "google.com" or host.endswith(".google.com"):
        return False
    return lowered.startswith("https://")
