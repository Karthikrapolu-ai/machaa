"""Run one allowlisted desktop action. The Guardian is asked again here."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from machaa.companion.policy import (
    resolve_docx,
    resolve_folder,
    resolve_inside,
    title_is_our_notepad,
    title_matches_window,
)
from machaa.companion.windows import (
    capture_screen,
    focus_dashboard,
    launch_app,
    open_registered_document,
    switch_to_window,
    type_into_notepad,
)
from machaa.core.errors import CompanionRefused
from machaa.core.guardian import Guardian

_LAUNCH = {
    "desktop.open_notepad": "notepad",
    "desktop.open_calculator": "calculator",
    "desktop.open_explorer": "explorer",
}


class CompanionState:
    """Memory that stays inside the companion process."""

    def __init__(self, documents: Path) -> None:
        self.documents = documents
        self.permission = False
        self.notepad_pid = 0
        self.notepad_title = ""
        self.explorer_pid = 0
        self.explorer_title = ""
        self.document_pid = 0
        self.document_title = ""
        self.guardian = Guardian()


def perform(state: CompanionState, action: str, arguments: dict) -> dict:
    """Execute one action the Guardian already named. Never a shell command."""

    if not isinstance(arguments, dict):
        raise CompanionRefused("The companion refused that action.")
    decision = state.guardian.review_tool_call(action, arguments)
    if not decision.allowed:
        raise CompanionRefused(decision.reason)
    if action != "desktop.focus_dashboard" and not state.permission:
        raise CompanionRefused(
            "Desktop control is off. Turn Desktop control on in the Machaa window."
        )
    if action in _LAUNCH:
        opened = launch_app(_LAUNCH[action], state.documents)
        if action == "desktop.open_notepad":
            state.notepad_pid = int(opened["pid"])
            state.notepad_title = "Untitled - Notepad"
        if action == "desktop.open_explorer":
            state.explorer_pid = int(opened["pid"])
            state.explorer_title = "Machaa"
        detail = {
            "notepad": "Opened Notepad.",
            "calculator": "Opened Calculator.",
            "explorer": "Opened File Explorer in the Machaa Documents folder.",
        }[_LAUNCH[action]]
        return {"ok": True, "detail": detail, "pid": opened["pid"]}
    if action == "desktop.focus_dashboard":
        if sys.platform == "win32":
            focus_dashboard()
            return {"ok": True, "detail": "Opened the Machaa dashboard."}
        return {"ok": True, "detail": "The Machaa dashboard is at http://127.0.0.1:8787."}
    if action == "desktop.type_notepad":
        if not title_is_our_notepad(state.notepad_title, state.notepad_pid, state.notepad_pid):
            raise CompanionRefused(
                "Machaa refused to type because the front window is not the Notepad it opened."
            )
        type_into_notepad(str(arguments["text"]), state.notepad_pid)
        return {"ok": True, "detail": "Typed into the Notepad Machaa opened."}
    if action == "desktop.save_text":
        path = resolve_inside(state.documents, str(arguments["filename"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(arguments["text"]), encoding="utf-8")
        return {"ok": True, "detail": f"Saved {path.name} in the Machaa Documents folder."}
    if action == "desktop.read_file":
        path = resolve_inside(state.documents, str(arguments["filename"]))
        if not path.is_file():
            raise CompanionRefused("That file is not in the Machaa Documents folder.")
        return {"ok": True, "detail": path.read_text(encoding="utf-8")[:500]}
    if action == "desktop.save_docx":
        path = resolve_docx(state.documents, str(arguments["filename"]))
        data = base64.b64decode(str(arguments["content"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_bytes() == data:
            return {
                "ok": True,
                "detail": f"Saved {path.name} in the Machaa Documents folder.",
                "verified": True,
                "duplicate": True,
                "path": str(path),
            }
        path.write_bytes(data)
        return {
            "ok": True,
            "detail": f"Saved {path.name} in the Machaa Documents folder.",
            "verified": True,
            "path": str(path),
        }
    if action == "desktop.open_docx":
        path = resolve_docx(state.documents, str(arguments["filename"]))
        if not path.is_file():
            raise CompanionRefused("That file is not in the Machaa Documents folder.")
        open_registered_document(path)
        state.document_title = path.name
        return {
            "ok": True,
            "detail": f"Opened {path.name} with its registered app.",
            "verified": True,
            "path": str(path),
        }
    if action == "desktop.organize_file":
        source = resolve_docx(state.documents, str(arguments["filename"]))
        if not source.is_file():
            raise CompanionRefused("That file is not in the Machaa Documents folder.")
        folder = resolve_folder(state.documents, str(arguments["folder"]))
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / source.name
        if destination.exists():
            raise CompanionRefused(
                "Machaa did not move that file because a file with the same name is already in that folder."
            )
        source.rename(destination)
        return {
            "ok": True,
            "detail": f"Moved {source.name} into {folder.name}.",
            "verified": True,
            "path": str(destination),
        }
    if action == "desktop.switch_window":
        target = str(arguments["target"]).strip().lower()
        if target == "notepad":
            pid, title, kind = state.notepad_pid, state.notepad_title, "notepad"
        elif target == "explorer":
            pid, title, kind = state.explorer_pid, state.explorer_title or "Machaa", "explorer"
        else:
            pid, title, kind = state.document_pid, state.document_title, "document"
        if not title_matches_window(kind, title, pid, pid):
            raise CompanionRefused(
                "Machaa refused to switch windows because that window is not one it opened."
            )
        switch_to_window(kind, pid, title)
        return {"ok": True, "detail": "Switched to the window Machaa opened.", "verified": True}
    if action == "desktop.capture_screen":
        path = state.documents / "machaa-screen.bmp"
        capture_screen(path)
        return {
            "ok": True,
            "detail": "Saved machaa-screen.bmp in the Machaa Documents folder.",
            "verified": path.is_file(),
            "path": str(path),
        }
    if action == "desktop.open_website":
        raise CompanionRefused(
            "Websites open in Machaa's own browser, not in your personal browser."
        )
    raise CompanionRefused("The companion refused that action.")
