"""Errors raised by Machaa. These are not prompts; callers must handle them."""


class MachaaError(Exception):
    """Base error for Machaa."""


class ToolDenied(MachaaError):
    """The Guardian refused a tool call. The handler must not run."""

    def __init__(self, reason: str, category: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.category = category


class TaskStopped(MachaaError):
    """The owner pressed stop."""


class StepLimitReached(MachaaError):
    """The task used every step it is allowed."""


class ProfileRefusal(MachaaError):
    """The browser profile is not Machaa's dedicated profile."""


class ApprovalDenied(MachaaError):
    """The owner rejected a desktop action. Nothing was changed."""


class DesktopOff(MachaaError):
    """Desktop control is switched off."""


class CompanionUnavailable(MachaaError):
    """The Windows Companion is not reachable on this computer."""


class CompanionRefused(MachaaError):
    """The companion refused an action. The action did not run."""


class VoiceUnavailable(MachaaError):
    """Speech recognition is not available. Typing still works."""
