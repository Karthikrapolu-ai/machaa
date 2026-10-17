"""Day 4 and Day 5 checks.

Voice playback, a real microphone, Notepad, and a real Git update on Windows
are listed in the README. These tests cover the decisions those features make.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from machaa.agents.planning import parse_research_request
from machaa.core.errors import CompanionUnavailable
from machaa.core.service import TaskService
from machaa.core.tasks import TaskStore
from machaa.launcher import ensure_docker, prepare_companion, prepare_start, prepare_stop
from machaa.llm.fixture import FixtureGemini
from machaa.main import create_app
from machaa.reports.creative import clean_copy
from machaa.reports.docx_writer import write_social_document
from machaa.update.engine import UpdateFailed, apply_update, migrate_zip
from machaa.update.trust import UpdateRefused, choose_update, is_trusted_update
from machaa.updater import main as updater_main
from tests.fakes import ExplodingBrowser

OFFICIAL = "https://github.com/Karthikrapolu-ai/machaa.git"
BANK = "Buy a sofa and pay with my credit card at checkout"


class RecordingGit:
    def __init__(self, wipe: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.wipe = wipe

    def run(self, args: list[str], cwd: Path) -> str:
        self.calls.append(list(args))
        if args[:1] == ["init"]:
            (cwd / ".git").mkdir(exist_ok=True)
        if self.wipe and args[:1] in (["init"], ["checkout"]):
            env = cwd / ".env"
            if env.exists():
                env.write_text("WIPED", encoding="utf-8")
            history = cwd / "data" / "history.txt"
            if history.exists():
                history.unlink()
            note = cwd / "data" / "documents" / "note.txt"
            if note.exists():
                note.write_text("gone", encoding="utf-8")
        return ""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "machaa-folder"
    (root / "machaa").mkdir(parents=True)
    (root / "machaa" / "__init__.py").write_text("version = '0.5.0'\n", encoding="utf-8")
    (root / ".env").write_text("GEMINI_API_KEY=kept\n", encoding="utf-8")
    (root / "data" / "documents").mkdir(parents=True)
    (root / "data" / "history.txt").write_text("history", encoding="utf-8")
    (root / "data" / "documents" / "note.txt").write_text("caption", encoding="utf-8")
    (root / "data" / "browser-profile").mkdir()
    (root / "data" / "browser-profile" / "cookie").write_text("session", encoding="utf-8")
    return root


def _kept(root: Path) -> None:
    assert (root / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=kept\n"
    assert (root / "data" / "history.txt").read_text(encoding="utf-8") == "history"
    assert (root / "data" / "documents" / "note.txt").read_text(encoding="utf-8") == "caption"
    assert (root / "data" / "browser-profile" / "cookie").read_text(encoding="utf-8") == "session"


def test_microphone_stays_in_the_box_and_does_not_send(settings):
    client = TestClient(create_app(settings, ExplodingBrowser))
    page = client.get("/").text
    assert 'data-testid="talk"' in page
    assert 'aria-label="Click to record"' in page
    assert 'data-testid="recording"' in page
    assert 'data-testid="recording-timer">00:00' in page
    assert 'data-testid="recording-stop"' in page
    assert 'data-testid="recording-cancel"' in page
    assert 'data-testid="settings"' in page
    assert "Hold to talk" in page
    assert "Track a draft branch" in page
    assert 'data-testid="check-updates"' in page
    script = Path("machaa/web/app.js").read_text(encoding="utf-8")
    start = script.index("async function uploadRecording")
    end = script.index("desktopSwitch.addEventListener")
    assert "requestSubmit" not in script[start:end]
    assert "input.value" in script[start:end]
    assert "speechSynthesis" in script
    assert "getUserMedia" in script
    assert "percent" not in script
    assert "Microphone blocked. In Windows, choose Allow when the browser asks. You can still type." in script


def test_transcription_is_returned_for_the_box(settings, monkeypatch):
    monkeypatch.setattr("machaa.api.routes.transcribe_audio", lambda data, **_kwargs: "Open Notepad, then wait.")
    client = TestClient(create_app(settings, ExplodingBrowser))
    response = client.post("/api/voice/transcribe", content=b"not-saved")
    assert response.status_code == 200
    assert response.json()["text"] == "Open Notepad, then wait."


def test_progress_names_the_step_and_counts_seconds(settings):
    store = TaskStore(settings.database_path)
    record = store.create("Open Google and search for bedroom ideas")
    store.add_step(
        record.id,
        tool="browser.search_google",
        label="Search",
        arguments={},
        status="completed",
    )
    past = (datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat(timespec="seconds")
    store.set_fields(record.id, status="running", phase="Searching…", started_at=past)
    public = store.get(record.id).to_public()
    assert public["phase"] == "Searching…"
    assert public["elapsed_seconds"] >= 2
    assert "percent" not in public
    store.close()


def test_payment_stays_blocked_and_events_have_no_percentage(settings):
    client = TestClient(create_app(settings, ExplodingBrowser))
    created = client.post("/api/tasks", json={"instruction": BANK})
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "blocked"
    assert body["phase"] == "Blocked"
    assert "percent" not in body
    with client.stream("GET", f"/api/tasks/{body['id']}/events") as response:
        text = "".join(response.iter_text())
    assert "Blocked" in text
    assert "elapsed_seconds" in text
    assert "percent" not in text


def test_creative_document_has_three_distinct_ideas(tmp_path: Path):
    payload = FixtureGemini().write_social(
        "Vistaara Interiors",
        "2BHK interiors",
        "Instagram",
        "homeowners",
        "https://commons.wikimedia.org/wiki/File:Room.jpg",
        "",
    )
    payload["tone"] = "warm"
    payload["concepts"][0]["short_caption"] = "Rooms from ₹50,000 that delve into a look."
    payload["concepts"][0]["caption"] = payload["concepts"][0]["short_caption"]
    path = tmp_path / "instagram.docx"
    write_social_document(path, payload, None)
    text = "\n".join(paragraph.text for paragraph in Document(str(path)).paragraphs)
    for label in ("Hook:", "Short caption:", "Long caption:", "Call to action:", "Visual direction:", "Hashtags:"):
        assert label in text
    assert "reel" in text
    assert "carousel" in text
    assert "static" in text
    assert "₹" not in text
    assert "$" not in text
    assert "delve" not in text.lower()
    assert "Tone: warm" in text
    plan = parse_research_request(
        "Machaa, prepare an Instagram content document for Vistaara Interiors about 2BHK interiors in a warm tone"
    )
    assert plan is not None and plan.tone == "warm"
    assert "₹" not in clean_copy("Rooms from ₹50,000")
    assert "delve" not in clean_copy("Please delve later").lower()


def test_launcher_does_not_start_a_second_copy(tmp_path: Path):
    root = tmp_path / "app"
    plan = prepare_start(root, alive=lambda pid: False, listening=lambda port: port == 8787)
    assert plan.already_running is True
    assert plan.spawn is False
    (root / "data" / "machaa.pid").write_text("42", encoding="utf-8")
    again = prepare_start(root, alive=lambda pid: pid == 42, listening=lambda port: False)
    assert again.already_running is True
    fresh = prepare_start(root, alive=lambda pid: False, listening=lambda port: False)
    assert fresh.spawn is True
    (root / "data" / "companion.pid").write_text("77", encoding="utf-8")
    stopped: list[int] = []
    commands = prepare_stop(root, alive=lambda pid: pid in {42, 77}, killer=stopped.append)
    assert stopped == [42, 77]
    assert commands == ["docker compose stop"]
    assert not (root / "data" / "machaa.pid").exists()
    assert not (root / "data" / "companion.pid").exists()
    windows = prepare_companion(root, platform="win32", alive=lambda pid: False, listening=lambda port: False)
    assert windows.spawn is True
    other = prepare_companion(root, platform="linux", alive=lambda pid: False, listening=lambda port: False)
    assert other.spawn is False
    calls: list[str] = []

    def probe() -> str:
        calls.append("probe")
        return "not_running" if len(calls) == 1 else "running"

    assert ensure_docker(probe=probe, launch=lambda: calls.append("start")) == "running"
    assert calls == ["probe", "start", "probe"]
    launched: list[str] = []
    assert ensure_docker(probe=lambda: "not_installed", launch=lambda: launched.append("no")) == "not_installed"
    assert launched == []
    start_bat = Path("START-MACHAA.bat").read_text(encoding="utf-8")
    stop_bat = Path("STOP-MACHAA.bat").read_text(encoding="utf-8")
    assert "machaa.launcher start" in start_bat
    assert "machaa.launcher stop" in stop_bat
    assert "docker compose up --build" not in start_bat


def test_updates_ignore_forks_drafts_and_pull_requests():
    assert is_trusted_update(OFFICIAL, "refs/heads/main") is True
    assert is_trusted_update(OFFICIAL, "refs/tags/v0.5.0") is True
    assert is_trusted_update("https://github.com/someone/machaa.git", "refs/heads/main") is False
    assert is_trusted_update(OFFICIAL, "refs/pull/4/head", "cursor/machaa-day4-5") is False
    assert is_trusted_update(OFFICIAL, "refs/heads/cursor/machaa-day4-5", "") is False
    assert is_trusted_update(OFFICIAL, "refs/heads/cursor/machaa-day4-5", "cursor/machaa-day4-5") is True
    offer = choose_update(
        [
            ("pull", "refs/pull/3/head"),
            ("draft", "refs/heads/cursor/machaa-day4-5"),
            ("mainsha", "refs/heads/main"),
        ],
        "older",
        "",
    )
    assert offer is not None
    assert offer["ref"] == "refs/heads/main"
    assert offer["available"] is True
    tracked = choose_update(
        [("draft", "refs/heads/cursor/machaa-day4-5"), ("mainsha", "refs/heads/main")],
        "older",
        "cursor/machaa-day4-5",
    )
    assert tracked is not None
    assert tracked["ref"] == "refs/heads/cursor/machaa-day4-5"


def test_unapproved_and_untrusted_updates_do_not_run(settings, tmp_path: Path):
    client = TestClient(create_app(settings, ExplodingBrowser))
    refused = client.post("/api/updates/apply", json={"approved": False})
    assert refused.status_code == 400
    assert "Approval is needed" in refused.json()["detail"]
    status = client.get("/api/updates").json()
    assert status["track"]["enabled"] is False
    assert status["available"] is False
    saved = client.post(
        "/api/updates/track",
        json={"enabled": True, "branch": "cursor/machaa-day4-5"},
    ).json()
    assert saved["enabled"] is True
    service = client.app.state.service
    service.remote_listing = "abc refs/pull/9/head\n"
    service.update_runner = RecordingGit()
    message = service.apply_approved_update(True)
    assert "official" in message.lower() or "no approved" in message.lower()
    assert service.update_runner.calls == []
    root = _project(tmp_path)
    runner = RecordingGit()
    with pytest.raises(UpdateRefused):
        apply_update(
            root,
            "https://github.com/someone/machaa.git",
            "refs/heads/main",
            approved=True,
            track_branch="",
            runner=runner,
            health_ok=lambda: True,
            current_sha="abc",
        )
    assert runner.calls == []
    _kept(root)
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "root": str(root),
                "remote": "https://github.com/someone/machaa.git",
                "ref": "refs/heads/main",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    assert updater_main([str(plan)]) == 1
    _kept(root)


def test_update_keeps_user_files_and_rolls_back(tmp_path: Path):
    root = _project(tmp_path)
    runner = RecordingGit(wipe=True)
    with pytest.raises(UpdateFailed) as caught:
        apply_update(
            root,
            OFFICIAL,
            "refs/heads/main",
            approved=True,
            track_branch="",
            runner=runner,
            health_ok=lambda: False,
            current_sha="previous-sha",
        )
    assert "previous version" in str(caught.value).lower()
    assert ["reset", "--hard", "previous-sha"] in runner.calls
    _kept(root)
    backup = root / "data" / "update-backup" / "latest" / ".env"
    assert backup.read_text(encoding="utf-8") == "GEMINI_API_KEY=kept\n"


def test_zip_migration_keeps_the_env_file(tmp_path: Path):
    root = _project(tmp_path)
    message = migrate_zip(root, RecordingGit(wipe=True))
    assert "kept" in message.lower()
    assert (root / ".git").is_dir()
    assert (root / "data" / "migrated.txt").read_text(encoding="utf-8").strip() == "official"
    _kept(root)


def test_interrupted_task_keeps_finished_steps(settings):
    store = TaskStore(settings.database_path)
    record = store.create("Open Google and search for bedroom ideas")
    store.add_step(
        record.id,
        tool="browser.search_google",
        label="Search",
        arguments={},
        status="completed",
    )
    store.set_fields(record.id, status="running", phase="Searching…")
    store.close()
    service = TaskService(settings, ExplodingBrowser)
    recovered = service.get(record.id)
    assert recovered is not None
    assert recovered["status"] == "failed"
    assert "stopped before this finished" in recovered["summary"]
    assert recovered["steps"][0]["tool"] == "browser.search_google"
    assert recovered["steps"][0]["status"] == "completed"


class FlakyCompanion:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def configured(self) -> bool:
        return True

    def set_permission(self, enabled: bool) -> dict:
        return {"ok": True, "enabled": enabled}

    def call(self, action: str, arguments: dict) -> dict:
        self.calls.append(action)
        if len(self.calls) == 1:
            raise CompanionUnavailable("The companion did not answer.")
        return {"ok": True, "detail": "Opened Notepad.", "pid": 5}


async def test_companion_recovers_after_one_missed_connection(settings):
    companion = FlakyCompanion()
    service = TaskService(settings, ExplodingBrowser, companion=companion)
    service.desktop_enabled = True
    created = await service.submit("Machaa, open Notepad.")
    finished = {}
    for _ in range(80):
        finished = service.get(created["id"])
        if finished["status"] in {"completed", "failed", "blocked"}:
            break
        await asyncio.sleep(0.05)
    assert finished["status"] == "completed", finished
    assert finished["summary"] == "Opened Notepad."
    assert companion.calls == ["desktop.open_notepad", "desktop.open_notepad"]
