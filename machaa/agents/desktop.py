"""Safe desktop actions. The Guardian checks the plan before the companion runs."""

from __future__ import annotations

import asyncio
import re
import time

from machaa.agents.planner import Action, PlanningError, actions_from_model, validate_actions
from machaa.companion.client import COMPANION_HELP
from machaa.core.errors import (
    ApprovalDenied,
    CompanionRefused,
    CompanionUnavailable,
    DesktopOff,
    StepLimitReached,
    TaskStopped,
    ToolDenied,
)
from machaa.core.tasks import TERMINAL_STATUSES
from machaa.llm.gemini import DraftError, QuotaError, TokenLimitError
from machaa.tools.gateway import ToolGateway

DESKTOP_OFF = (
    "Desktop control is off. Turn Desktop control on, then ask again. Nothing was opened."
)
REJECTED = "You rejected this. Machaa did not change anything."
_STOP = re.compile(r"^(?:machaa[,:]?\s+)?stop[.!]?$", re.IGNORECASE)
_NEEDS_APPROVAL = frozenset(
    {
        "desktop.type_notepad",
        "desktop.save_text",
        "desktop.read_file",
        "desktop.save_docx",
        "desktop.capture_screen",
        "desktop.organize_file",
    }
)


class NotepadMemory:
    """The last text Machaa typed, kept in this process only."""

    def __init__(self) -> None:
        self.text = ""


def is_stop_phrase(instruction: str) -> bool:
    return _STOP.fullmatch(" ".join(instruction.strip().split())) is not None


def stand_in_captions(instruction: str) -> str:
    """Three caption ideas used when Gemini has no key. Labelled as a stand-in."""

    brand = "Vistaara Interiors" if "vistaara" in instruction.lower() else "the brand"
    return (
        f"{brand} — three caption ideas. "
        "These lines are a stand-in on this computer, not a live Gemini call.\n\n"
        f"1. {brand}: a 2BHK can look finished and still feel easy to live in. "
        "One material, one warm light, room to walk.\n"
        "#2BHK #VistaaraInteriors #InteriorDesign\n\n"
        f"2. Premium-looking rooms for {brand} start with a clear floor and one strong wall.\n"
        "#AffordableLuxury #HomeInspo #VistaaraInteriors\n\n"
        f"3. Evening light, warm lamps, and calm surfaces. That is the {brand} look.\n"
        "#2BHK #InteriorDesign #VistaaraInteriors\n"
    )


def local_desktop_actions(
    instruction: str,
    notes: NotepadMemory,
    document_text: str = "",
) -> list[Action]:
    """A fixed plan for the sentences Machaa already knows. No model call."""

    text = " ".join(instruction.strip().split())
    lowered = text.lower()
    if "machaa documents" in lowered and re.search(r"\bsave\b", lowered):
        body = notes.text.strip() or (
            "Machaa had no Notepad text yet. This file only says that. Nothing was invented."
        )
        filename = "vistaara-captions.txt" if "vistaara" in lowered or "vistaara" in notes.text.lower() else "machaa-note.txt"
        return [
            Action(
                "desktop.save_text",
                {"filename": filename, "text": body[:8000]},
                "Save the text in Machaa Documents",
            )
        ]
    if "calculator" in lowered:
        return [Action("desktop.open_calculator", {}, "Open Calculator")]
    if "file explorer" in lowered:
        return [Action("desktop.open_explorer", {}, "Open File Explorer")]
    if "notepad" in lowered and re.search(r"\bswitch\b", lowered):
        return [Action("desktop.switch_window", {"target": "notepad"}, "Switch to Notepad")]
    if re.search(r"\borganize\b", lowered) and ".docx" in lowered:
        found = re.search(r"([A-Za-z0-9][A-Za-z0-9._ -]{0,60}\.docx)", text)
        folder = "Posts"
        into = re.search(r"\binto\s+([A-Za-z0-9][A-Za-z0-9 _-]{0,40})", text)
        if into:
            folder = into.group(1).strip()
        filename = found.group(1) if found else "machaa-posts.docx"
        return [
            Action(
                "desktop.organize_file",
                {"filename": filename, "folder": folder},
                "Organize the file",
            )
        ]
    if "screenshot" in lowered and "screen" in lowered:
        return [Action("desktop.capture_screen", {}, "Take a screenshot of the screen")]
    if "notepad" in lowered and re.search(r"\b(summary|summarize|that document|the document)\b", lowered):
        body = document_text.strip() or (
            "Machaa looked for the last document and did not find one. Nothing was invented."
        )
        return [
            Action("desktop.open_notepad", {}, "Open Notepad"),
            Action("desktop.type_notepad", {"text": body[:4000]}, "Type the summary"),
        ]
    if "notepad" in lowered and re.search(r"\b(write|type|caption)\b", lowered):
        return [
            Action("desktop.open_notepad", {}, "Open Notepad"),
            Action(
                "desktop.type_notepad",
                {"text": stand_in_captions(text)},
                "Type three captions",
            ),
        ]
    if "notepad" in lowered:
        return [Action("desktop.open_notepad", {}, "Open Notepad")]
    if "open machaa" in lowered:
        return [Action("desktop.focus_dashboard", {}, "Open Machaa")]
    raise PlanningError("Machaa does not know a safe desktop action for that sentence.")


def approval_text(action: Action, documents) -> str:
    if action.tool == "desktop.type_notepad":
        preview = action.arguments["text"][:500]
        return (
            "Machaa wants to type this into the Notepad window it opened. "
            "Press Approve to type it, or Reject to leave Notepad unchanged.\n\n"
            + preview
        )
    if action.tool == "desktop.save_docx":
        name = action.arguments.get("filename", "the document")
        path = documents / name
        return (
            f"Machaa wants to save {name} at {path}. "
            "Press Approve to write that file, or Reject to change nothing."
        )
    if action.tool == "desktop.capture_screen":
        return (
            "Machaa wants to capture the screen and save machaa-screen.bmp "
            "in the Machaa Documents folder. Press Approve to capture it, or Reject to skip it."
        )
    if action.tool == "desktop.organize_file":
        return (
            f"Machaa wants to move {action.arguments.get('filename', 'the file')} "
            f"into {action.arguments.get('folder', 'a folder')} inside the Machaa Documents folder. "
            "Press Approve to move it, or Reject to change nothing."
        )
    if action.tool == "desktop.save_text":
        path = documents / action.arguments["filename"]
        return (
            f"Machaa wants to save a text file at {path}. "
            "Press Approve to write that file, or Reject to change nothing."
        )
    path = documents / action.arguments.get("filename", "")
    return (
        f"Machaa wants to read {path}. "
        "Press Approve to read it, or Reject to change nothing."
    )


async def execute_desktop(agent, task_id: str, task, plan) -> None:
    """Check desktop control, validate the plan, then ask the companion."""

    from machaa.agents.research import StepBudget

    if _needs_desktop_switch(task.instruction) and not _desktop_on(agent):
        agent.store.finish(
            task_id,
            status="blocked",
            summary=DESKTOP_OFF,
            block_reason=DESKTOP_OFF,
            agent="desktop",
        )
        return
    try:
        actions = await _propose(agent, task.instruction)
        validate_actions(agent.guardian, actions, agent.settings.max_steps)
    except PlanningError as exc:
        agent.store.finish(task_id, status="failed", summary=str(exc), agent="desktop")
        return
    except (QuotaError, TokenLimitError, DraftError) as exc:
        agent.store.finish(task_id, status="failed", summary=str(exc), agent="desktop")
        return
    deadline = time.monotonic() + agent.settings.task_timeout_seconds
    budget = StepBudget(agent.settings.max_steps, agent.store, task_id, deadline)
    artifacts = agent.settings.artifacts_dir / task_id
    artifacts.mkdir(parents=True, exist_ok=True)
    needs_browser = any(action.tool == "desktop.open_website" for action in actions)
    try:
        if needs_browser:
            async with agent.browser_factory(agent.settings) as workspace:
                gateway = ToolGateway(agent.guardian, agent._handlers(workspace, artifacts))
                await _run_actions(agent, task_id, actions, budget, gateway, deadline)
        else:
            gateway = ToolGateway(agent.guardian, agent._handlers(_IdleBrowser(), artifacts))
            await _run_actions(agent, task_id, actions, budget, gateway, deadline)
    except ApprovalDenied as exc:
        agent.store.finish(task_id, status="stopped", summary=str(exc), agent="desktop")
        return
    except DesktopOff as exc:
        agent.store.finish(
            task_id,
            status="blocked",
            summary=str(exc),
            block_reason=str(exc),
            agent="desktop",
        )
        return
    except CompanionUnavailable as exc:
        agent.store.finish(task_id, status="failed", summary=str(exc), agent="desktop")
        return
    except CompanionRefused as exc:
        agent.store.finish(task_id, status="failed", summary=str(exc), agent="desktop")
        return
    except ToolDenied as denied:
        agent.store.finish(
            task_id,
            status="blocked",
            summary=denied.reason,
            block_reason=denied.reason,
            agent="desktop",
        )
        return
    except TaskStopped:
        agent.store.finish(task_id, status="stopped", summary="Stopped.", agent="desktop")
        return
    except StepLimitReached:
        agent.store.finish(
            task_id,
            status="failed",
            summary="Machaa stopped because this task reached its step limit.",
            agent="desktop",
        )
        return
    except TimeoutError:
        agent.store.finish(
            task_id,
            status="failed",
            summary="Machaa stopped this task because it took too long.",
            agent="desktop",
        )
        return
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        agent.store.finish(task_id, status="failed", summary=message[:500], agent="desktop")
        return
    current = agent.store.get(task_id)
    if current is not None and current.stop_requested:
        agent.store.finish(task_id, status="stopped", summary="Stopped.", agent="desktop")
        return
    agent.store.finish(
        task_id,
        status="completed",
        summary=_summary(task.instruction, actions, agent),
        agent="desktop",
    )


def desktop_handlers(agent, workspace, artifacts) -> dict:
    """Handlers the gateway can run after the Guardian agrees."""

    async def open_notepad(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.open_notepad", {})
        return {"detail": result.get("detail") or "Opened Notepad.", "pid": result.get("pid")}

    async def open_calculator(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.open_calculator", {})
        return {"detail": result.get("detail") or "Opened Calculator."}

    async def open_explorer(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.open_explorer", {})
        return {
            "detail": result.get("detail") or "Opened File Explorer.",
            "verified": bool(result.get("verified", True)),
        }

    async def save_docx(arguments: dict) -> dict:
        result = await _companion_call(
            agent,
            "desktop.save_docx",
            {"filename": arguments["filename"], "content": arguments["content"]},
        )
        return {
            "detail": result.get("detail") or "Saved the Word document.",
            "verified": bool(result.get("verified", True)),
            "duplicate": bool(result.get("duplicate")),
            "path": result.get("path") or "",
        }

    async def open_docx(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.open_docx", {"filename": arguments["filename"]})
        return {
            "detail": result.get("detail") or "",
            "verified": bool(result.get("verified", False)),
            "path": result.get("path") or "",
        }

    async def switch_window(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.switch_window", {"target": arguments["target"]})
        return {"detail": result.get("detail") or "Switched windows.", "verified": bool(result.get("verified", True))}

    async def capture_screen(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.capture_screen", {})
        return {"detail": result.get("detail") or "Saved the screenshot.", "verified": bool(result.get("verified", True))}

    async def organize_file(arguments: dict) -> dict:
        result = await _companion_call(
            agent,
            "desktop.organize_file",
            {"filename": arguments["filename"], "folder": arguments["folder"]},
        )
        return {"detail": result.get("detail") or "Moved the file.", "verified": bool(result.get("verified", True))}

    async def type_notepad(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.type_notepad", {"text": arguments["text"]})
        agent.notes.text = arguments["text"]
        return {"detail": result.get("detail") or "Typed into Notepad."}

    async def save_text(arguments: dict) -> dict:
        result = await _companion_call(
            agent,
            "desktop.save_text",
            {"filename": arguments["filename"], "text": arguments["text"]},
        )
        return {"detail": result.get("detail") or "Saved the file."}

    async def read_file(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.read_file", {"filename": arguments["filename"]})
        return {"detail": result.get("detail") or "Read the file."}

    async def focus_dashboard(arguments: dict) -> dict:
        result = await _companion_call(agent, "desktop.focus_dashboard", {})
        return {"detail": result.get("detail") or "Opened the Machaa dashboard."}

    async def open_website(arguments: dict) -> dict:
        if not _desktop_on(agent):
            raise DesktopOff(DESKTOP_OFF)
        opened = await workspace.visit(arguments["url"])
        from machaa.agents.research import _refuse_final_url

        await _refuse_final_url(agent.guardian, workspace, opened["url"])
        shot = artifacts / "screenshot.png"
        artifacts.mkdir(parents=True, exist_ok=True)
        await workspace.screenshot(shot)
        opened["detail"] = opened.get("url") or "Opened the page in Machaa's browser."
        return opened

    return {
        "desktop.open_notepad": open_notepad,
        "desktop.open_calculator": open_calculator,
        "desktop.open_explorer": open_explorer,
        "desktop.save_docx": save_docx,
        "desktop.open_docx": open_docx,
        "desktop.switch_window": switch_window,
        "desktop.capture_screen": capture_screen,
        "desktop.organize_file": organize_file,
        "desktop.type_notepad": type_notepad,
        "desktop.save_text": save_text,
        "desktop.read_file": read_file,
        "desktop.focus_dashboard": focus_dashboard,
        "desktop.open_website": open_website,
    }


async def _companion_call(agent, action: str, arguments: dict) -> dict:
    companion = agent.companion
    if companion is None or not companion.configured():
        raise CompanionUnavailable(COMPANION_HELP)
    try:
        return await asyncio.to_thread(companion.call, action, arguments)
    except CompanionUnavailable:
        await asyncio.sleep(0.05)
        if companion is None or not companion.configured():
            raise CompanionUnavailable(COMPANION_HELP)
        return await asyncio.to_thread(companion.call, action, arguments)


def _desktop_on(agent) -> bool:
    gate = getattr(agent, "desktop_enabled", None)
    if gate is None:
        return False
    return bool(gate()) if callable(gate) else bool(gate)


def _needs_desktop_switch(instruction: str) -> bool:
    lowered = instruction.lower()
    if "open machaa" in lowered and "notepad" not in lowered and "calculator" not in lowered:
        return False
    return True


async def _run_actions(agent, task_id, actions, budget, gateway, deadline) -> None:
    for action in actions:
        current = agent.store.get(task_id)
        if current is None or current.stop_requested or current.status in TERMINAL_STATUSES:
            raise TaskStopped()
        if action.tool != "desktop.focus_dashboard" and not _desktop_on(agent):
            raise DesktopOff("Desktop control was turned off. Machaa stopped and did not continue.")
        if action.tool in _NEEDS_APPROVAL:
            question = approval_text(action, agent.documents_dir)
            agent.store.set_fields(
                task_id,
                status="needs_approval",
                summary=question,
                approval=question,
            )
            await _wait_for_approval(agent, task_id, deadline)
        await agent._call(
            task_id,
            budget,
            gateway,
            action.tool,
            action.arguments,
            action.label,
        )


async def _propose(agent, instruction: str) -> list[Action]:
    client = agent.gemini
    model = getattr(client, "model", "")
    configured = bool(getattr(client, "configured", False))
    from machaa.memory.recall import asks_for_document_summary, summary_for_notepad

    document_text = summary_for_notepad(agent.store) if asks_for_document_summary(instruction) else ""
    if client is None or model == "stand-in" or not configured or document_text:
        return local_desktop_actions(instruction, agent.notes, document_text=document_text)
    feedback = ""
    last = "The planner did not return a usable plan."
    for _attempt in range(2):
        try:
            raw = await asyncio.to_thread(client.plan_desktop, instruction, feedback, agent.settings.max_steps)
        except (QuotaError, TokenLimitError):
            raise
        except DraftError as exc:
            last = str(exc)
            feedback = last
            continue
        try:
            actions = actions_from_model(raw, agent.settings.max_steps)
            validate_actions(agent.guardian, actions, agent.settings.max_steps)
            return actions
        except PlanningError as exc:
            last = str(exc)
            feedback = last
    raise PlanningError(last)


async def _wait_for_approval(agent, task_id: str, deadline: float) -> None:
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError()
        task = agent.store.get(task_id)
        if task is None or task.status in TERMINAL_STATUSES or task.stop_requested:
            raise TaskStopped()
        if not _desktop_on(agent):
            raise DesktopOff("Desktop control was turned off. Machaa stopped and did not continue.")
        if task.pause_requested:
            await asyncio.sleep(0.05)
            continue
        if task.approval == "approved":
            agent.store.set_fields(task_id, approval="", status="running")
            return
        if task.approval == "rejected":
            raise ApprovalDenied(REJECTED)
        await asyncio.sleep(0.05)


def _summary(instruction: str, actions: list[Action], agent) -> str:
    labels = [action.label for action in actions]
    model = getattr(agent.gemini, "model", "")
    stand_in = model in {"", "stand-in"} or not bool(getattr(agent.gemini, "configured", False))
    if any(action.tool == "desktop.type_notepad" for action in actions):
        body = next(
            action.arguments.get("text", "")
            for action in actions
            if action.tool == "desktop.type_notepad"
        )
        if str(body).startswith("Summary of the last Machaa document"):
            return "Opened Notepad and typed a summary of the last document."
        if str(body).startswith("Machaa looked for the last document"):
            return "Opened Notepad. There was no earlier document to summarize."
        if stand_in:
            return (
                "Opened Notepad and typed three caption ideas. "
                "The captions are a stand-in on this computer, not a live Gemini call."
            )
        return f"Opened Notepad and typed three caption ideas. Written with {model}."
    if any(action.tool == "desktop.save_text" for action in actions):
        name = actions[-1].arguments.get("filename", "the file")
        return f"Saved {name} in the Machaa Documents folder after you approved it."
    if any(action.tool == "desktop.open_notepad" for action in actions):
        return "Opened Notepad."
    if any(action.tool == "desktop.open_calculator" for action in actions):
        return "Opened Calculator."
    if any(action.tool == "desktop.open_explorer" for action in actions):
        return "Opened File Explorer in the Machaa Documents folder."
    if any(action.tool == "desktop.focus_dashboard" for action in actions):
        return "Opened the Machaa dashboard."
    if labels:
        return labels[-1] + "."
    return "Finished the desktop action."


class _IdleBrowser:
    """Desktop plans that do not open a website never touch Chromium."""

    async def visit(self, url: str) -> dict:
        raise ToolDenied("Machaa blocked this action because the browser is not open.", "tool")

    async def screenshot(self, path) -> None:
        return None

    async def blank(self) -> None:
        return None
