"""Local companion HTTP server. It binds to this computer only."""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from machaa.companion.actions import CompanionState, perform
from machaa.core.errors import CompanionRefused

_MAX_BODY = 12_000_000


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
        if host == "0.0.0.0" or host not in {"127.0.0.1", ""}:
            raise RuntimeError("The companion only listens on this computer (127.0.0.1).")
        if host == "" and os.environ.get("MACHAA_COMPANION_DOCKER") != "1":
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

        def do_GET(self) -> None:  # noqa: N802
            if self._reject_remote():
                return
            if self.path not in {"/health", "/v1/health"}:
                self._send(404, {"ok": False, "error": "Not found."})
                return
            self._send(200, {"ok": True, "status": "ok"})

        def do_POST(self) -> None:  # noqa: N802
            if self._reject_remote():
                return
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

        def _reject_remote(self) -> bool:
            host = self.client_address[0] if self.client_address else ""
            if peer_allowed(host):
                return False
            self._send(403, {"ok": False, "error": "The companion only answers on this computer."})
            return True

        def _send(self, status: int, body: dict) -> None:
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def peer_allowed(address: str) -> bool:
    """Loopback, plus the private addresses Docker Desktop uses on Windows."""

    raw = (address or "").split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    return bool(ip.is_private and not ip.is_link_local)


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
        print("The companion needs a token. Double-click START-MACHAA.bat.")
        raise SystemExit(1)
    documents = Path(
        os.environ.get("MACHAA_DOCUMENTS_DIR", str(Path.home() / "Documents" / "Machaa"))
    ).expanduser()
    port = int(os.environ.get("MACHAA_COMPANION_PORT", "8788"))
    _write_pid()
    host = "127.0.0.1"
    if sys.platform == "win32" and os.environ.get("MACHAA_COMPANION_DOCKER") == "1":
        # Docker Desktop cannot open a program that listens only on 127.0.0.1.
        # Public internet addresses are still refused. The token is still required.
        host = ""
        print("If Windows asks to allow Python on private networks, choose Allow.")
        print("Machaa will not click that box for you.")
    print("Machaa companion is listening on this computer.")
    print("Leave this window open. It is not reachable from the internet.")
    print("Machaa will not click a Windows security prompt.")
    try:
        CompanionServer(token, documents, port).serve_forever(host)
    except OSError:
        print("The Windows Companion is already running. Leave that window open.")
        raise SystemExit(0) from None


def _write_pid() -> None:
    path = Path(os.environ.get("MACHAA_DATA_DIR", "data")) / "companion.pid"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        return
