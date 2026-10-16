"""Create a task, ask the Guardian, then hand it to the runner."""

from __future__ import annotations

from machaa.agents.research import ResearchAgent
from machaa.browser.workspace import PlaywrightWorkspace
from machaa.config import Settings
from machaa.core.guardian import Guardian
from machaa.core.orchestrator import DayOneOrchestrator
from machaa.core.runner import Runner
from machaa.core.tasks import TaskStore
from machaa.memory.store import LocalMemory


class TaskService:
    """The dashboard talks to this object and not to the browser directly."""

    def __init__(self, settings: Settings, browser_factory=None) -> None:
        self.settings = settings
        self.store = TaskStore(settings.database_path)
        self.guardian = Guardian()
        self.memory = LocalMemory(self.store)
        self.orchestrator = DayOneOrchestrator()
        self.research = ResearchAgent(
            settings,
            self.store,
            self.guardian,
            browser_factory or PlaywrightWorkspace,
        )
        self.runner = Runner(settings, self.store, self.research, self.memory)

    async def submit(self, instruction: str) -> dict:
        record = self.store.create(instruction.strip())
        decision = self.guardian.review_instruction(record.instruction)
        if not decision.allowed:
            self.store.finish(
                record.id,
                status="blocked",
                summary=decision.reason,
                block_reason=decision.reason,
                agent="guardian",
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
        raw = record.screenshot_path if kind == "screenshot" else record.report_path
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
