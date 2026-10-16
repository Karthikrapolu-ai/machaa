"""Social posts: the plan is checked before the browser, and the document tells the truth."""

import asyncio
import io
import json
from pathlib import Path

import pytest

from machaa.agents.planner import PlanningError, actions_from_model, validate_actions
from machaa.config import Settings
from machaa.core.guardian import Guardian
from machaa.core.service import TaskService
from machaa.images.licensed import Candidate, ImageResult, find_licensed_image, license_is_reusable
from machaa.llm.fixture import FixtureGemini
from machaa.llm.gemini import GeminiClient, QuotaError, TokenLimitError
from tests.fakes import ExplodingBrowser, FakeBrowser

SOCIAL = (
    "Machaa, prepare an Instagram content document for Vistaara Interiors "
    "about affordable premium-looking 2BHK interiors. Research design ideas, "
    "find a suitably licensed reference image, and create 3 captions with hashtags."
)
PAYMENT = (
    "Prepare an Instagram content document for Vistaara about paying with my credit card at checkout"
)


def _keyed(settings, **changes):
    return Settings(**{**settings.__dict__, "gemini_api_key": "test-key", **changes})


async def _wait(service, task_id: str) -> dict:
    current = service.get(task_id)
    for _ in range(100):
        current = service.get(task_id)
        if current["status"] not in {"queued", "running", "paused"}:
            return current
        await asyncio.sleep(0.05)
    raise AssertionError(current)


def _png(path: Path) -> None:
    from machaa.images.licensed import _write_placeholder_png

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_placeholder_png(path)


def _reusable(query, dest, guardian):
    path = dest / "reference.png"
    _png(path)
    return ImageResult(
        placeholder=False,
        path=path,
        title="Living room",
        artist="Ada Lovelace",
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        source_page="https://commons.wikimedia.org/wiki/File:Room.jpg",
        file_url="https://upload.wikimedia.org/wikipedia/commons/room.jpg",
    )


def _placeholder(query, dest, guardian):
    path = dest / "reference-placeholder.png"
    _png(path)
    return ImageResult(placeholder=True, path=path)


class ShellPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def plan_actions(self, instruction, feedback="", max_steps=8):
        self.calls += 1
        return [{"tool": "os.system", "arguments": {"command": "rm -rf /"}, "label": "Run a shell"}]

    def write_social(self, *args, **kwargs):
        raise AssertionError("the document should not be written")


class PaypalPlanner:
    def plan_actions(self, instruction, feedback="", max_steps=8):
        return [
            {
                "tool": "browser.visit_public_page",
                "arguments": {"url": "https://www.paypal.com/checkout"},
                "label": "Open checkout",
            }
        ]


class EmptyPlanner:
    def plan_actions(self, instruction, feedback="", max_steps=8):
        return []


class RepairPlanner:
    def __init__(self) -> None:
        self.calls = 0
        self.writer = FixtureGemini()

    def plan_actions(self, instruction, feedback="", max_steps=8):
        self.calls += 1
        if self.calls == 1:
            return [{"tool": "os.system", "arguments": {"command": "id"}, "label": "shell"}]
        return self.writer.plan_actions(instruction, feedback, max_steps)

    def write_social(self, *args, **kwargs):
        return self.writer.write_social(*args, **kwargs)

    def reset_budget(self) -> None:
        return None


class Boom(Exception):
    pass


class QuotaPlanner:
    def plan_actions(self, instruction, feedback="", max_steps=8):
        raise QuotaError("Gemini is out of quota (HTTP 429). Resource exhausted.")


class TokenPlanner:
    def plan_actions(self, instruction, feedback="", max_steps=8):
        raise TokenLimitError(
            "This task reached its token limit. Machaa stopped before another Gemini call."
        )


async def test_shell_plan_does_not_start_the_browser(settings):
    planner = ShellPlanner()
    service = TaskService(_keyed(settings), ExplodingBrowser, planner)
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "failed"
    assert "shell" in finished["summary"].lower()
    assert planner.calls == 2
    assert finished["has_document"] is False


async def test_paypal_plan_is_denied_before_the_browser(settings):
    service = TaskService(_keyed(settings), ExplodingBrowser, PaypalPlanner())
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "failed"
    assert "blocked" in finished["summary"].lower()
    assert finished["has_document"] is False


async def test_empty_plan_fails_before_the_browser(settings):
    service = TaskService(_keyed(settings), ExplodingBrowser, EmptyPlanner())
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "failed"
    assert "list of actions" in finished["summary"]


async def test_payment_social_request_is_blocked_before_planning(settings):
    service = TaskService(settings, ExplodingBrowser, ShellPlanner())
    finished = await service.submit(PAYMENT)
    assert finished["status"] == "blocked"
    assert finished["has_document"] is False


async def test_a_rejected_plan_can_be_repaired_once(settings, monkeypatch):
    monkeypatch.setattr("machaa.images.licensed.find_licensed_image", _reusable)
    planner = RepairPlanner()
    service = TaskService(_keyed(settings), FakeBrowser, planner)
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "completed", finished["summary"]
    assert planner.calls == 2
    assert finished["has_document"] is True


async def test_quota_failure_is_reported_and_the_browser_stays_off(settings):
    service = TaskService(_keyed(settings), ExplodingBrowser, QuotaPlanner())
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "failed"
    assert "quota" in finished["summary"].lower()


async def test_token_limit_stops_the_task(settings):
    service = TaskService(_keyed(settings), ExplodingBrowser, TokenPlanner())
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "failed"
    assert "token limit" in finished["summary"].lower()


async def test_attribution_is_written_into_the_document(settings, monkeypatch):
    monkeypatch.setattr("machaa.images.licensed.find_licensed_image", _reusable)
    service = TaskService(_keyed(settings), FakeBrowser, FixtureGemini())
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "completed", finished["summary"]
    assert "stand-in" in finished["summary"]
    assert finished["has_document"] is True
    assert finished["has_screenshot"] is True
    text = _docx_text(service.artifact(created["id"], "document"))
    assert "Vistaara Interiors" in text
    assert "Instagram" in text
    assert "Ada Lovelace" in text
    assert "CC BY 4.0" in text
    assert "https://commons.wikimedia.org/wiki/File:Room.jpg" in text
    assert text.count("Hashtags:") == 3
    assert "#2BHK" in text
    names = [step["label"] for step in finished["steps"]]
    assert names[0] == "Search design ideas"
    assert all(step["status"] == "completed" for step in finished["steps"])


async def test_placeholder_is_labelled_and_not_called_a_photo(settings, monkeypatch):
    monkeypatch.setattr("machaa.images.licensed.find_licensed_image", _placeholder)
    service = TaskService(_keyed(settings), FakeBrowser, FixtureGemini())
    created = await service.submit(SOCIAL)
    finished = await _wait(service, created["id"])
    assert finished["status"] == "completed", finished["summary"]
    text = _docx_text(service.artifact(created["id"], "document"))
    assert "placeholder" in text.lower()
    assert "not a photograph" in text.lower()
    assert "Ada Lovelace" not in text


async def test_missing_key_stops_a_social_request(settings):
    service = TaskService(settings, ExplodingBrowser)
    finished = await service.submit(SOCIAL)
    assert finished["status"] == "needs_key"
    assert "GEMINI_API_KEY" in finished["summary"]


async def test_pause_holds_the_next_step_until_resume(settings, monkeypatch):
    monkeypatch.setattr("machaa.images.licensed.find_licensed_image", _reusable)
    gate = asyncio.Event()
    release = asyncio.Event()

    class GateBrowser(FakeBrowser):
        async def search_google(self, query):
            gate.set()
            await release.wait()
            return await FakeBrowser.search_google(self, query)

    service = TaskService(_keyed(settings, task_timeout_seconds=20), GateBrowser, FixtureGemini())
    created = await service.submit(SOCIAL)
    await asyncio.wait_for(gate.wait(), timeout=5)
    paused = service.pause(created["id"])
    assert paused["pause_requested"] is True
    release.set()
    current = {}
    for _ in range(50):
        current = service.get(created["id"])
        if current["status"] == "paused":
            break
        await asyncio.sleep(0.05)
    assert current["status"] == "paused"
    assert sum(step["status"] == "completed" for step in current["steps"]) == 1
    service.resume(created["id"])
    finished = await _wait(service, created["id"])
    assert finished["status"] == "completed", finished["summary"]


async def test_stop_while_paused_does_not_continue(settings, monkeypatch):
    monkeypatch.setattr("machaa.images.licensed.find_licensed_image", _reusable)
    gate = asyncio.Event()
    release = asyncio.Event()

    class GateBrowser(FakeBrowser):
        async def search_google(self, query):
            gate.set()
            await release.wait()
            return await FakeBrowser.search_google(self, query)

    service = TaskService(_keyed(settings, task_timeout_seconds=20), GateBrowser, FixtureGemini())
    created = await service.submit(SOCIAL)
    await asyncio.wait_for(gate.wait(), timeout=5)
    service.pause(created["id"])
    release.set()
    for _ in range(50):
        if service.get(created["id"])["status"] == "paused":
            break
        await asyncio.sleep(0.05)
    stopped = service.stop(created["id"])
    assert stopped["status"] == "stopped"
    await asyncio.sleep(0.3)
    final = service.get(created["id"])
    assert final["status"] == "stopped"
    assert sum(step["status"] == "completed" for step in final["steps"]) <= 1


def test_too_many_steps_are_rejected():
    raw = [{"tool": "browser.screenshot", "arguments": {}, "label": f"Shot {index}"} for index in range(9)]
    with pytest.raises(PlanningError):
        actions_from_model(raw, max_steps=8)


def test_guardian_denies_a_planned_checkout():
    actions = actions_from_model(
        [
            {
                "tool": "browser.visit_public_page",
                "arguments": {"url": "https://www.paypal.com/checkout"},
                "label": "Pay",
            }
        ],
        max_steps=8,
    )
    with pytest.raises(PlanningError):
        validate_actions(Guardian(), actions, 8)


def test_a_jpeg_without_jfif_is_given_a_header_word_can_read():
    from machaa.images.licensed import _prepare_image

    raw = b"\xff\xd8\xff\xdb" + b"\x00" * 40
    prepared, suffix = _prepare_image(raw)
    assert suffix == ".jpg"
    assert prepared[6:10] == b"JFIF"


def test_reusable_licences_and_rejected_ones():
    assert license_is_reusable("CC0")
    assert license_is_reusable("Public domain")
    assert license_is_reusable("CC BY 4.0")
    assert license_is_reusable("CC BY-SA 4.0")
    assert not license_is_reusable("CC BY-NC 4.0")
    assert not license_is_reusable("CC BY-ND 4.0")
    assert not license_is_reusable("CC BY-NC-SA 4.0")
    assert not license_is_reusable("")


def test_an_nc_only_search_becomes_a_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "machaa.images.licensed._search_commons",
        lambda query: [
            Candidate(
                title="Room",
                artist="Someone",
                license_name="CC BY-NC 4.0",
                license_url="https://creativecommons.org/licenses/by-nc/4.0/",
                source_page="https://commons.wikimedia.org/wiki/File:Room.jpg",
                file_url="https://upload.wikimedia.org/wikipedia/commons/room.jpg",
            )
        ],
    )
    monkeypatch.setattr("machaa.images.licensed._search_openverse", lambda query: [])

    def explode(*args, **kwargs):
        raise AssertionError("an NC image must not be downloaded")

    monkeypatch.setattr("machaa.images.licensed._download", explode)
    result = find_licensed_image("living room", tmp_path, Guardian())
    assert result.placeholder is True
    assert result.path is not None and result.path.is_file()


def test_cc0_is_chosen_ahead_of_nc(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "machaa.images.licensed._search_commons",
        lambda query: [
            Candidate("NC room", "A", "CC BY-NC", "", "https://commons.wikimedia.org/wiki/File:A.jpg", "https://upload.wikimedia.org/a.jpg"),
            Candidate("Free room", "Wilfredor", "CC0", "https://creativecommons.org/publicdomain/zero/1.0/", "https://commons.wikimedia.org/wiki/File:B.jpg", "https://upload.wikimedia.org/b.jpg"),
        ],
    )
    monkeypatch.setattr("machaa.images.licensed._search_openverse", lambda query: [])

    def fake_download(candidate, dest, guardian):
        assert candidate.license_name == "CC0"
        path = dest / "reference.jpg"
        path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
        return path

    monkeypatch.setattr("machaa.images.licensed._download", fake_download)
    result = find_licensed_image("living room", tmp_path, Guardian())
    assert result.reusable is True
    assert result.artist == "Wilfredor"
    assert result.license_name == "CC0"


def test_quota_is_retried_then_reported(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append(request.full_url)
        raise _http_error(429, "Resource exhausted. secret-value")

    monkeypatch.setattr("machaa.llm.gemini.urllib.request.urlopen", fake_urlopen)
    try:
        GeminiClient("secret-value", max_retries=1).draft("Write a note", "notes")
    except QuotaError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected QuotaError")
    assert len(calls) == 2
    assert "quota" in message.lower()
    assert "Resource exhausted" in message
    assert "secret-value" not in message
    assert "[key]" in message


def test_token_limit_stops_the_next_call(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            body = {
                "candidates": [{"content": {"parts": [{"text": json.dumps({
                    "title": "Note",
                    "sections": [{"heading": "One", "paragraphs": ["Hello."]}],
                })}]}}],
                "usageMetadata": {"totalTokenCount": 100},
            }
            return json.dumps(body).encode()

    def fake_urlopen(request, timeout=0):
        calls.append(1)
        return Response()

    monkeypatch.setattr("machaa.llm.gemini.urllib.request.urlopen", fake_urlopen)
    client = GeminiClient("secret-value", max_tokens=50)
    client.draft("Write a note", "notes")
    assert client.tokens_used == 100
    with pytest.raises(TokenLimitError):
        client.draft("Write another note", "notes")
    assert len(calls) == 1


def test_pause_and_resume_routes(settings):
    from fastapi.testclient import TestClient

    from machaa.main import create_app

    app = create_app(settings, FakeBrowser)
    client = TestClient(app)
    created = app.state.service.store.create("Open Google and search for chairs")
    paused = client.post(f"/api/tasks/{created.id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/api/tasks/{created.id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["pause_requested"] is False
    assert resumed.json()["status"] == "queued"


def _docx_text(path: Path) -> str:
    import zipfile

    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return xml.replace("<", "\n")


def _http_error(code: int, message: str):
    import urllib.error

    body = json.dumps({"error": {"code": code, "message": message, "status": "ERROR"}}).encode()
    return urllib.error.HTTPError(
        "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent",
        code,
        "error",
        hdrs=None,
        fp=io.BytesIO(body),
    )

