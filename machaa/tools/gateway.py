"""Run a tool only after the Guardian allows that exact call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from machaa.core.errors import ToolDenied
from machaa.core.guardian import ALLOWED_TOOLS, Guardian

Handler = Callable[[dict], Awaitable[dict]]


class ToolGateway:
    """The only path from an agent to a browser or report action."""

    def __init__(self, guardian: Guardian, handlers: dict[str, Handler]) -> None:
        unknown = set(handlers) - ALLOWED_TOOLS
        if unknown:
            raise ValueError(
                "Refusing to register tools that are not allowlisted: " + ", ".join(sorted(unknown))
            )
        self.guardian = guardian
        self._handlers = dict(handlers)

    async def execute(self, tool: str, arguments: dict) -> dict:
        decision = self.guardian.review_tool_call(tool, arguments)
        if not decision.allowed:
            raise ToolDenied(decision.reason, decision.category)
        handler = self._handlers.get(tool)
        if handler is None:
            raise ToolDenied(
                "Machaa blocked this action because it is not on the allowlist of safe browser actions.",
                "tool",
            )
        result = await handler(arguments)
        if not isinstance(result, dict):
            raise ToolDenied("Machaa blocked this action because the result was not usable.", "tool")
        return result
