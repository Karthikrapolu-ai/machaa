"""Launch the dedicated Chromium profile and read a public page."""

import asyncio

import pytest

from machaa.browser.workspace import PlaywrightWorkspace
from machaa.core.service import TaskService

pytestmark = pytest.mark.browser


async def _wait(service: TaskService, task_id: str) -> dict:
    for _ in range(180):
        current = service.get(task_id)
        if current["status"] not in {"queued", "running"}:
            return current
        await asyncio.sleep(0.5)
    raise AssertionError(service.get(task_id))


async def test_visit_example_saves_text_and_a_png(settings):
    service = TaskService(settings, PlaywrightWorkspace)
    created = await service.submit("Visit https://example.com and extract the page text")
    finished = await _wait(service, created["id"])
    report = service.artifact(finished["id"], "report")
    report_text = report.read_text(encoding="utf-8") if report else ""
    assert finished["status"] == "completed", finished["summary"] + "\n" + report_text[:1500]
    assert "Example Domain" in report_text
    assert finished["page_url"].startswith("https://example.com")
    screenshot = service.artifact(finished["id"], "screenshot")
    assert screenshot is not None
    assert screenshot.read_bytes().startswith(b"\x89PNG")
    profile = settings.browser_profile_dir.resolve()
    assert profile.is_dir()
    assert str(profile).startswith(str(settings.data_dir.resolve()))
    assert "google-chrome" not in str(profile).lower()
