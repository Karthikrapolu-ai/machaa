"""Answers that come from tasks Machaa has already stored.

Nothing here is guessed. If the database has no file, the answer says so.
"""

from __future__ import annotations

import re
from pathlib import Path

_RECALL = re.compile(
    r"\bwhat did you (?:create|make|save|write)\b[\s\S]{0,80}\blast task\b",
    re.IGNORECASE,
)
_SUMMARY_ASK = re.compile(
    r"\b(summary|summarize|that document|last document|the document)\b",
    re.IGNORECASE,
)


def is_recall(instruction: str) -> bool:
    return _RECALL.search(" ".join((instruction or "").split())) is not None


def asks_for_document_summary(instruction: str) -> bool:
    return _SUMMARY_ASK.search(instruction or "") is not None


def describe_last(store, skip_id: str) -> str:
    """Say what the previous task did, using its saved row."""

    records = [record for record in store.list_recent(40) if record.id != skip_id]
    if not records:
        return "Machaa has no earlier task yet."
    last = records[-1]
    parts = [
        f"The last task was: {last.instruction}",
        f"Status: {last.status}.",
    ]
    if last.summary:
        parts.append(last.summary)
    location = ""
    for step in last.steps:
        if step.tool == "desktop.save_docx" and step.status == "completed" and step.detail:
            location = step.detail
    if location:
        parts.append(f"Saved file: {location}")
    elif last.document_path:
        parts.append("A Word document is on that task card.")
    else:
        parts.append("That task did not leave a file Machaa can point to.")
    errors = [
        f"{step.label}: {step.detail}"
        for step in last.steps
        if step.status in {"failed", "blocked"} and step.detail
    ]
    if errors:
        parts.append("Errors: " + " ".join(errors)[:400])
    return " ".join(parts)[:1200]


def summary_for_notepad(store) -> str:
    """A short reading of the last Word file. It does not add claims."""

    for record in reversed(store.list_recent(40)):
        raw = record.document_path or ""
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        text = _docx_text(path)
        if not text:
            continue
        return "Summary of the last Machaa document:\n" + text[:1500]
    return "Machaa looked for the last document and did not find one. Nothing was invented."


def _docx_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return ""
    try:
        document = Document(str(path))
    except Exception:
        return ""
    lines = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n".join(lines[:12])
