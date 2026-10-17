"""One instruction that researches, writes, saves, and opens a document.

The model may suggest labels. Machaa keeps its own order, runs independent
steps together, checks each result, and does not call an external step again
when that result is already stored.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path

from machaa.agents.planner import Action, PlanningError, actions_from_model
from machaa.agents.planning import ResearchPlan
from machaa.core.errors import (
    ApprovalDenied,
    CompanionRefused,
    CompanionUnavailable,
    DesktopOff,
    StepLimitReached,
    TaskStopped,
    ToolDenied,
)
from machaa.llm.gemini import KEY_HELP, DraftError, MissingKeyError, QuotaError, TokenLimitError
from machaa.reports.docx_writer import DocumentError

_EXTERNAL = frozenset(
    {
        "browser.search_google",
        "image.find_licensed",
        "content.write_social",
        "desktop.save_docx",
        "desktop.open_docx",
        "desktop.open_explorer",
    }
)


class WorkflowError(Exception):
    """A step ran, and its result did not match what Machaa asked for."""


def docx_name(brand: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", brand or "").strip("-").lower()[:40]
    if not slug or not slug[0].isalnum():
        slug = "machaa-posts"
    return f"{slug}.docx"


def skeleton_actions(plan: ResearchPlan) -> list[Action]:
    """The research half. Saving and opening are added only after the file exists."""

    topic = (plan.query or "interior design").strip()[:300]
    return [
        Action("browser.search_google", {"query": topic}, "Search design ideas", 0),
        Action(
            "image.find_licensed",
            {"query": f"{topic} interior"[:300]},
            "Find a licensed reference image",
            0,
        ),
        Action(
            "content.write_social",
            {
                "brand": (plan.brand or "the brand").strip()[:200],
                "topic": topic,
                "platform": (plan.platform or "Instagram").strip()[:40],
                "audience": (plan.audience or "people who might hire this brand").strip()[:200],
            },
            "Write three captions",
            1,
        ),
    ]


def reconcile_plan(proposed: list[Action], skeleton: list[Action]) -> list[Action]:
    """Keep Machaa's steps and order. A label from the model may be reused."""

    labels = {action.tool: action.label for action in proposed if action.tool}
    reconciled: list[Action] = []
    for step in skeleton:
        reconciled.append(
            Action(step.tool, dict(step.arguments), labels.get(step.tool, step.label), step.group)
        )
    return reconciled


def can_run_together(actions: list[Action]) -> bool:
    """Browser work stays one at a time. Desktop work is never overlapped."""

    if len(actions) < 2:
        return False
    browser = [action for action in actions if action.tool.startswith("browser.")]
    if len(browser) > 1:
        return False
    if any(action.tool.startswith("desktop.") for action in actions):
        return False
    return True


def group_actions(actions: list[Action]) -> list[list[Action]]:
    groups: list[list[Action]] = []
    for action in actions:
        if not groups or groups[-1][0].group != action.group:
            groups.append([action])
        else:
            groups[-1].append(action)
    return groups


async def run_independent(jobs: list) -> list:
    """Run coroutines together and keep every result, including a failure."""

    return list(await asyncio.gather(*[job() for job in jobs], return_exceptions=True))


def copy_matches(path: Path, data: bytes) -> bool:
    return path.is_file() and path.read_bytes() == data


async def execute_workflow(agent, task_id: str, task, plan: ResearchPlan) -> None:
    from machaa.agents.desktop import DESKTOP_OFF, _desktop_on, _wait_for_approval, approval_text
    from machaa.agents.research import StepBudget, _existing_artifacts
    from machaa.companion.policy import resolve_docx

    artifacts = agent.settings.artifacts_dir / task_id
    artifacts.mkdir(parents=True, exist_ok=True)
    agent._image = None
    agent._social_tone = plan.tone or ""
    agent._latest_hits = []
    agent._draft_model = ""
    filename = docx_name(plan.brand or "")
    page_url = ""
    deadline = time.monotonic() + agent.settings.task_timeout_seconds
    budget = StepBudget(agent.settings.max_steps, agent.store, task_id, deadline)
    try:
        actions = await _propose(agent, plan, task.instruction)
        async with agent.browser_factory(agent.settings) as workspace:
            from machaa.tools.gateway import ToolGateway

            gateway = ToolGateway(agent.guardian, agent._handlers(workspace, artifacts))
            for wave in group_actions(actions):
                _raise_if_stopped(agent, task_id)
                if can_run_together(wave):
                    outcomes = await run_independent(
                        [_step_job(agent, task_id, budget, gateway, action, artifacts) for action in wave]
                    )
                    for outcome in outcomes:
                        if isinstance(outcome, Exception):
                            raise outcome
                        if action_url(outcome):
                            page_url = action_url(outcome) or page_url
                else:
                    for action in wave:
                        result = await _run_step(agent, task_id, budget, gateway, action, artifacts)
                        page_url = action_url(result) or page_url
        _require_document(artifacts / "brief.docx")
        if not _desktop_on(agent):
            agent.store.finish(
                task_id,
                status="failed",
                summary=(
                    "The Word document is on the task card. "
                    + DESKTOP_OFF
                    + " Machaa did not copy it into Documents and did not open it."
                ),
                agent="workflow",
                **_existing_artifacts(artifacts, page_url),
            )
            return
        saved = await _save_copy(agent, task_id, budget, artifacts, filename, deadline)
        _raise_if_stopped(agent, task_id)
        opened = await _desktop_step(
            agent,
            task_id,
            budget,
            Action("desktop.open_docx", {"filename": filename}, "Open the Word document", 3),
        )
        _require_verified(opened, "Machaa did not open the Word document.")
        _raise_if_stopped(agent, task_id)
        explorer = await _desktop_step(
            agent,
            task_id,
            budget,
            Action("desktop.open_explorer", {}, "Show the folder", 4),
        )
        _require_verified(explorer, "Machaa did not open the folder.")
    except WorkflowError as exc:
        _finish_partial(agent, task_id, "failed", str(exc), artifacts, page_url)
        return
    except PlanningError as exc:
        _finish_partial(agent, task_id, "failed", str(exc), artifacts, page_url)
        return
    except MissingKeyError:
        _finish_partial(agent, task_id, "needs_key", KEY_HELP, artifacts, page_url)
        return
    except (DraftError, DocumentError, QuotaError, TokenLimitError) as exc:
        _finish_partial(agent, task_id, "failed", str(exc), artifacts, page_url)
        return
    except ApprovalDenied as exc:
        _finish_partial(agent, task_id, "stopped", str(exc), artifacts, page_url)
        return
    except DesktopOff as exc:
        _finish_partial(agent, task_id, "blocked", str(exc), artifacts, page_url, block=str(exc))
        return
    except (CompanionUnavailable, CompanionRefused) as exc:
        _finish_partial(agent, task_id, "failed", str(exc), artifacts, page_url)
        return
    except ToolDenied as denied:
        _finish_partial(agent, task_id, "blocked", denied.reason, artifacts, page_url, block=denied.reason)
        return
    except TaskStopped:
        _finish_partial(agent, task_id, "stopped", _stopped_text(agent, task_id), artifacts, page_url)
        return
    except StepLimitReached:
        _finish_partial(
            agent,
            task_id,
            "failed",
            "Machaa stopped because this task reached its step limit.",
            artifacts,
            page_url,
        )
        return
    except TimeoutError:
        _finish_partial(
            agent,
            task_id,
            "failed",
            "Machaa stopped this task because it took too long.",
            artifacts,
            page_url,
        )
        return
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        _finish_partial(agent, task_id, "failed", message[:500], artifacts, page_url)
        return
    if _stopped(agent, task_id):
        _finish_partial(agent, task_id, "stopped", _stopped_text(agent, task_id), artifacts, page_url)
        return
    path = resolve_docx(agent.documents_dir, filename)
    picture = _picture_sentence(agent)
    model = agent._draft_model or getattr(agent.gemini, "model", "")
    if model == "stand-in":
        written = "The writing was a stand-in on this computer, not a live Gemini call."
    elif model:
        written = f"Written with {model}."
    else:
        written = "The Word document is saved."
    agent.store.finish(
        task_id,
        status="completed",
        summary=(
            f"Created {filename} for {plan.brand} about “{plan.query}”. "
            f"Saved it in {path}. Opened it with its registered app. "
            f"File Explorer is open on that folder. {picture} {written} "
            f"{saved.get('detail', '')}"
        ).strip(),
        agent="workflow",
        **_existing_artifacts(artifacts, page_url),
    )


def _step_job(agent, task_id, budget, gateway, action, artifacts):
    async def run():
        return await _run_step(agent, task_id, budget, gateway, action, artifacts)

    return run


async def _run_step(agent, task_id, budget, gateway, action: Action, artifacts: Path) -> dict:
    _raise_if_stopped(agent, task_id)
    if _already_done(agent, task_id, action.tool):
        return {"detail": "Already finished. Machaa did not repeat it.", "verified": True, "duplicate": True}
    try:
        result = await agent._call(task_id, budget, gateway, action.tool, action.arguments, action.label)
    except Exception:
        if _already_done(agent, task_id, action.tool):
            return {"detail": "Already finished. Machaa did not repeat it.", "verified": True, "duplicate": True}
        _raise_if_stopped(agent, task_id)
        result = await agent._call(task_id, budget, gateway, action.tool, action.arguments, action.label)
    problem = _problem(action.tool, result, artifacts)
    if problem:
        _mark_tool_failed(agent, task_id, action.tool, problem)
        raise WorkflowError(problem)
    return result


async def _save_copy(agent, task_id, budget, artifacts: Path, filename: str, deadline: float) -> dict:
    from machaa.agents.desktop import _wait_for_approval, approval_text
    from machaa.companion.policy import resolve_docx
    from machaa.tools.gateway import ToolGateway

    source = artifacts / "brief.docx"
    data = source.read_bytes()
    path = resolve_docx(agent.documents_dir, filename)
    if copy_matches(path, data):
        detail = f"Saved {filename} in the Machaa Documents folder."
        return {"detail": detail, "verified": True, "duplicate": True, "path": str(path)}
    content = base64.b64encode(data).decode("ascii")
    action = Action(
        "desktop.save_docx",
        {"filename": filename, "content": content},
        "Save the Word document",
        2,
    )
    decision = agent.guardian.review_tool_call(action.tool, action.arguments)
    if not decision.allowed:
        raise ToolDenied(decision.reason, decision.category)
    agent.store.set_fields(
        task_id,
        status="needs_approval",
        summary=approval_text(action, agent.documents_dir),
        approval=approval_text(action, agent.documents_dir),
    )
    await _wait_for_approval(agent, task_id, deadline)
    if copy_matches(path, data):
        return {
            "detail": f"Saved {filename} in the Machaa Documents folder.",
            "verified": True,
            "duplicate": True,
            "path": str(path),
        }
    gateway = ToolGateway(agent.guardian, agent._handlers(_ClosedBrowser(), artifacts))
    result = await _run_step(agent, task_id, budget, gateway, action, artifacts)
    if not copy_matches(path, data) and not result.get("verified"):
        raise WorkflowError("Machaa could not confirm the Word file in the Machaa Documents folder.")
    return result


async def _desktop_step(agent, task_id, budget, action: Action) -> dict:
    from machaa.tools.gateway import ToolGateway

    decision = agent.guardian.review_tool_call(action.tool, action.arguments)
    if not decision.allowed:
        raise ToolDenied(decision.reason, decision.category)
    artifacts = agent.settings.artifacts_dir / task_id
    gateway = ToolGateway(agent.guardian, agent._handlers(_ClosedBrowser(), artifacts))
    return await _run_step(agent, task_id, budget, gateway, action, artifacts)


async def _propose(agent, plan: ResearchPlan, instruction: str) -> list[Action]:
    skeleton = skeleton_actions(plan)
    client = agent.gemini
    planner = getattr(client, "plan_workflow", None)
    raw = None
    if planner is not None:
        try:
            raw = await asyncio.to_thread(planner, instruction, "", agent.settings.max_steps)
        except (QuotaError, TokenLimitError):
            raise
        except (MissingKeyError, DraftError, PlanningError):
            raw = None
    if raw is None:
        return skeleton
    try:
        proposed = actions_from_model(raw, agent.settings.max_steps)
    except PlanningError:
        return skeleton
    return reconcile_plan(proposed, skeleton)


def _problem(tool: str, result: dict, artifacts: Path) -> str:
    if not isinstance(result, dict):
        return "Machaa could not read the result of that step."
    if tool == "browser.search_google":
        if result.get("needs_human"):
            return str(result.get("note") or "The search needs a person. Machaa did not continue.")
        if not result.get("hits") and not result.get("url"):
            return "The search did not return a page Machaa could use."
        return ""
    if tool == "image.find_licensed":
        detail = str(result.get("detail") or "")
        if "Placeholder" in detail or "licence" in detail.lower() or "license" in detail.lower() or result.get("saved"):
            return ""
        return "Machaa could not confirm the image credit."
    if tool == "content.write_social":
        document = artifacts / "brief.docx"
        if not document.is_file():
            return "The Word document was not created."
        text = _plain_docx(document)
        if "Hook:" not in text or "Hashtags:" not in text:
            return "The Word document is missing the captions Machaa expected."
        return ""
    if tool in {"desktop.save_docx", "desktop.open_docx", "desktop.open_explorer"}:
        if result.get("duplicate"):
            return ""
        if result.get("verified") is False:
            return str(result.get("detail") or "Machaa could not confirm that step.")
        detail = str(result.get("detail") or "")
        if tool == "desktop.open_docx" and "Opened" not in detail:
            return "Machaa did not open the Word document."
        if tool == "desktop.open_explorer" and "Explorer" not in detail and "folder" not in detail.lower():
            return "Machaa did not open the folder."
        return ""
    return ""


def _require_document(path: Path) -> None:
    if not path.is_file():
        raise WorkflowError("The Word document was not created.")
    text = _plain_docx(path)
    if "Hook:" not in text or "Hashtags:" not in text:
        raise WorkflowError("The Word document is missing the captions Machaa expected.")


def _require_verified(result: dict, message: str) -> None:
    if not isinstance(result, dict):
        raise WorkflowError(message)
    if result.get("duplicate"):
        return
    detail = str(result.get("detail") or "")
    if result.get("verified") is False or not detail:
        raise WorkflowError(message)


def _plain_docx(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def _already_done(agent, task_id: str, tool: str) -> bool:
    if tool not in _EXTERNAL:
        return False
    current = agent.store.get(task_id)
    if current is None:
        return False
    return any(step.tool == tool and step.status == "completed" for step in current.steps)


def _mark_tool_failed(agent, task_id: str, tool: str, detail: str) -> None:
    """Mark this tool's step, not whichever step finished last in a parallel wave."""

    current = agent.store.get(task_id)
    if current is None:
        return
    matches = [step for step in current.steps if step.tool == tool]
    if not matches:
        return
    agent.store.finish_step(matches[-1].id, "failed", detail[:500])


def _raise_if_stopped(agent, task_id: str) -> None:
    if _stopped(agent, task_id):
        raise TaskStopped()


def _stopped(agent, task_id: str) -> bool:
    current = agent.store.get(task_id)
    return current is None or bool(current.stop_requested) or current.status in {"stopped", "failed", "blocked"}


def _stopped_text(agent, task_id: str) -> str:
    current = agent.store.get(task_id)
    done = []
    if current is not None:
        done = [step.label for step in current.steps if step.status == "completed"]
    if done:
        return (
            "Stopped. Finished: "
            + "; ".join(done)
            + ". Machaa did not continue, and it did not mark the task done."
        )
    return "Stopped. No step had finished. Machaa did not mark the task done."


def _picture_sentence(agent) -> str:
    image = getattr(agent, "_image", None)
    if image is not None and getattr(image, "placeholder", False):
        return "No reusable licensed image was found, so the document uses a labelled placeholder."
    if image is not None:
        return f"The reference image is {image.license_name}, credited to {image.artist}."
    return "No reference image was added."


def action_url(result: dict) -> str:
    if isinstance(result, dict):
        return str(result.get("url") or "")
    return ""


def _finish_partial(agent, task_id: str, status: str, summary: str, artifacts: Path, page_url: str, block: str | None = None) -> None:
    from machaa.agents.research import _existing_artifacts

    current = agent.store.get(task_id)
    if current is not None and current.status in {"completed", "failed", "blocked", "stopped", "needs_human", "needs_key"}:
        return
    agent.store.finish(
        task_id,
        status=status,
        summary=summary[:500],
        block_reason=block,
        agent="workflow",
        **_existing_artifacts(artifacts, page_url),
    )


class _ClosedBrowser:
    async def search_google(self, query: str) -> dict:
        raise ToolDenied("Machaa blocked this action because the browser is not open.", "tool")

    async def visit(self, url: str) -> dict:
        raise ToolDenied("Machaa blocked this action because the browser is not open.", "tool")

    async def extract_text(self) -> str:
        return ""

    async def screenshot(self, path: Path) -> None:
        return None

    async def blank(self) -> None:
        return None

    async def show_document(self, html: str) -> None:
        return None

    async def page_title(self) -> str:
        return ""
