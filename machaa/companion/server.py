"""Local companion HTTP server. It binds to this computer only."""

from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from machaa.companion.actions import CompanionState, perform
from machaa.core.errors import CompanionRefused

_MAX_BODY = 200_000


class CompanionServer:
    """127.0.0.1 only, with a bearer token the browser never sees."""

    def __init__(self, token: str, documents: Path, port: int = 8788) -> None:
        if not token:
            raise RuntimeError("The companion needs a token that stays on this computer.")
        self.token = token
        self.state = CompanionState(documents)
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def bind(self, host: str = "127.0.0.1") -> None:
        if host not in {"127.0.0.1"}:
            raise RuntimeError("The companion only listens on this computer (127.0.0.1).")
        handler = _handler_factory(self)
        self._httpd = ThreadingHTTPServer((host, self.port), handler)
        self.port = int(self._httpd.server_address[1])

    def serve_forever(self, host: str = "127.0.0.1") -> None:
        self.bind(host)
        assert self._httpd is not None
        self._httpd.serve_forever()

    def start_background(self) -> None:
        self.bind("127.0.0.1")
        assert self._httpd is not None
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="machaa-companion",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()


def _handler_factory(server: CompanionServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/v1/act", "/v1/permission"}:
                self._send(404, {"ok": False, "error": "Not found."})
                return
            if not _authorized(self.headers.get("Authorization", ""), server.token):
                self._send(401, {"ok": False, "error": "The companion did not accept that request."})
                return
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit() or int(length) > _MAX_BODY:
                self._send(413, {"ok": False, "error": "That request is too large."})
                return
            raw = self.rfile.read(int(length))
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._send(400, {"ok": False, "error": "Machaa could not read that request."})
                return
            if not isinstance(payload, dict):
                self._send(400, {"ok": False, "error": "Machaa could not read that request."})
                return
            try:
                if self.path == "/v1/permission":
                    server.state.permission = bool(payload.get("enabled"))
                    body = {
                        "ok": True,
                        "enabled": server.state.permission,
                        "detail": "Desktop control updated on this computer.",
                    }
                else:
                    action = str(payload.get("action") or "")
                    arguments = payload.get("arguments") or {}
                    body = perform(server.state, action, arguments)
            except CompanionRefused as refused:
                self._send(403, {"ok": False, "error": str(refused)})
                return
            self._send(200, body)

        def log_message(self, fmt: str, *args) -> None:
            return

        def _send(self, status: int, body: dict) -> None:
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def _authorized(header: str, token: str) -> bool:
    expected = f"Bearer {token}"
    if len(header) != len(expected):
        return False
    return secrets.compare_digest(header, expected)


def main() -> None:
    """Start the companion. The Windows launcher calls this."""

    token = os.environ.get("MACHAA_COMPANION_TOKEN", "").strip()
    if not token:
        token_file = Path(os.environ.get("MACHAA_DATA_DIR", "data")) / "companion.token"
        if token_file.is_file():
            token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        print("The companion needs a token. Double-click start-machaa-windows.bat.")
        raise SystemExit(1)
    documents = Path(
        os.environ.get("MACHAA_DOCUMENTS_DIR", str(Path.home() / "Documents" / "Machaa"))
    ).expanduser()
    port = int(os.environ.get("MACHAA_COMPANION_PORT", "8788"))
    print("Machaa companion is listening only on this computer.")
    print("Leave this window open. It is not reachable from the internet.")
    print("Machaa will not click a Windows security prompt.")
    CompanionServer(token, documents, port).serve_forever("127.0.0.1")
