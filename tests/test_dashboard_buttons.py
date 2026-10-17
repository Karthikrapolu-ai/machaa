"""The real dashboard in headless Chrome, with a fake microphone."""

from __future__ import annotations

import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from machaa.config import Settings
from machaa.main import create_app
from tests.fakes import ExplodingBrowser

pytest.importorskip("playwright")

PORT = 8795


def test_buttons_work_with_a_fake_microphone(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "machaa.api.routes.transcribe_audio",
        lambda data, **_kwargs: "words from the recording",
    )
    settings = Settings(
        host="127.0.0.1",
        port=PORT,
        data_dir=tmp_path,
        browser_profile_dir=tmp_path / "browser-profile",
        artifacts_dir=tmp_path / "artifacts",
        database_path=tmp_path / "machaa.sqlite3",
        max_steps=4,
        task_timeout_seconds=20,
        navigation_timeout_ms=20000,
        headless=True,
        chromium_no_sandbox=True,
    )
    settings.ensure_dirs()
    app = create_app(settings, ExplodingBrowser)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise AssertionError("dashboard did not start")

    errors: list[str] = []
    try:
        _exercise(errors)
    finally:
        server.should_exit = True
    assert errors == [], errors


def _exercise(errors: list[str]) -> None:
    init = """
      (() => {
        class FakeSpeech {
          start() {
            window.__speech = this;
            window.setTimeout(() => {
              if (this.onerror && window.__speechMode === "network") {
                this.onerror({ error: "network" });
              }
            }, 30);
          }
          stop() {}
          abort() {}
        }
        const define = (name) => {
          try { delete window[name]; } catch (error) {}
          Object.defineProperty(window, name, { configurable: true, writable: true, value: FakeSpeech });
        };
        define("SpeechRecognition");
        define("webkitSpeechRecognition");
      })();
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ],
        )
        page = browser.new_page(viewport={"width": 1100, "height": 800})
        page.add_init_script(init)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        response = page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
        assert response is not None
        assert "no-store" in (response.headers.get("cache-control") or "")
        assert page.get_by_test_id("build-label").inner_text().startswith("v0.6.0")
        assert page.evaluate("() => window.isSecureContext") is True
        assert page.evaluate("() => location.origin === 'http://127.0.0.1:8795'") is True
        assert "/assets/app.js?v=" in (page.content())
        assert page.get_by_test_id("page-error").is_hidden()

        page.get_by_test_id("talk").click()
        page.get_by_test_id("recording").wait_for()
        page.wait_for_function("() => window.__speech")
        page.evaluate(
            """() => {
              const result = [{ transcript: "hello vistaara" }];
              result.isFinal = true;
              window.__speech.onresult({ resultIndex: 0, results: [result] });
            }"""
        )
        assert page.get_by_test_id("instruction").input_value() == "hello vistaara"
        _shot(page, "day6-mic-live.png")
        page.get_by_test_id("recording-stop").click()
        page.wait_for_function("() => document.querySelector('[data-testid=recording]').hidden")
        assert page.get_by_test_id("instruction").input_value() == "hello vistaara"
        assert page.get_by_test_id("recording-timer").inner_text() == "00:00"
        page.wait_for_timeout(1200)
        assert page.get_by_test_id("recording-timer").inner_text() == "00:00"

        page.get_by_test_id("instruction").fill("")
        page.evaluate("() => { window.__speech = null; window.__speechMode = 'network'; }")
        page.get_by_test_id("talk").click()
        page.get_by_test_id("recording").wait_for()
        page.get_by_test_id("mic-status").get_by_text("Stop will turn the recording into text").wait_for()
        page.wait_for_timeout(400)
        page.get_by_test_id("recording-stop").click()
        page.wait_for_function("() => document.querySelector('[data-testid=recording]').hidden")
        page.wait_for_timeout(1500)
        heard = page.get_by_test_id("instruction").input_value()
        status = page.get_by_test_id("mic-status").inner_text()
        assert heard == "words from the recording", (heard, status)
        assert page.get_by_test_id("recording-timer").inner_text() == "00:00"

        page.get_by_test_id("instruction").fill("")
        page.evaluate("() => { window.__speech = null; window.__speechMode = ''; }")
        page.get_by_test_id("talk").click()
        page.get_by_test_id("recording").wait_for()
        page.wait_for_function("() => window.__speech")
        page.evaluate(
            """() => {
              const result = [{ transcript: "buy an image using my credit card" }];
              result.isFinal = true;
              window.__speech.onresult({ resultIndex: 0, results: [result] });
            }"""
        )
        page.get_by_test_id("recording-send").click()
        page.locator("[data-testid='task-status'][data-status='blocked']").wait_for(timeout=10000)
        page.wait_for_function("() => document.querySelector('[data-testid=recording]').hidden")

        page.get_by_test_id("settings").locator("summary").click()
        page.get_by_test_id("desktop-control").check()
        assert page.get_by_test_id("desktop-control").is_checked()
        page.get_by_test_id("test-microphone").click()
        diagnostic = page.get_by_test_id("mic-diagnostic")
        diagnostic.wait_for()
        text = diagnostic.inner_text()
        assert "Speech engine:" in text
        assert "Mic level:" in text
        assert "secure context" in text
        assert page.get_by_test_id("page-error").is_hidden()
        _shot(page, "day6-mic-test.png", full_page=True)
        browser.close()


def _shot(page, name: str, full_page: bool = False) -> None:
    folder = Path("/opt/cursor/artifacts")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / name), full_page=full_page)
    except OSError:
        return
