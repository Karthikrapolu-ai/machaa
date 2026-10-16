"""Path and window rules for the Windows Companion.

These checks are pure. They run on any computer, including the tests.
The companion refuses a path that is not a single file inside the
Machaa Documents folder, and it refuses to type unless the window is
the Notepad process Machaa itself opened.
"""

from __future__ import annotations

import re
from pathlib import Path

from machaa.core.errors import CompanionRefused
from machaa.core.guardian import _SAFE_DOCX, _SAFE_FILENAME, _SAFE_FOLDER

_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])$", re.IGNORECASE)


def title_is_our_notepad(title: str, pid: int, expected_pid: int) -> bool:
    """True only for the Notepad window Machaa launched.

    Notepad++ and any other process are refused, even when the title
    contains the word Notepad.
    """

    if not isinstance(title, str) or not isinstance(pid, int) or not isinstance(expected_pid, int):
        return False
    if expected_pid <= 0 or pid != expected_pid:
        return False
    cleaned = " ".join(title.split())
    lowered = cleaned.lower()
    if "notepad++" in lowered or "powershell" in lowered or "command prompt" in lowered:
        return False
    return bool(re.search(r"(^| - )notepad$", lowered))


def title_matches_window(kind: str, title: str, pid: int, expected_pid: int) -> bool:
    """True only for a window Machaa opened.

    The process id has to match, and the title has to belong to that app.
    Notepad++ and a command window never match.
    """

    if kind == "notepad":
        return title_is_our_notepad(title, pid, expected_pid)
    if not isinstance(title, str) or not isinstance(pid, int) or not isinstance(expected_pid, int):
        return False
    if expected_pid <= 0 or pid != expected_pid:
        return False
    lowered = " ".join(title.split()).lower()
    if "notepad++" in lowered or "powershell" in lowered or "command prompt" in lowered:
        return False
    if kind == "explorer":
        return "machaa" in lowered
    if kind == "document":
        return lowered.endswith(".docx") or "word" in lowered
    return False


def resolve_docx(root: Path, filename: str) -> Path:
    """A .docx Machaa may save or open, and only inside the Machaa Documents folder."""

    if not isinstance(filename, str):
        raise CompanionRefused(
            "Machaa will only open or save a simple .docx name inside the Machaa Documents folder."
        )
    name = filename.strip()
    if any(sep in filename for sep in ("/", "\\", "\x00")) or _SAFE_DOCX.fullmatch(name) is None:
        raise CompanionRefused(
            "Machaa will only open or save a simple .docx name inside the Machaa Documents folder."
        )
    folder = root.resolve()
    candidate = folder / name
    if candidate.is_symlink():
        raise CompanionRefused(
            "Machaa refused that file because it points outside the Machaa Documents folder."
        )
    resolved = candidate.resolve()
    if resolved.parent != folder:
        raise CompanionRefused(
            "Machaa refused that file because it is outside the Machaa Documents folder."
        )
    return resolved


def resolve_folder(root: Path, folder_name: str) -> Path:
    """One new folder inside the Machaa Documents folder. Nothing above it."""

    if not isinstance(folder_name, str) or _SAFE_FOLDER.fullmatch(folder_name.strip()) is None:
        raise CompanionRefused(
            "Machaa will only move a file into a simple folder inside the Machaa Documents folder."
        )
    folder = root.resolve()
    candidate = folder / folder_name.strip()
    if candidate.is_symlink():
        raise CompanionRefused(
            "Machaa refused that folder because it points outside the Machaa Documents folder."
        )
    resolved = candidate.resolve()
    if resolved.parent != folder:
        raise CompanionRefused(
            "Machaa refused that folder because it is outside the Machaa Documents folder."
        )
    return resolved


def resolve_inside(root: Path, filename: str) -> Path:
    """Return the only path Machaa may read or write for this name."""

    if not isinstance(filename, str):
        raise CompanionRefused(
            "Machaa will only use a simple .txt or .md name inside the Machaa Documents folder."
        )
    name = filename.strip()
    if name != filename.strip() or any(sep in filename for sep in ("/", "\\", "\x00")):
        raise CompanionRefused(
            "Machaa will only use a simple .txt or .md name inside the Machaa Documents folder."
        )
    if _SAFE_FILENAME.fullmatch(name) is None:
        raise CompanionRefused(
            "Machaa will only use a simple .txt or .md name inside the Machaa Documents folder."
        )
    stem = name.rsplit(".", 1)[0]
    if _DEVICE.fullmatch(stem):
        raise CompanionRefused(
            "Machaa will only use a simple .txt or .md name inside the Machaa Documents folder."
        )
    folder = root.resolve()
    candidate = folder / name
    if candidate.is_symlink():
        raise CompanionRefused(
            "Machaa refused that file because it points outside the Machaa Documents folder."
        )
    resolved = candidate.resolve()
    if resolved.parent != folder:
        raise CompanionRefused(
            "Machaa refused that file because it is outside the Machaa Documents folder."
        )
    return resolved
