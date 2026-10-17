"""Task ids, status, and the execution history stored on this computer."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "blocked", "stopped", "needs_human", "needs_key"}
)


def new_task_id() -> str:
    return "task_" + uuid.uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _phase_for_tool(tool: str) -> str:
    return {
        "browser.search_google": "Searching…",
        "browser.visit_public_page": "Opening the page…",
        "browser.extract_text": "Reading the page…",
        "browser.screenshot": "Saving a screenshot…",
        "image.find_licensed": "Looking for a licensed image…",
        "content.write_social": "Generating captions…",
        "llm.draft_document": "Generating the document…",
        "report.save_docx": "Creating Word document…",
        "report.save_markdown": "Saving the report…",
        "desktop.open_notepad": "Opening Notepad…",
        "desktop.open_calculator": "Opening Calculator…",
        "desktop.open_explorer": "Opening File Explorer…",
        "desktop.type_notepad": "Typing into Notepad…",
        "desktop.save_text": "Saving the text file…",
        "desktop.read_file": "Reading the file…",
        "desktop.focus_dashboard": "Opening Machaa…",
        "desktop.open_website": "Opening the page…",
        "desktop.save_docx": "Saving the Word document…",
        "desktop.open_docx": "Opening the Word document…",
        "desktop.switch_window": "Switching windows…",
        "desktop.capture_screen": "Taking a screenshot…",
        "desktop.organize_file": "Organizing the file…",
    }.get(tool, "Working…")


def _phase_for_status(status: str) -> str:
    return {
        "queued": "Waiting",
        "running": "Understanding…",
        "paused": "Paused",
        "needs_approval": "Waiting for your approval",
        "needs_key": "Needs a Gemini key",
        "needs_human": "Needs a person",
        "completed": "Completed",
        "failed": "Something went wrong",
        "blocked": "Blocked",
        "stopped": "Stopped",
    }.get(status, "")


def _elapsed_seconds(started_at: str) -> int:
    if not started_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - started).total_seconds()))


def _saved_location(steps: list) -> str:
    for step in reversed(steps):
        if step.tool == "desktop.save_docx" and step.status == "completed" and step.detail:
            return step.detail
    return ""


@dataclass
class StepRecord:
    id: int
    task_id: str
    position: int
    tool: str
    label: str
    status: str
    detail: str

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "position": self.position,
            "tool": self.tool,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class TaskRecord:
    id: str
    instruction: str
    status: str
    agent: str | None
    summary: str
    block_reason: str | None
    report_path: str | None
    screenshot_path: str | None
    document_path: str | None
    page_url: str | None
    stop_requested: bool
    pause_requested: bool
    approval: str
    phase: str
    started_at: str
    created_at: str
    updated_at: str
    steps: list[StepRecord]

    def to_public(self) -> dict:
        """Fields the dashboard may see. Filesystem paths stay on the server."""

        return {
            "id": self.id,
            "instruction": self.instruction,
            "status": self.status,
            "agent": self.agent,
            "summary": self.summary,
            "block_reason": self.block_reason,
            "page_url": self.page_url,
            "stop_requested": self.stop_requested,
            "pause_requested": self.pause_requested,
            "approval": self.approval,
            "phase": self.phase or _phase_for_status(self.status),
            "started_at": self.started_at,
            "elapsed_seconds": _elapsed_seconds(self.started_at),
            "saved_location": _saved_location(self.steps),
            "has_screenshot": bool(self.screenshot_path),
            "has_report": bool(self.report_path),
            "has_document": bool(self.document_path),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [step.to_public() for step in self.steps],
        }


class TaskStore:
    """SQLite history. The database file lives in the data directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    instruction TEXT NOT NULL,
                    status TEXT NOT NULL,
                    agent TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    block_reason TEXT,
                    report_path TEXT,
                    screenshot_path TEXT,
                    page_url TEXT,
                    document_path TEXT,
                    stop_requested INTEGER NOT NULL DEFAULT 0,
                    pause_requested INTEGER NOT NULL DEFAULT 0,
                    approval TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    tool TEXT NOT NULL,
                    label TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row[1] for row in self._connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "document_path" not in columns:
                self._connection.execute("ALTER TABLE tasks ADD COLUMN document_path TEXT")
            if "pause_requested" not in columns:
                self._connection.execute(
                    "ALTER TABLE tasks ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0"
                )
            if "approval" not in columns:
                self._connection.execute(
                    "ALTER TABLE tasks ADD COLUMN approval TEXT NOT NULL DEFAULT ''"
                )
            if "phase" not in columns:
                self._connection.execute("ALTER TABLE tasks ADD COLUMN phase TEXT NOT NULL DEFAULT ''")
            if "started_at" not in columns:
                self._connection.execute(
                    "ALTER TABLE tasks ADD COLUMN started_at TEXT NOT NULL DEFAULT ''"
                )
            self._connection.commit()

    def create(self, instruction: str) -> TaskRecord:
        now = utc_now()
        task_id = new_task_id()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO tasks (
                    id, instruction, status, summary, created_at, updated_at
                ) VALUES (?, ?, 'queued', '', ?, ?)
                """,
                (task_id, instruction, now, now),
            )
            self._connection.commit()
        record = self.get(task_id)
        if record is None:
            raise RuntimeError("task was not saved")
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            steps = self._connection.execute(
                "SELECT * FROM steps WHERE task_id = ? ORDER BY position ASC, id ASC",
                (task_id,),
            ).fetchall()
        return _task_from_row(row, steps)

    def list_recent(self, limit: int = 50) -> list[TaskRecord]:
        capped = max(1, min(limit, 100))
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM (
                    SELECT * FROM tasks ORDER BY created_at DESC, id DESC LIMIT ?
                ) ORDER BY created_at ASC, id ASC
                """,
                (capped,),
            ).fetchall()
            records = []
            for row in rows:
                steps = self._connection.execute(
                    "SELECT * FROM steps WHERE task_id = ? ORDER BY position ASC, id ASC",
                    (row["id"],),
                ).fetchall()
                records.append(_task_from_row(row, steps))
        return records

    def set_fields(self, task_id: str, **fields: object) -> None:
        allowed = {
            "status",
            "agent",
            "summary",
            "block_reason",
            "report_path",
            "screenshot_path",
            "page_url",
            "document_path",
            "stop_requested",
            "pause_requested",
            "approval",
            "phase",
            "started_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown task fields: {sorted(unknown)}")
        if not fields:
            return
        if "status" in fields and "phase" not in fields:
            fields = dict(fields)
            fields["phase"] = _phase_for_status(str(fields["status"]))
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = [
            int(bool(value)) if name in {"stop_requested", "pause_requested"} else value
            for name, value in fields.items()
        ]
        values.append(utc_now())
        values.append(task_id)
        with self._lock:
            self._connection.execute(
                f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
                values,
            )
            self._connection.commit()

    def request_stop(self, task_id: str) -> TaskRecord | None:
        task = self.get(task_id)
        if task is None:
            return None
        if task.status in TERMINAL_STATUSES:
            return task
        if task.status in {"queued", "paused", "needs_approval"}:
            self.finish(task_id, status="stopped", summary="Stopped.", stop_requested=True)
        else:
            self.set_fields(task_id, stop_requested=True)
        return self.get(task_id)

    def request_pause(self, task_id: str) -> TaskRecord | None:
        task = self.get(task_id)
        if task is None or task.status in TERMINAL_STATUSES or task.status == "paused":
            return task
        self.set_fields(task_id, pause_requested=True)
        if task.status == "queued":
            self.set_fields(task_id, status="paused")
        return self.get(task_id)

    def request_resume(self, task_id: str) -> TaskRecord | None:
        task = self.get(task_id)
        if task is None or task.status in TERMINAL_STATUSES:
            return task
        self.set_fields(task_id, pause_requested=False)
        if task.status == "paused":
            self.set_fields(task_id, status="running" if task.agent else "queued")
        return self.get(task_id)

    def add_step(
        self,
        task_id: str,
        *,
        tool: str,
        label: str,
        arguments: dict,
        status: str,
    ) -> int:
        now = utc_now()
        with self._lock:
            position_row = self._connection.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 AS next_pos FROM steps WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            position = int(position_row["next_pos"])
            cursor = self._connection.execute(
                """
                INSERT INTO steps (
                    task_id, position, tool, label, arguments, status, detail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)
                """,
                (task_id, position, tool, label, json.dumps(arguments), status, now, now),
            )
            self._connection.execute(
                "UPDATE tasks SET phase = ?, updated_at = ? WHERE id = ?",
                (_phase_for_tool(tool), now, task_id),
            )
            self._connection.commit()
            return int(cursor.lastrowid)

    def finish_step(self, step_id: int, status: str, detail: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE steps SET status = ?, detail = ?, updated_at = ? WHERE id = ?",
                (status, detail[:500], utc_now(), step_id),
            )
            self._connection.commit()

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        summary: str,
        block_reason: str | None = None,
        agent: str | None = None,
        report_path: str | None = None,
        screenshot_path: str | None = None,
        page_url: str | None = None,
        document_path: str | None = None,
        stop_requested: bool | None = None,
    ) -> None:
        """Move a task into a final status. A second finish does not overwrite it."""

        current = self.get(task_id)
        if current is None or current.status in TERMINAL_STATUSES:
            return
        fields: dict[str, object] = {"status": status, "summary": summary}
        if block_reason is not None:
            fields["block_reason"] = block_reason
        if agent is not None:
            fields["agent"] = agent
        if report_path is not None:
            fields["report_path"] = report_path
        if screenshot_path is not None:
            fields["screenshot_path"] = screenshot_path
        if page_url is not None:
            fields["page_url"] = page_url
        if document_path is not None:
            fields["document_path"] = document_path
        if stop_requested is not None:
            fields["stop_requested"] = stop_requested
        self.set_fields(task_id, **fields)
        if status != "completed":
            step_status = "stopped" if status == "stopped" else status
            with self._lock:
                self._connection.execute(
                    """
                    UPDATE steps
                    SET status = ?, updated_at = ?
                    WHERE task_id = ? AND status = 'running'
                    """,
                    (step_status, utc_now(), task_id),
                )
                self._connection.commit()

    def add_note(self, kind: str, content: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO memory_notes (kind, content, created_at) VALUES (?, ?, ?)",
                (kind, content[:2000], utc_now()),
            )
            self._connection.commit()

    def search_notes(self, query: str, limit: int = 5) -> list[dict]:
        needle = f"%{query.strip()}%"
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, kind, content, created_at
                FROM memory_notes
                WHERE content LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (needle, max(1, min(limit, 20))),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_interrupted(self) -> None:
        """Mark work that was still open when Machaa last stopped."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id FROM tasks
                WHERE status IN ('queued', 'running', 'paused', 'needs_approval')
                """
            ).fetchall()
        for row in rows:
            self.finish(
                row["id"],
                status="failed",
                summary=(
                    "Machaa stopped before this finished. "
                    "The steps already done are saved. Send the request again if you still want it."
                ),
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _task_from_row(row: sqlite3.Row, steps: list[sqlite3.Row]) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        instruction=row["instruction"],
        status=row["status"],
        agent=row["agent"],
        summary=row["summary"],
        block_reason=row["block_reason"],
        report_path=row["report_path"],
        screenshot_path=row["screenshot_path"],
        page_url=row["page_url"],
        document_path=row["document_path"] if "document_path" in row.keys() else None,
        stop_requested=bool(row["stop_requested"]),
        pause_requested=bool(row["pause_requested"]) if "pause_requested" in row.keys() else False,
        approval=row["approval"] if "approval" in row.keys() and row["approval"] else "",
        phase=row["phase"] if "phase" in row.keys() and row["phase"] else "",
        started_at=row["started_at"] if "started_at" in row.keys() and row["started_at"] else "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        steps=[
            StepRecord(
                id=step["id"],
                task_id=step["task_id"],
                position=step["position"],
                tool=step["tool"],
                label=step["label"],
                status=step["status"],
                detail=step["detail"],
            )
            for step in steps
        ],
    )
