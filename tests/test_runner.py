"""Step limit, timeout, stop, and a completed research task with a fake browser."""

import asyncio
from pathlib import Path

from machaa.config import Settings
from machaa.core.service import TaskService
from tests.fakes import FakeBrowser

ACCEPTANCE = "Open Google and search for simple 2BHK interior design ideas"


def _service(settings: Settings, browser_factory, **changes) -> TaskService:
    if changes:
        settings = Settings(**{**settings.__dict__, **changes})
        settings.ensure_dirs()
    return TaskService(settings, browser_factory)


async def _wait(service: TaskService, task_id: str) -> dict:
    for _ in range(100):
        current = service.get(task_id)
        if current["status"] not in {"queued", "running"}:
            return current
        await asyncio.sleep(0.05)
    raise AssertionError(service.get(task_id))


async def test_fake_search_saves_a_report_and_screenshot(settings):
    FakeBrowser.launched = 0
    service = _service(settings, FakeBrowser)
    created = await service.submit(ACCEPTANCE)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "completed"
    assert "2BHK" in finished["summary"]
    assert finished["has_screenshot"] is True
    assert finished["has_report"] is True
    assert finished["page_url"].startswith("https://www.google.com/search?")
    assert [step["status"] for step in finished["steps"]] == ["completed"] * 4
    report = service.artifact(finished["id"], "report")
    assert report is not None
    text = report.read_text(encoding="utf-8")
    assert "simple 2BHK interior design ideas" in text
    assert "https://example.com/ideas" in text
    assert "MACHAA research report" in text
    screenshot = service.artifact(finished["id"], "screenshot")
    assert screenshot is not None
    assert screenshot.read_bytes().startswith(b"\x89PNG")
    assert FakeBrowser.launched == 1
    notes = service.memory.search("2BHK")
    assert notes


async def test_stop_between_steps(settings):
    class SlowBrowser(FakeBrowser):
        async def search_google(self, query: str) -> dict:
            await asyncio.sleep(1)
            return await FakeBrowser.search_google(self, query)

    service = _service(settings, SlowBrowser)
    created = await service.submit("search for lamps")
    for _ in range(50):
        if service.get(created["id"])["status"] == "running":
            break
        await asyncio.sleep(0.02)
    stopped = service.stop(created["id"])
    assert stopped["stop_requested"] is True
    finished = await _wait(service, created["id"])
    assert finished["status"] == "stopped"


async def test_timeout_fails_the_task(settings):
    class StuckBrowser(FakeBrowser):
        async def search_google(self, query: str) -> dict:
            await asyncio.sleep(2)
            return await FakeBrowser.search_google(self, query)

    service = _service(settings, StuckBrowser, task_timeout_seconds=0.3)
    created = await service.submit("search for lamps")
    finished = await _wait(service, created["id"])
    assert finished["status"] == "failed"
    assert "too long" in finished["summary"]


async def test_step_limit_stops_extra_actions(settings):
    service = _service(settings, FakeBrowser, max_steps=2)
    created = await service.submit("search for lamps")
    finished = await _wait(service, created["id"])
    assert finished["status"] == "failed"
    assert "step limit" in finished["summary"]
    assert len(finished["steps"]) == 2


def test_artifact_escape_is_not_served(settings):
    service = _service(settings, FakeBrowser)
    created = service.store.create("Visit https://example.com")
    service.store.finish(
        created.id,
        status="completed",
        summary="Done.",
        screenshot_path="/etc/passwd",
        report_path=str(Path("/etc/hostname")),
    )
    assert service.artifact(created.id, "screenshot") is None
    assert service.artifact(created.id, "report") is None
