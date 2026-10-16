"""Shared description of an agent. Execution stays in each agent module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentInfo:
    """What the orchestrator can tell the owner about an agent."""

    name: str
    available: bool
    summary: str
