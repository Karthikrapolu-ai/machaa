"""Run a checked social-post plan. The browser starts only after every action is allowed."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from machaa.agents.planner import Action, PlanningError, actions_from_model, validate_actions
from machaa.core.errors import StepLimitReached, TaskStopped, ToolDenied
from machaa.images.licensed import ImageResult
from machaa.llm.gemini import KEY_HELP, DraftError, MissingKeyError, QuotaError, TokenLimitError
from machaa.reports.docx_writer import DocumentError, write_social_document
from machaa.reports.writer import render_report
from machaa.tools.gateway import ToolGateway


async def execute_social(agent, task_id: str, task, plan) -> None:
    """Validate the whole plan, then run it. A bad plan never opens the browser."""

    from machaa.agents.research import StepBudget, _existing_artifacts

    artifacts = agent.settings.artifacts_dir / task_id
    artifacts.mkdir(parents=True, exist_ok=True)
    reset = getattr(agent.gemini, "reset_budget", None)
    if reset is not None:
        reset()
    agent._image = None
    agent._latest_hits = []
    agent._draft_model = ""
    page_url = ""
    try:
        actions = await _propose(agent, task.instruction)
        needs_browser = any(action.tool.startswith("browser.") for action in actions)
        deadline = time.monotonic() + agent.settings.task_timeout_seconds
        budget = StepBudget(agent.settings.max_steps, agent.store, task_id, deadline)

        async def run_actions(gateway: ToolGateway) -> None:
            nonlocal page_url
            for action in actions:
                result = await agent._call(
                    task_id,
                    budget,
                    gateway,
                    action.tool,
                    action.arguments,
                    action.label,
                )
                if action.tool == "browser.search_google":
                    page_url = str(result.get("url") or page_url)

        if needs_browser:
            async with agent.browser_factory(agent.settings) as workspace:
                gateway = ToolGateway(agent.guardian, agent._handlers(workspace, artifacts))
                await run_actions(gateway)
        else:
            gateway = ToolGateway(agent.guardian, agent._handlers(_NoBrowser(), artifacts))
            await run_actions(gateway)
    except PlanningError as exc:
        agent.store.finish(task_id, status="failed", summary=str(exc), agent=agent.name)
        return
    except MissingKeyError:
        agent.store.finish(
            task_id,
            status="needs_key",
            summary=KEY_HELP,
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    except (DraftError, DocumentError, QuotaError, TokenLimitError) as exc:
        agent.store.finish(
            task_id,
            status="failed",
            summary=str(exc),
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    except ToolDenied as denied:
        agent.store.finish(
            task_id,
            status="blocked",
            summary=denied.reason,
            block_reason=denied.reason,
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    except TaskStopped:
        agent.store.finish(
            task_id,
            status="stopped",
            summary="Stopped.",
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    except StepLimitReached:
        agent.store.finish(
            task_id,
            status="failed",
            summary="Machaa stopped because this task reached its step limit.",
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    except TimeoutError:
        agent.store.finish(
            task_id,
            status="failed",
            summary="Machaa stopped this task because it took too long.",
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        agent.store.finish(
            task_id,
            status="failed",
            summary=message[:500],
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    current = agent.store.get(task_id)
    if current is not None and current.stop_requested:
        agent.store.finish(
            task_id,
            status="stopped",
            summary="Stopped.",
            agent=agent.name,
            **_existing_artifacts(artifacts, page_url),
        )
        return
    model = agent._draft_model or getattr(agent.gemini, "model", "")
    if model == "stand-in":
        written = "The writing was a stand-in on this computer, not a live Gemini call."
    elif model:
        written = f"Written with {model}."
    else:
        written = "The Word document is saved."
    image = agent._image
    if image is not None and image.placeholder:
        picture = "No reusable licensed image was found, so the document uses a labelled placeholder."
    elif image is not None:
        picture = f"The reference image is {image.license_name}, credited to {image.artist}."
    else:
        picture = "No reference image was added."
    agent.store.finish(
        task_id,
        status="completed",
        summary=(
            f"Prepared the {plan.platform} document for {plan.brand} about “{plan.query}”. "
            f"{picture} {written}"
        ),
        agent=agent.name,
        **_existing_artifacts(artifacts, page_url),
    )


async def _propose(agent, instruction: str) -> list[Action]:
    feedback = ""
    last = "The planner did not return a usable plan."
    for _attempt in range(2):
        try:
            raw = await asyncio.to_thread(_call_plan, agent.gemini, instruction, feedback, agent.settings.max_steps)
        except (QuotaError, TokenLimitError, MissingKeyError):
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


def _call_plan(client, instruction: str, feedback: str, max_steps: int):
    return client.plan_actions(instruction, feedback, max_steps)


class _NoBrowser:
    """Used when a valid plan never asks for the browser."""

    async def search_google(self, query: str) -> dict:
        raise ToolDenied("Machaa blocked this action because the browser is not open.", "tool")

    async def visit(self, url: str) -> dict:
        raise ToolDenied("Machaa blocked this action because the browser is not open.", "tool")

    async def extract_text(self) -> str:
        return ""

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")

    async def blank(self) -> None:
        return None

    async def show_document(self, html: str) -> None:
        return None

    async def page_title(self) -> str:
        return ""


def social_handlers(agent, workspace, artifacts: Path) -> dict:
    """Handlers for the two social tools. Browser handlers stay on the agent."""

    async def find_licensed(arguments: dict) -> dict:
        from machaa.images.licensed import find_licensed_image

        result = await asyncio.to_thread(
            find_licensed_image,
            arguments["query"],
            artifacts,
            agent.guardian,
        )
        agent._image = result
        if result.placeholder:
            detail = "Placeholder. No reusable licensed image was found."
        else:
            detail = f"{result.license_name} — {result.title}"
        return {"saved": True, "detail": detail[:500]}

    async def write_social(arguments: dict) -> dict:
        if agent.gemini is None:
            raise MissingKeyError("Machaa needs a free Gemini key.")
        image: ImageResult | None = getattr(agent, "_image", None)
        sources = _notes(agent._latest_hits)
        note = _image_note(image)
        draft = await asyncio.to_thread(
            agent.gemini.write_social,
            arguments["brand"],
            arguments["topic"],
            arguments["platform"],
            arguments["audience"],
            sources,
            note,
        )
        agent._draft_model = str(draft.get("model") or "")
        payload = {
            "title": draft["title"],
            "brand": arguments["brand"],
            "platform": arguments["platform"],
            "audience": arguments["audience"],
            "topic": arguments["topic"],
            "concepts": draft["concepts"],
            "image": _image_payload(image),
        }
        image_path = image.path if image is not None else None
        await asyncio.to_thread(write_social_document, artifacts / "brief.docx", payload, image_path)
        from machaa.core.tasks import utc_now

        markdown = render_report(
            task_id=artifacts.name,
            instruction=arguments["topic"],
            page_url="",
            page_title=draft["title"],
            page_text=_markdown_body(payload),
            steps=["Wrote three social posts."],
            saved_at=utc_now(),
            hits=agent._latest_hits or None,
            source_note=note,
        )
        (artifacts / "report.md").write_text(markdown, encoding="utf-8")
        return {"saved": True, "detail": "Saved the Word document."}

    return {
        "image.find_licensed": find_licensed,
        "content.write_social": write_social,
    }


def _image_note(image: ImageResult | None) -> str:
    if image is None or image.placeholder:
        return (
            "No reusable licensed image was found. "
            "A placeholder will be used. Do not describe that placeholder as a photograph."
        )
    return (
        f"Reusable image: {image.title}. Artist: {image.artist}. "
        f"Licence: {image.license_name}. Licence URL: {image.license_url}. "
        f"Source: {image.source_page}. File: {image.file_url}."
    )


def _image_payload(image: ImageResult | None) -> dict:
    if image is None or image.placeholder:
        return {"placeholder": True}
    return {
        "placeholder": False,
        "title": image.title,
        "artist": image.artist,
        "license_name": image.license_name,
        "license_url": image.license_url,
        "source_page": image.source_page,
        "file_url": image.file_url,
    }


def _notes(hits: list[dict]) -> str:
    lines: list[str] = []
    for hit in hits:
        title = " ".join(str(hit.get("title") or "").split())
        url = str(hit.get("url") or "").strip()
        snippet = " ".join(str(hit.get("snippet") or "").split())
        if title and url.startswith("http"):
            lines.append(f"- {title} {url}")
            if snippet:
                lines.append(f"  {snippet}")
    return "\n".join(lines)[:8000]


def _markdown_body(payload: dict) -> str:
    lines = [
        f"Brand: {payload.get('brand')}",
        f"Platform: {payload.get('platform')}",
        f"Audience: {payload.get('audience')}",
        f"Topic: {payload.get('topic')}",
    ]
    image = payload.get("image") or {}
    if image.get("placeholder"):
        lines.append("Reference image: placeholder, not a photograph.")
    else:
        lines.append(
            "Reference image: "
            f"{image.get('title')} by {image.get('artist')} ({image.get('license_name')}). "
            f"{image.get('source_page')}"
        )
    for index, concept in enumerate(payload.get("concepts") or [], start=1):
        lines.append(f"Post {index}: {concept.get('name')}")
        lines.append(str(concept.get("caption") or ""))
        lines.append("Hashtags: " + " ".join(concept.get("hashtags") or []))
        lines.append("Image suggestion: " + str(concept.get("image_suggestion") or ""))
        lines.append("Sources: " + " ".join(concept.get("source_urls") or []))
    return "\n".join(lines)

