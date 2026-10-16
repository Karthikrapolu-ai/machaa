"""Seams later days will fill. Day 1 ships the protocols, not the full systems.

The orchestrator, agents, memory, background queue, cloud connector, and
desktop companion should keep these shapes so they can be added without
rewriting the dashboard or the Guardian.
"""

from __future__ import annotations

from typing import Protocol


class Agent(Protocol):
    """One specialist. Research is implemented. Computer and work are not."""

    name: str

    async def run(self, task_id: str) -> None:
        """Execute a task that the orchestrator already accepted."""


class MemoryStore(Protocol):
    """Long-term memory. Day 1 stores short notes in SQLite.

    A later implementation should use Postgres with pgvector and keep
    ``add`` and ``search``.
    """

    def add(self, kind: str, content: str) -> None:
        """Remember one note."""

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Return notes that match a plain-text query."""


class BackgroundQueue(Protocol):
    """Work that outlives a single dashboard request.

    Day 1 runs this inside the API process. A later queue can move it
    to a separate worker without changing the task record.
    """

    def enqueue(self, task_id: str) -> None:
        """Schedule a task id for execution."""


class CloudConnector(Protocol):
    """Optional remote runtime. Day 1 does not connect to any cloud."""

    def configured(self) -> bool:
        """Return whether a cloud runtime is available."""
