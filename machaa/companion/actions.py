"""Run one allowlisted desktop action. The Guardian is asked again here."""

from __future__ import annotations

import sys
from pathlib import Path

from machaa.companion.policy import resolve_inside, title_is_our_notepad
from machaa.companion.windows import focus_dashboard, launch_app, type_into_notepad
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
    if action == "desktop.open_website":
        raise CompanionRefused(
            "Websites open in Machaa's own browser, not in your personal browser."
        )
    raise CompanionRefused("The companion refused that action.")
