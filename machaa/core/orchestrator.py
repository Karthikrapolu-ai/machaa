"""Day 1 router. Later this is the multi-agent orchestrator."""

from __future__ import annotations

import re
from dataclasses import dataclass

from machaa.agents.computer import COMPUTER_AGENT
from machaa.agents.planning import parse_research_request
from machaa.agents.work import WORK_AGENT

_COMPUTER = re.compile(
    r"\b(my desktop|my computer|move the mouse|control my (screen|computer|desktop)|click the)\b",
    re.IGNORECASE,
)
_WORK = re.compile(
    r"\b(write the code|refactor|edit the (file|code)|open a pull request|run the tests)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Route:
    agent: str
    available: bool
    message: str


class DayOneOrchestrator:
    """Send a sentence to research, or explain that another agent is not here yet."""

    def route(self, instruction: str) -> Route:
        if parse_research_request(instruction) is not None:
            return Route("research", True, "")
        if _COMPUTER.search(instruction):
            return Route(COMPUTER_AGENT.name, False, COMPUTER_AGENT.summary)
        if _WORK.search(instruction):
            return Route(WORK_AGENT.name, False, WORK_AGENT.summary)
        return Route(
            "research",
            False,
            "Machaa can search the web, open one public website, or write a Word document. "
            "Try: Write a Word document about simple 2BHK interior design ideas.",
        )
