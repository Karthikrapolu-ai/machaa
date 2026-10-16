"""Day 3 desktop and voice checks.

The Windows desktop itself is not started here. A stand-in companion
records what would have been asked, and the path and window rules are
the real ones.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from machaa.companion.client import CompanionClient
from machaa.companion.policy import resolve_inside, title_is_our_notepad
from machaa.companion.server import CompanionServer
from machaa.core.errors import CompanionRefused, CompanionUnavailable
from machaa.core.guardian import Guardian
from machaa.core.service import TaskService
from machaa.llm.gemini import QuotaError
from machaa.main import create_app
from machaa.voice.transcribe import is_open_machaa, recordings_in
from tests.fakes import ExplodingBrowser, FakeBrowser

NOTEPAD = "Machaa, open Notepad."
CAPTIONS = "Machaa, write three Instagram caption ideas for Vistaara Interiors in Notepad."
SAVE = "Machaa, save this to my Machaa Documents folder."
CALCULATOR = "Machaa, open Calculator."
SEARCH = "Machaa, open Google and search for modern bedroom interiors."
STOP = "Machaa, stop."
BANK = "Machaa, open my banking application and make a payment."


class ExplodingCompanion:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def configured(self) -> bool:
        return True

    def call(self, action: str, arguments: dict) -> dict:
        self.calls.append(action)
        raise AssertionError(action)

    def set_permission(self, enabled: bool) -> dict:
        return {"ok": True, "enabled": enabled}


class DownCompanion:
    def configured(self) -> bool:
        return False

    def call(self, action: str, arguments: dict) -> dict:
        raise AssertionError(action)

    def set_permission(self, enabled: bool) -> dict:
        return {"ok": True}


class FakeCompanion:
    """Records desktop actions and applies the real folder and window rules."""

    def __init__(self, documents: Path) -> None:
        self.documents = documents
        self.calls: list[str] = []
        self.permission = False
        self.pid = 4242
        self.expected_pid = 4242
        self.title = "Untitled - Notepad"
        self.typed = ""

    def configured(self) -> bool:
        return True

    def set_permission(self, enabled: bool) -> dict:
        self.permission = bool(enabled)
        return {"ok": True, "enabled": self.permission}

    def call(self, action: str, arguments: dict) -> dict:
        if action != "desktop.focus_dashboard" and not self.permission:
            raise CompanionRefused("Desktop control is off on the companion.")
        self.calls.append(action)
        if action == "desktop.open_notepad":
            return {"ok": True, "detail": "Opened Notepad.", "pid": self.pid}
        if action == "desktop.open_calculator":
            return {"ok": True, "detail": "Opened Calculator.", "pid": 7}
        if action == "desktop.open_explorer":
            return {"ok": True, "detail": "Opened File Explorer.", "pid": 8}
        if action == "desktop.type_notepad":
            if not title_is_our_notepad(self.title, self.pid, self.expected_pid):
                raise CompanionRefused(
                    "Machaa refused to type because the front window is not the Notepad it opened."
                )
            self.typed = arguments["text"]
            return {"ok": True, "detail": "Typed into the Notepad Machaa opened."}
        if action == "desktop.save_text":
            path = resolve_inside(self.documents, arguments["filename"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments["text"], encoding="utf-8")
            return {"ok": True, "detail": f"Saved {path.name} in the Machaa Documents folder."}
        if action == "desktop.read_file":
            path = resolve_inside(self.documents, arguments["filename"])
            return {"ok": True, "detail": path.read_text(encoding="utf-8")[:500]}
        if action == "desktop.focus_dashboard":
            return {"ok": True, "detail": "Opened the Machaa dashboard."}
        raise CompanionRefused("The companion refused that action.")


class GateCompanion(FakeCompanion):
    def __init__(self, documents: Path) -> None:
        super().__init__(documents)
        self.started = threading.Event()
        self.release = threading.Event()

    def call(self, action: str, arguments: dict) -> dict:
        if action == "desktop.open_notepad":
            self.calls.append(action)
            self.started.set()
            self.release.wait(timeout=5)
            return {"ok": True, "detail": "Opened Notepad.", "pid": self.pid}
        return super().call(action, arguments)


class EvilPlanner:
    model = "gemini-3.5-flash-lite"
    configured = True
    tokens_used = 0

    def __init__(self) -> None:
        self.calls = 0

    def reset_budget(self) -> None:
        self.tokens_used = 0

    def plan_desktop(self, instruction: str, feedback: str = "", max_steps: int = 8) -> list:
        self.calls += 1
        return [{"tool": "os.system", "arguments": {"cmd": "powershell"}, "label": "run"}]


class QuotaPlanner:
    model = "gemini-3.5-flash-lite"
    configured = True
    tokens_used = 0

    def reset_budget(self) -> None:
        self.tokens_used = 0

    def plan_desktop(self, instruction: str, feedback: str = "", max_steps: int = 8) -> list:
        raise QuotaError("Gemini is busy (HTTP 429). Try again later.")


def _docs(settings) -> Path:
    return settings.data_dir / "Documents" / "Machaa"


def _service(settings, companion, browser=ExplodingBrowser, gemini=None) -> TaskService:
    return TaskService(settings, browser, gemini, companion)


async def _until(service: TaskService, task_id: str, statuses: set[str]) -> dict:
    current = {}
    for _ in range(80):
        current = service.get(task_id)
        if current["status"] in statuses:
            return current
        await asyncio.sleep(0.05)
    raise AssertionError(current)


def test_window_title_must_be_the_notepad_machaa_opened():
    assert title_is_our_notepad("Untitled - Notepad", 5, 5) is True
    assert title_is_our_notepad("vistaara-captions.txt - Notepad", 5, 5) is True
    assert title_is_our_notepad("notes.txt - Notepad++", 5, 5) is False
    assert title_is_our_notepad("Untitled - Notepad", 5, 9) is False
    assert title_is_our_notepad("Administrator: PowerShell", 5, 5) is False


def test_save_path_cannot_leave_the_machaa_folder(tmp_path: Path):
    root = tmp_path / "Machaa"
    root.mkdir()
    saved = resolve_inside(root, "vistaara-captions.txt")
    assert saved.parent == root.resolve()
    outside = tmp_path / "secret.txt"
    outside.write_text("no", encoding="utf-8")
    link = root / "notes.txt"
    link.symlink_to(outside)
    with pytest.raises(CompanionRefused):
        resolve_inside(root, "notes.txt")
    for bad in ("../secret.txt", "secret.exe", "CON.txt", "nested/notes.txt"):
        with pytest.raises(CompanionRefused):
            resolve_inside(root, bad)
    assert outside.read_text(encoding="utf-8") == "no"


def test_guardian_blocks_settings_and_allows_caption_text():
    guardian = Guardian()
    blocked = guardian.review_instruction("Open PowerShell and change system settings")
    assert blocked.allowed is False
    bank = guardian.review_instruction(BANK)
    assert bank.allowed is False
    assert bank.category == "payment"
    typed = guardian.review_tool_call(
        "desktop.type_notepad",
        {"text": "A caption can mention a shop without buying anything."},
    )
    assert typed.allowed is True
    escaped = guardian.review_tool_call(
        "desktop.save_text",
        {"filename": "../secret.txt", "text": "no"},
    )
    assert escaped.allowed is False


def test_open_machaa_phrase():
    assert is_open_machaa("Open Machaa") is True
    assert is_open_machaa("Machaa, open Machaa.") is True
    assert is_open_machaa("open notepad") is False


async def test_notepad_is_blocked_while_desktop_control_is_off(settings):
    companion = ExplodingCompanion()
    service = _service(settings, companion)
    created = await service.submit(NOTEPAD)
    finished = await _until(service, created["id"], {"blocked", "completed", "failed"})
    assert finished["status"] == "blocked"
    assert "Desktop control is off" in finished["summary"]
    assert companion.calls == []


async def test_notepad_calculator_and_search_acceptance(settings):
    companion = FakeCompanion(_docs(settings))
    service = _service(settings, companion, FakeBrowser)
    service.set_desktop(True)
    opened = await service.submit(NOTEPAD)
    finished = await _until(service, opened["id"], {"completed", "failed", "blocked"})
    assert finished["status"] == "completed", finished["summary"]
    assert finished["summary"] == "Opened Notepad."
    calc = await service.submit(CALCULATOR)
    calc_done = await _until(service, calc["id"], {"completed", "failed", "blocked"})
    assert calc_done["status"] == "completed"
    assert calc_done["summary"] == "Opened Calculator."
    found = await service.submit(SEARCH)
    search_done = await _until(service, found["id"], {"completed", "failed", "blocked", "needs_human"})
    assert search_done["status"] == "completed", search_done["summary"]
    assert "modern bedroom interiors" in search_done["summary"]
    assert companion.calls == ["desktop.open_notepad", "desktop.open_calculator"]


async def test_captions_need_approval_and_save_stays_in_the_folder(settings):
    companion = FakeCompanion(_docs(settings))
    service = _service(settings, companion)
    service.set_desktop(True)
    created = await service.submit(CAPTIONS)
    waiting = await _until(service, created["id"], {"needs_approval", "failed", "blocked"})
    assert waiting["status"] == "needs_approval", waiting["summary"]
    assert "Approve" in waiting["summary"]
    assert companion.calls == ["desktop.open_notepad"]
    service.approve(created["id"])
    finished = await _until(service, created["id"], {"completed", "failed", "blocked", "stopped"})
    assert finished["status"] == "completed", finished["summary"]
    assert "stand-in" in finished["summary"]
    assert "#2BHK" in companion.typed
    assert "Vistaara" in companion.typed
    save = await service.submit(SAVE)
    pending = await _until(service, save["id"], {"needs_approval", "failed", "blocked"})
    assert pending["status"] == "needs_approval"
    assert "vistaara-captions.txt" in pending["summary"]
    assert "Machaa" in pending["summary"]
    service.reject(save["id"])
    rejected = await _until(service, save["id"], {"stopped", "failed", "completed"})
    assert rejected["status"] == "stopped"
    assert "did not change anything" in rejected["summary"]
    assert not (_docs(settings) / "vistaara-captions.txt").exists()
    again = await service.submit(SAVE)
    again_wait = await _until(service, again["id"], {"needs_approval", "failed"})
    assert again_wait["status"] == "needs_approval"
    service.approve(again["id"])
    saved = await _until(service, again["id"], {"completed", "failed", "stopped"})
    assert saved["status"] == "completed", saved["summary"]
    written = (_docs(settings) / "vistaara-captions.txt").read_text(encoding="utf-8")
    assert "Vistaara" in written
    assert "#2BHK" in written


async def test_stop_phrase_cancels_a_pending_desktop_action(settings):
    companion = FakeCompanion(_docs(settings))
    service = _service(settings, companion)
    service.set_desktop(True)
    created = await service.submit(CAPTIONS)
    waiting = await _until(service, created["id"], {"needs_approval", "failed"})
    assert waiting["status"] == "needs_approval"
    stopped = await service.submit(STOP)
    assert stopped["id"] == created["id"]
    assert stopped["status"] == "stopped"
    await asyncio.sleep(0.2)
    assert "desktop.type_notepad" not in companion.calls


async def test_stop_during_a_desktop_call_does_not_start_the_next_action(settings):
    companion = GateCompanion(_docs(settings))
    service = _service(settings, companion)
    service.set_desktop(True)
    created = await service.submit(CAPTIONS)
    for _ in range(40):
        if companion.started.is_set():
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(service.get(created["id"]))
    service.stop(created["id"])
    companion.release.set()
    finished = await _until(service, created["id"], {"stopped", "failed", "completed"})
    assert finished["status"] == "stopped"
    assert "desktop.type_notepad" not in companion.calls


async def test_wrong_window_is_not_typed_in(settings):
    companion = FakeCompanion(_docs(settings))
    companion.title = "notes.txt - Notepad++"
    service = _service(settings, companion)
    service.set_desktop(True)
    created = await service.submit(CAPTIONS)
    waiting = await _until(service, created["id"], {"needs_approval", "failed"})
    assert waiting["status"] == "needs_approval"
    service.approve(created["id"])
    finished = await _until(service, created["id"], {"failed", "completed", "stopped"})
    assert finished["status"] == "failed"
    assert "not the Notepad" in finished["summary"]
    assert companion.typed == ""


async def test_companion_down_does_not_claim_notepad_opened(settings):
    service = _service(settings, DownCompanion())
    service.set_desktop(True)
    created = await service.submit(NOTEPAD)
    finished = await _until(service, created["id"], {"failed", "completed", "blocked"})
    assert finished["status"] == "failed"
    assert "not running" in finished["summary"]
    assert "Opened Notepad" not in finished["summary"]


async def test_shell_plan_never_starts_the_companion(settings):
    companion = ExplodingCompanion()
    planner = EvilPlanner()
    service = _service(settings, companion, gemini=planner)
    service.set_desktop(True)
    created = await service.submit(NOTEPAD)
    finished = await _until(service, created["id"], {"failed", "blocked", "completed"})
    assert finished["status"] == "failed", finished["summary"]
    assert planner.calls == 2
    assert companion.calls == []
    assert "shell" in finished["summary"].lower() or "not allowed" in finished["summary"].lower()


async def test_quota_failure_is_shown(settings):
    companion = ExplodingCompanion()
    service = _service(settings, companion, gemini=QuotaPlanner())
    service.set_desktop(True)
    created = await service.submit(NOTEPAD)
    finished = await _until(service, created["id"], {"failed", "blocked", "completed"})
    assert finished["status"] == "failed"
    assert "429" in finished["summary"]
    assert companion.calls == []


async def test_banking_never_reaches_the_companion(settings):
    companion = ExplodingCompanion()
    service = _service(settings, companion)
    service.desktop_enabled = True
    created = await service.submit(BANK)
    assert created["status"] == "blocked"
    assert created["block_reason"]
    assert companion.calls == []


async def test_open_machaa_does_not_require_the_desktop_switch(settings):
    companion = FakeCompanion(_docs(settings))
    service = _service(settings, companion)
    created = await service.submit("Open Machaa")
    finished = await _until(service, created["id"], {"completed", "failed", "blocked"})
    assert finished["status"] == "completed", finished["summary"]
    assert companion.calls == ["desktop.focus_dashboard"]
    assert companion.permission is False


def test_voice_route_does_not_store_audio(settings, monkeypatch):
    monkeypatch.setattr(
        "machaa.api.routes.transcribe_audio",
        lambda data: "Machaa, open Notepad.",
    )
    client = TestClient(create_app(settings, ExplodingBrowser))
    response = client.post("/api/voice/transcribe", content=b"fake-audio")
    assert response.status_code == 200
    assert response.json()["text"] == "Machaa, open Notepad."
    assert recordings_in(settings.data_dir) == []
    wake = client.post("/api/voice/wake", json={"enabled": True})
    assert wake.status_code == 200
    assert wake.json()["enabled"] is False
    assert "off" in wake.json()["detail"].lower()
    page = client.get("/")
    for test_id in ("talk", "mute", "mic-status", "desktop-control", "wake-word"):
        assert f'data-testid="{test_id}"' in page.text
    script = Path("machaa/web/app.js").read_text(encoding="utf-8")
    assert "speechSynthesis" in script
    assert "getUserMedia" in script
    assert "Hold to talk" in page.text


def test_voice_without_the_optional_program_keeps_typing(settings, monkeypatch):
    monkeypatch.setattr("machaa.voice.transcribe.voice_ready", lambda: False)
    client = TestClient(create_app(settings, ExplodingBrowser))
    response = client.post("/api/voice/transcribe", content=b"fake-audio")
    assert response.status_code == 503
    assert "type" in response.json()["detail"].lower()
    assert recordings_in(settings.data_dir) == []


def test_companion_listens_only_on_this_computer(tmp_path: Path):
    documents = tmp_path / "Machaa"
    server = CompanionServer("local-token", documents, 0)
    with pytest.raises(RuntimeError):
        server.bind("0.0.0.0")
    server.start_background()
    try:
        client = CompanionClient(f"http://127.0.0.1:{server.port}", "local-token")
        with pytest.raises(CompanionRefused):
            client.call("desktop.open_notepad", {})
        client.set_permission(True)
        with pytest.raises(CompanionRefused) as refused:
            client.call("desktop.open_notepad", {})
        assert "Windows" in str(refused.value)
        assert "pretend" in str(refused.value)
        saved = client.call(
            "desktop.save_text",
            {"filename": "vistaara-captions.txt", "text": "hello from machaa"},
        )
        assert saved["ok"] is True
        assert (documents / "vistaara-captions.txt").read_text(encoding="utf-8") == "hello from machaa"
        with pytest.raises(CompanionRefused):
            client.call("desktop.save_text", {"filename": "../secret.txt", "text": "no"})
        assert not (tmp_path / "secret.txt").exists()
        stranger = CompanionClient(f"http://127.0.0.1:{server.port}", "other-token")
        with pytest.raises(CompanionRefused):
            stranger.call("desktop.open_calculator", {})
        missing = CompanionClient("http://127.0.0.1:9", "local-token")
        with pytest.raises(CompanionUnavailable):
            missing.call("desktop.open_calculator", {})
    finally:
        server.shutdown()
