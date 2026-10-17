"""Call the Windows Companion from the Machaa server. Localhost only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from machaa.core.errors import CompanionRefused, CompanionUnavailable

COMPANION_HELP = (
    "The Windows Companion is not running. "
    "Double-click START-MACHAA.bat and leave the Machaa Companion window open. "
    "Nothing was opened."
)


class CompanionClient:
    """Authenticated requests to 127.0.0.1. The token is not sent to the browser."""

    def __init__(self, url: str, token: str, timeout: float = 20) -> None:
        self.url = (url or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.url and self.token)

    def call(self, action: str, arguments: dict) -> dict:
        return self._post("/v1/act", {"action": action, "arguments": arguments})

    def set_permission(self, enabled: bool) -> dict:
        if not self.configured():
            return {"ok": True, "enabled": enabled}
        return self._post("/v1/permission", {"enabled": bool(enabled)})

    def _post(self, path: str, payload: dict) -> dict:
        if not self.configured():
            raise CompanionUnavailable(COMPANION_HELP)
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CompanionRefused(_error_message(exc)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise CompanionUnavailable(COMPANION_HELP) from None
        if not isinstance(parsed, dict) or not parsed.get("ok"):
            message = "The companion refused that action."
            if isinstance(parsed, dict) and parsed.get("error"):
                message = str(parsed["error"])
            raise CompanionRefused(message)
        return parsed


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        parsed = json.loads(exc.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        parsed = {}
    if isinstance(parsed, dict) and parsed.get("error"):
        return str(parsed["error"])[:500]
    if exc.code == 401:
        return "The companion did not accept that request."
    return "The companion refused that action."
