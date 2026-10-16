"""Turn a social-post request into a short list of allowed actions.

The model may propose the list. Machaa checks every action with the Guardian
before a browser starts. A shell command is never an action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from machaa.core.errors import MachaaError
from machaa.core.guardian import ALLOWED_ARGS, ALLOWED_TOOLS, Guardian

_SHELL = re.compile(
    r"(os\.system|subprocess|shell\.exec|powershell|cmd\.exe|\bbash\b|\bsh\s+-c\b)",
    re.IGNORECASE,
)


class PlanningError(MachaaError):
    """The proposed plan cannot be run. Nothing was executed."""


@dataclass(frozen=True)
class Action:
    tool: str
    arguments: dict
    label: str


def default_social_actions(brand: str, topic: str, platform: str, audience: str) -> list[Action]:
    """The three actions a social post is expected to take."""

    query = (topic or "interior design").strip()[:300]
    return [
        Action("browser.search_google", {"query": query}, "Search design ideas"),
        Action("browser.screenshot", {}, "Take a screenshot"),
        Action(
            "image.find_licensed",
            {"query": f"{query} interior"[:300]},
            "Find a licensed reference image",
        ),
        Action(
            "content.write_social",
            {
                "brand": (brand or "the brand").strip()[:200],
                "topic": query,
                "platform": (platform or "Instagram").strip()[:40],
                "audience": (audience or "people who might hire this brand").strip()[:200],
            },
            "Write three captions",
        ),
    ]


def actions_from_model(raw: object, max_steps: int) -> list[Action]:
    """Read the model's list. This does not approve it."""

    if isinstance(raw, dict):
        raw = raw.get("actions")
    if not isinstance(raw, list) or not raw:
        raise PlanningError("The planner did not return a list of actions.")
    if len(raw) > max_steps:
        raise PlanningError("The plan has more steps than this task allows.")
    actions: list[Action] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlanningError("The planner returned an action Machaa cannot read.")
        tool = str(item.get("tool") or "").strip()
        if _SHELL.search(tool):
            raise PlanningError(
                "The planner asked for a shell command. Machaa does not run shell commands."
            )
        arguments = item.get("arguments")
        if not isinstance(arguments, dict):
            raise PlanningError("The planner returned an action with no arguments.")
        label = " ".join(str(item.get("label") or tool).split())[:120] or tool
        actions.append(Action(tool, dict(arguments), label))
    return actions


def validate_actions(guardian: Guardian, actions: list[Action], max_steps: int) -> None:
    """Refuse the whole plan if any action is illegal. No action has run yet."""

    if not actions:
        raise PlanningError("The planner returned an empty plan.")
    if len(actions) > max_steps:
        raise PlanningError("The plan has more steps than this task allows.")
    for action in actions:
        if _SHELL.search(action.tool) or action.tool not in ALLOWED_TOOLS:
            raise PlanningError(
                "The planner asked for an action that is not allowed. "
                "Machaa does not run shell commands."
            )
        if set(action.arguments) != ALLOWED_ARGS[action.tool]:
            raise PlanningError(
                "The planner asked for an action whose arguments are not allowed."
            )
        decision = guardian.review_planned_call(action.tool, action.arguments)
        if not decision.allowed:
            raise PlanningError(decision.reason)
