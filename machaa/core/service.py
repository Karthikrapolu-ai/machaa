"""Create a task, ask the Guardian, then hand it to the runner."""

from __future__ import annotations

from machaa.agents.desktop import NotepadMemory, is_stop_phrase
from machaa.agents.planning import parse_research_request
from machaa.agents.research import ResearchAgent
from machaa.browser.workspace import PlaywrightWorkspace
from machaa.companion.client import CompanionClient
from machaa.config import Settings
from machaa.core.errors import CompanionRefused, CompanionUnavailable
from machaa.core.guardian import Guardian
from machaa.core.orchestrator import DayOneOrchestrator
from machaa.core.runner import Runner
from machaa.core.tasks import TERMINAL_STATUSES, TaskStore
from machaa.llm.fixture import FixtureGemini
from machaa.llm.gemini import KEY_HELP, GeminiClient
from machaa.memory.store import LocalMemory


class TaskService:
    """The dashboard talks to this object and not to the browser directly."""

    def __init__(self, settings: Settings, browser_factory=None, gemini_client=None, companion=None) -> None:
        self.settings = settings
        self.store = TaskStore(settings.database_path)
        self.guardian = Guardian()
        self.memory = LocalMemory(self.store)
        self.orchestrator = DayOneOrchestrator()
        self.desktop_enabled = False
        self.wake_enabled = False
        self.notes = NotepadMemory()
        self.companion = companion or CompanionClient(
            settings.companion_url,
            settings.companion_token,
        )
        self._model_ready = (
            gemini_client is not None or bool(settings.gemini_api_key) or settings.gemini_fixture
        )
        if gemini_client is not None:
            self.gemini = gemini_client
        elif settings.gemini_api_key:
            self.gemini = GeminiClient(
                settings.gemini_api_key,
                settings.gemini_model,
                max_tokens=settings.max_tokens,
                max_retries=settings.max_retries,
            )
        elif settings.gemini_fixture:
            self.gemini = FixtureGemini()
        else:
            self.gemini = GeminiClient(
                "",
                settings.gemini_model,
                max_tokens=settings.max_tokens,
                max_retries=settings.max_retries,
            )
        self.research = ResearchAgent(
            settings,
            self.store,
            self.guardian,
            browser_factory or PlaywrightWorkspace,
            self.gemini,
            companion=self.companion,
            desktop_enabled=lambda: self.desktop_enabled,
            notes=self.notes,
        )
        self.runner = Runner(settings, self.store, self.research, self.memory)
        self.store.recover_interrupted()
        self.remote_listing = ""
        self.update_runner = None
        self.update_health = None
        self._docker_checked_at = 0.0
        self._docker_state = ""

    async def submit(self, instruction: str) -> dict:
        if is_stop_phrase(instruction):
            active = self._latest_open()
            if active is not None:
                stopped = self.stop(active.id)
                if stopped is not None:
                    return stopped
            record = self.store.create(instruction.strip())
            self.store.finish(
                record.id,
                status="completed",
                summary="Nothing was running.",
                agent="desktop",
            )
            return self._public(record.id)
        record = self.store.create(instruction.strip())
        decision = self.guardian.review_instruction(record.instruction)
        if decision.allowed:
            from machaa.memory.recall import describe_last, is_recall

            if is_recall(record.instruction):
                self.store.finish(
                    record.id,
                    status="completed",
                    summary=describe_last(self.store, record.id),
                    agent="memory",
                )
                return self._public(record.id)
        if not decision.allowed:
            self.store.finish(
                record.id,
                status="blocked",
                summary=decision.reason,
                block_reason=decision.reason,
                agent="guardian",
            )
            return self._public(record.id)
        plan = parse_research_request(record.instruction)
        if plan is not None and plan.kind in {"document", "social"} and not self._model_ready:
            self.store.finish(
                record.id,
                status="needs_key",
                summary=KEY_HELP,
                agent="research",
            )
            return self._public(record.id)
        route = self.orchestrator.route(record.instruction)
        if not route.available:
            self.store.finish(
                record.id,
                status="completed",
                summary=route.message,
                agent=route.agent,
            )
            return self._public(record.id)
        self.store.set_fields(record.id, status="queued", agent=route.agent)
        self.runner.enqueue(record.id)
        return self._public(record.id)

    def stop(self, task_id: str) -> dict | None:
        record = self.store.request_stop(task_id)
        if record is None:
            return None
        return record.to_public()

    def pause(self, task_id: str) -> dict | None:
        record = self.store.request_pause(task_id)
        if record is None:
            return None
        return record.to_public()

    def resume(self, task_id: str) -> dict | None:
        record = self.store.request_resume(task_id)
        if record is None:
            return None
        return record.to_public()

    def approve(self, task_id: str) -> dict | None:
        record = self.store.get(task_id)
        if record is None:
            return None
        if record.status == "needs_approval":
            self.store.set_fields(task_id, approval="approved")
        return self._public(task_id)

    def reject(self, task_id: str) -> dict | None:
        record = self.store.get(task_id)
        if record is None:
            return None
        if record.status == "needs_approval":
            self.store.set_fields(task_id, approval="rejected")
        return self._public(task_id)

    def set_desktop(self, enabled: bool) -> dict:
        self.desktop_enabled = bool(enabled)
        detail = "Desktop control is on." if enabled else "Desktop control is off."
        if self.companion.configured():
            try:
                self.companion.set_permission(self.desktop_enabled)
            except CompanionUnavailable:
                detail = (
                    "Desktop control was updated here, but the Windows Companion is not running."
                )
            except CompanionRefused as exc:
                detail = str(exc)
        return {"enabled": self.desktop_enabled, "detail": detail}

    def set_wake(self, enabled: bool) -> dict:
        from machaa.voice.transcribe import voice_ready

        if not enabled:
            self.wake_enabled = False
            return {
                "enabled": False,
                "detail": "Wake listening is off. Hold Talk, or type. Machaa does not record unless you ask.",
            }
        if not voice_ready():
            self.wake_enabled = False
            return {
                "enabled": False,
                "detail": (
                    "Wake listening stays off because the optional voice program is not installed. "
                    "You can still hold Talk or type. It stays off unless you turn it on, and it stays on this computer."
                ),
            }
        self.wake_enabled = True
        return {
            "enabled": True,
            "detail": (
                "Wake listening is on for the phrase Open Machaa. "
                "Audio stays on this computer and is not saved."
            ),
        }

    def runtime_status(self) -> dict:
        import time

        from machaa.launcher import docker_available, port_open

        now = time.monotonic()
        if not self._docker_state or now - self._docker_checked_at > 30:
            self._docker_state = docker_available()
            self._docker_checked_at = now
        companion_status = "not_configured"
        notes: list[str] = []
        if self._docker_state == "not_installed":
            notes.append(
                "Docker is not installed. Install Docker Desktop, open it, and double-click START-MACHAA.bat."
            )
        elif self._docker_state == "not_running":
            notes.append(
                "Docker is not running. Open Docker Desktop, then double-click START-MACHAA.bat."
            )
        if self.companion.configured():
            port = _companion_port(self.companion.url)
            companion_status = "reachable" if port_open(port) else "not_running"
            if companion_status == "not_running":
                notes.append(
                    "The Windows Companion is not running. "
                    "Double-click START-MACHAA.bat and leave that window open."
                )
        return {
            "docker": self._docker_state,
            "companion_status": companion_status,
            "browser_worker": "busy" if self.runner.busy else "ready",
            "reconnect": " ".join(notes),
        }

    def track_settings(self) -> dict:
        path = self.settings.data_dir / "update-settings.json"
        if not path.is_file():
            return {"enabled": False, "branch": ""}
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"enabled": False, "branch": ""}
        if not isinstance(data, dict):
            return {"enabled": False, "branch": ""}
        return {"enabled": bool(data.get("enabled")), "branch": str(data.get("branch") or "")}

    def set_track_branch(self, enabled: bool, branch: str) -> dict:
        import json
        import re

        name = " ".join((branch or "").split())[:80]
        if enabled and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}", name):
            return {
                "enabled": False,
                "branch": "",
                "detail": "That branch name cannot be used. Draft tracking stays off.",
            }
        payload = {"enabled": bool(enabled and name), "branch": name if enabled else ""}
        path = self.settings.data_dir / "update-settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        detail = (
            "Draft-branch tracking is on for the official Machaa repository only. Forks are still ignored."
            if payload["enabled"]
            else "Draft-branch tracking is off. Machaa looks at main and released versions."
        )
        return {**payload, "detail": detail}

    def check_updates(self) -> dict:
        from machaa import __version__
        from machaa.update.trust import choose_update, parse_ls_remote

        settings = self.track_settings()
        track = settings["branch"] if settings["enabled"] else ""
        listing = self.remote_listing if self.remote_listing else self._fetch_listing()
        offer = choose_update(parse_ls_remote(listing), "", track)
        if offer is None:
            return {
                "current": __version__,
                "available": False,
                "version": "",
                "ref": "",
                "detail": "No approved update was found on the official repository.",
                "track_branch": track,
            }
        return {
            "current": __version__,
            "available": bool(offer["available"]),
            "version": offer.get("version") or "",
            "ref": offer.get("ref") or "",
            "sha": offer.get("sha") or "",
            "detail": (
                "An update is available from the official repository."
                if offer["available"]
                else "Machaa is already on that version."
            ),
            "track_branch": track,
        }

    def apply_approved_update(self, approved: bool) -> str:
        from machaa.update.engine import apply_update
        from machaa.update.trust import UpdateRefused

        if not approved:
            raise PermissionError("Approval is needed before Machaa updates.")
        offer = self.check_updates()
        if not offer.get("available"):
            return offer.get("detail") or "No approved update was found."
        if self.update_runner is None:
            return (
                "Git is not available in this window. "
                "Download the official Machaa zip when you want the next version."
            )
        root = self._project_root()
        health = self.update_health if self.update_health is not None else (lambda: True)
        return apply_update(
            root,
            "https://github.com/Karthikrapolu-ai/machaa.git",
            str(offer["ref"]),
            approved=True,
            track_branch=str(offer.get("track_branch") or ""),
            runner=self.update_runner,
            health_ok=health,
            current_sha="PREVIOUS",
        )

    def _fetch_listing(self) -> str:
        return ""

    def _project_root(self):
        from pathlib import Path

        from machaa.update.trust import UpdateRefused

        candidate = self.settings.data_dir.parent
        if (candidate / "machaa" / "__init__.py").is_file() and candidate != Path("/"):
            return candidate
        cwd = Path.cwd()
        if (cwd / "machaa" / "__init__.py").is_file() and cwd != Path("/"):
            return cwd
        raise UpdateRefused("Machaa could not find its own folder, so it did not change any files.")

    def _latest_open(self):
        for record in reversed(self.store.list_recent(20)):
            if record.status not in TERMINAL_STATUSES:
                return record
        return None

    def get(self, task_id: str) -> dict | None:
        record = self.store.get(task_id)
        if record is None:
            return None
        return record.to_public()

    def list_recent(self, limit: int = 50) -> list[dict]:
        return [record.to_public() for record in self.store.list_recent(limit)]

    def artifact(self, task_id: str, kind: str):
        record = self.store.get(task_id)
        if record is None:
            return None
        if kind == "screenshot":
            raw = record.screenshot_path
        elif kind == "document":
            raw = record.document_path
        else:
            raw = record.report_path
        if not raw:
            return None
        from pathlib import Path

        path = Path(raw).resolve()
        root = self.settings.artifacts_dir.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path

    def _public(self, task_id: str) -> dict:
        record = self.store.get(task_id)
        if record is None:
            raise RuntimeError("task disappeared")
        return record.to_public()


def _companion_port(url: str) -> int:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.port:
        return int(parsed.port)
    return 8788
