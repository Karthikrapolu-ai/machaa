"""Research agent for Day 1.

The plan is fixed: search or open one public page, screenshot it, read
the visible text, and save a Markdown report. Text from the page is
saved. It is not treated as a new command.
"""

from __future__ import annotations

from pathlib import Path

from machaa.agents.planning import parse_research_request
from machaa.browser.workspace import PlaywrightWorkspace
from machaa.config import Settings
from machaa.core.errors import StepLimitReached, TaskStopped, ToolDenied
from machaa.core.guardian import Guardian
from machaa.core.tasks import TaskStore, utc_now
from machaa.reports.writer import render_report
from machaa.search.providers import provider_label
from machaa.search.session import perform_search
from machaa.tools.gateway import ToolGateway


class StepBudget:
    """Count actions and notice a stop request between them."""

    def __init__(self, max_steps: int, should_stop) -> None:
        self.max_steps = max_steps
        self.should_stop = should_stop
        self.used = 0

    def consume(self) -> None:
        if self.should_stop():
            raise TaskStopped()
        if self.used >= self.max_steps:
            raise StepLimitReached()
        self.used += 1


class ResearchAgent:
    """Run the Day 1 research plan through the tool gateway."""

    name = "research"

    def __init__(
        self,
        settings: Settings,
        store: TaskStore,
        guardian: Guardian,
        browser_factory=None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.guardian = guardian
        self.browser_factory = browser_factory or PlaywrightWorkspace

    async def run(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is None:
            return
        plan = parse_research_request(task.instruction)
        if plan is None:
            self.store.finish(
                task_id,
                status="completed",
                summary=(
                    "Day 1 can search Google or open one public website. "
                    "Try: Open Google and search for simple 2BHK interior design ideas."
                ),
                agent=self.name,
            )
            return
        artifacts = self.settings.artifacts_dir / task_id
        artifacts.mkdir(parents=True, exist_ok=True)
        budget = StepBudget(
            self.settings.max_steps,
            lambda: bool(self.store.get(task_id) and self.store.get(task_id).stop_requested),
        )
        page_url = ""
        page_title = ""
        page_text = ""
        site_blocked = False
        needs_human = False
        human_note = ""
        source_note = ""
        hits: list[dict] = []
        provider = ""
        done: list[str] = []
        try:
            async with self.browser_factory(self.settings) as workspace:
                gateway = ToolGateway(self.guardian, self._handlers(workspace, artifacts))
                if plan.kind == "search":
                    opened = await self._call(
                        task_id,
                        budget,
                        gateway,
                        "browser.search_google",
                        {"query": plan.query or ""},
                        "Search",
                    )
                    provider = str(opened.get("provider") or "")
                    hits = list(opened.get("hits") or [])
                    source_note = str(opened.get("note") or "")
                    needs_human = bool(opened.get("needs_human"))
                    human_note = source_note
                    if provider and provider != "google":
                        done.append(
                            f"Searched for {plan.query} with {provider_label(provider)}."
                        )
                    else:
                        done.append(f"Searched Google for {plan.query}.")
                else:
                    opened = await self._call(
                        task_id,
                        budget,
                        gateway,
                        "browser.visit_public_page",
                        {"url": plan.url or ""},
                        "Open the public page",
                    )
                    done.append(f"Opened {plan.url}.")
                page_url = str(opened.get("url") or "")
                page_title = str(opened.get("title") or "")
                page_text = str(opened.get("text") or "")
                site_blocked = bool(opened.get("site_blocked"))
                await self._call(
                    task_id,
                    budget,
                    gateway,
                    "browser.screenshot",
                    {},
                    "Take a screenshot",
                )
                done.append("Saved a screenshot.")
                extracted = await self._call(
                    task_id,
                    budget,
                    gateway,
                    "browser.extract_text",
                    {},
                    "Extract page text",
                )
                page_text = str(extracted.get("text") or page_text)
                done.append("Read the visible page text.")
                markdown = render_report(
                    task_id=task_id,
                    instruction=task.instruction,
                    page_url=page_url,
                    page_title=page_title,
                    page_text=page_text,
                    steps=done,
                    saved_at=utc_now(),
                    hits=hits if plan.kind == "search" else None,
                    source_note=source_note,
                )
                await self._call(
                    task_id,
                    budget,
                    gateway,
                    "report.save_markdown",
                    {"markdown": markdown},
                    "Save the research report",
                )
                done.append("Saved the research report.")
        except ToolDenied as denied:
            self.store.finish(
                task_id,
                status="blocked",
                summary=denied.reason,
                block_reason=denied.reason,
                agent=self.name,
                **_existing_artifacts(artifacts, page_url),
            )
            return
        except TaskStopped:
            self.store.finish(
                task_id,
                status="stopped",
                summary="Stopped.",
                agent=self.name,
                **_existing_artifacts(artifacts, page_url),
            )
            return
        except StepLimitReached:
            self.store.finish(
                task_id,
                status="failed",
                summary="Machaa stopped because this task reached its step limit.",
                agent=self.name,
                **_existing_artifacts(artifacts, page_url),
            )
            return
        current = self.store.get(task_id)
        if current is not None and current.stop_requested:
            self.store.finish(
                task_id,
                status="stopped",
                summary="Stopped.",
                agent=self.name,
                **_existing_artifacts(artifacts, page_url),
            )
            return
        if needs_human:
            summary = human_note or "Machaa needs a person to finish this search."
            if plan.query and plan.query not in summary:
                summary = f"{summary} Query: {plan.query}."
            self.store.finish(
                task_id,
                status="needs_human",
                summary=summary,
                agent=self.name,
                **_existing_artifacts(artifacts, page_url),
            )
            return
        if site_blocked and plan.kind != "search":
            self.store.finish(
                task_id,
                status="failed",
                summary=(
                    "The browser opened the page, but the site showed a robot check. "
                    "The screenshot and report were saved."
                ),
                agent=self.name,
                **_existing_artifacts(artifacts, page_url),
            )
            return
        if plan.kind == "search":
            if provider and provider != "google":
                summary = (
                    f"Searched for “{plan.query}” with {provider_label(provider)} "
                    f"and saved a report."
                )
            else:
                summary = f"Searched Google for “{plan.query}” and saved a report."
        else:
            summary = f"Opened {plan.url} and saved a report."
        self.store.finish(
            task_id,
            status="completed",
            summary=summary,
            agent=self.name,
            **_existing_artifacts(artifacts, page_url),
        )

    async def _call(
        self,
        task_id: str,
        budget: StepBudget,
        gateway: ToolGateway,
        tool: str,
        arguments: dict,
        label: str,
    ) -> dict:
        budget.consume()
        step_id = self.store.add_step(
            task_id,
            tool=tool,
            label=label,
            arguments=_step_arguments(tool, arguments),
            status="running",
        )
        try:
            result = await gateway.execute(tool, arguments)
        except ToolDenied as denied:
            self.store.finish_step(step_id, "blocked", denied.reason)
            raise
        except Exception as exc:
            self.store.finish_step(step_id, "failed", exc.__class__.__name__)
            raise
        detail = str(result.get("url") or "")[:500]
        self.store.finish_step(step_id, "completed", detail)
        return result

    def _handlers(self, workspace, artifacts: Path) -> dict:
        guardian = self.guardian

        async def search_google(arguments: dict) -> dict:
            opened = await perform_search(
                workspace,
                self.settings,
                guardian,
                arguments["query"],
            )
            final = str(opened.get("url") or "")
            if final and not opened.get("needs_human"):
                await _refuse_final_url(guardian, workspace, final)
            return opened

        async def visit_public_page(arguments: dict) -> dict:
            opened = await workspace.visit(arguments["url"])
            await _refuse_final_url(guardian, workspace, opened["url"])
            return opened

        async def extract_text(arguments: dict) -> dict:
            return {"text": await workspace.extract_text()}

        async def screenshot(arguments: dict) -> dict:
            await workspace.screenshot(artifacts / "screenshot.png")
            return {"saved": True}

        async def save_markdown(arguments: dict) -> dict:
            # The name is fixed. A tool argument cannot choose a path.
            (artifacts / "report.md").write_text(arguments["markdown"], encoding="utf-8")
            return {"saved": True}

        return {
            "browser.search_google": search_google,
            "browser.visit_public_page": visit_public_page,
            "browser.extract_text": extract_text,
            "browser.screenshot": screenshot,
            "report.save_markdown": save_markdown,
        }


async def _refuse_final_url(guardian: Guardian, workspace, url: str) -> None:
    """A redirect can land somewhere the original address did not."""

    decision = guardian.review_navigation(url, resolve=False)
    if decision.allowed:
        return
    await workspace.blank()
    raise ToolDenied(decision.reason, decision.category)


def _step_arguments(tool: str, arguments: dict) -> dict:
    if tool == "report.save_markdown":
        return {"markdown": "[saved to this task's report]"}
    return arguments


def _existing_artifacts(artifacts: Path, page_url: str) -> dict:
    screenshot = artifacts / "screenshot.png"
    report = artifacts / "report.md"
    return {
        "screenshot_path": str(screenshot) if screenshot.is_file() else None,
        "report_path": str(report) if report.is_file() else None,
        "page_url": page_url or None,
    }
