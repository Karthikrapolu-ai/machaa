"""Local notes that stand in for Postgres and pgvector."""

from __future__ import annotations

from machaa.core.tasks import TaskStore


class LocalMemory:
    """Remember a short note after a task finishes.

    ``search`` is a plain text match. It is the stand-in for a later
    pgvector search, not a claim that vector search already works.
    """

    def __init__(self, tasks: TaskStore) -> None:
        self._tasks = tasks

    def add(self, kind: str, content: str) -> None:
        self._tasks.add_note(kind, content)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        return self._tasks.search_notes(query, limit)
