"""Computer agent. Not implemented on Day 1.

This is the future home of personal desktop control: the mouse, the
keyboard, and apps on the owner's machine. It must go through the
Guardian, and it must never attach to a personal browser profile.
Voice activation ("open Machaa") belongs with the desktop companion,
not here, until that work is explicitly built.
"""

from machaa.agents.base import AgentInfo

COMPUTER_AGENT = AgentInfo(
    name="computer",
    available=False,
    summary=(
        "The computer agent is not built yet. "
        "Day 1 can search Google or open a public website."
    ),
)
