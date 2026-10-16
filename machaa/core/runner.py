"""Run one task at a time, with a timeout, a step budget, and a stop flag."""

from __future__ import annotations

import asyncio
import logging

from machaa.agents.research import ResearchAgent
from machaa.config import Settings
from machaa.core.tasks import TERMINAL_STATUSES, TaskStore
from machaa.memory.store import LocalMemory

log = logging.getLogger("machaa.runner")


class Runner:
    """In-process background queue. One browser runs at a time."""

    def __init__(
        self,
        settings: Settings,
        store: TaskStore,
        research: ResearchAgent,
        memory: LocalMemory,
    ) -> None:
        self.settings = settings
        self.store = store
        self.research = research
        self.memory = memory
        self._slots = asyncio.Semaphore(1)
        self._jobs: set[asyncio.Task] = set()

    def enqueue(self, task_id: str) -> None:
        """Schedule a task. The dashboard returns before this finishes."""

        job = asyncio.create_task(self.run(task_id), name=f"machaa-{task_id}")
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    async def run(self, task_id: str) -> None:
        acquired = False
        try:
            acquired = await self._acquire(task_id)
            if not acquired:
                return
            task = self.store.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return
            if task.stop_requested:
                self.store.finish(task_id, status="stopped", summary="Stopped.")
                return
            self.store.set_fields(task_id, status="running", agent="research")
            try:
                async with asyncio.timeout(self.settings.task_timeout_seconds):
                    await self.research.run(task_id)
            except TimeoutError:
                self.store.finish(
                    task_id,
                    status="failed",
                    summary="Machaa stopped this task because it took too long.",
                )
        except Exception:
            log.exception("task %s failed", task_id)
            current = self.store.get(task_id)
            if current is not None and current.status not in TERMINAL_STATUSES:
                self.store.finish(
                    task_id,
                    status="failed",
                    summary="Machaa hit an unexpected error and stopped this task.",
                )
        finally:
            if acquired:
                self._slots.release()
            self._remember(task_id)

    async def _acquire(self, task_id: str) -> bool:
        while True:
            task = self.store.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                return False
            if task.stop_requested:
                self.store.finish(task_id, status="stopped", summary="Stopped.")
                return False
            try:
                await asyncio.wait_for(self._slots.acquire(), timeout=0.2)
                return True
            except TimeoutError:
                continue

    def _remember(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is None or not task.summary:
            return
        try:
            self.memory.add("task", f"{task.instruction}\n{task.summary}")
        except Exception:
            log.exception("could not store a memory note for %s", task_id)
