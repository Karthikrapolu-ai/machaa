"""Start and stop Machaa once.

The Windows files START-MACHAA.bat and STOP-MACHAA.bat call this module.
A second start does not open another copy when the first one is still running.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StartPlan:
    already_running: bool
    spawn: bool
    message: str


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def read_pid(path: Path) -> int:
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text.isdigit() else 0


def prepare_start(root: Path, *, alive=pid_alive, listening=port_open) -> StartPlan:
    """Decide whether a new Machaa should be started."""

    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    pid = read_pid(data / "machaa.pid")
    if pid and alive(pid):
        return StartPlan(
            True,
            False,
            "Machaa is already running. Open http://127.0.0.1:8787",
        )
    if listening(8787):
        return StartPlan(
            True,
            False,
            "Machaa is already running on this computer. Open http://127.0.0.1:8787",
        )
    return StartPlan(False, True, "Starting Machaa.")


def mark_started(root: Path, pid: int) -> None:
    path = root / "data" / "machaa.pid"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def docker_available() -> str:
    """Return running, not_running, or not_installed. No install is attempted."""

    if shutil.which("docker") is None:
        return "not_installed"
    try:
        completed = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "not_running"
    return "running" if completed.returncode == 0 else "not_running"


def prepare_companion(root: Path, *, platform: str = sys.platform, alive=pid_alive, listening=port_open) -> StartPlan:
    """Start the Windows Companion once. Other systems only open the dashboard."""

    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    pid = read_pid(data / "companion.pid")
    if pid and alive(pid):
        return StartPlan(True, False, "The Windows Companion is already running.")
    if listening(8788):
        return StartPlan(True, False, "The Windows Companion is already running.")
    if platform != "win32":
        return StartPlan(
            False,
            False,
            "The Windows Companion runs on a Windows PC. The dashboard can still start.",
        )
    return StartPlan(False, True, "Starting the Windows Companion.")


def ensure_docker(probe=None, launch=None) -> str:
    """Return running, not_running, or not_installed. Start Docker only when it is installed."""

    check = probe or docker_available
    begin = launch or _launch_docker
    state = check()
    if state != "not_running":
        return state
    begin()
    return check()


def prepare_stop(root: Path, *, alive=pid_alive, killer=None) -> list[str]:
    """Stop recorded processes and clear their locks. The caller stops Docker."""

    for name in ("machaa.pid", "companion.pid"):
        path = root / "data" / name
        pid = read_pid(path)
        if pid and alive(pid) and killer is not None:
            killer(pid)
        elif pid and alive(pid) and killer is None:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        if path.is_file():
            path.unlink()
    return ["docker compose stop"]


def start(root: Path | None = None) -> int:
    folder = (root or Path.cwd()).resolve()
    plan = prepare_start(folder)
    print(plan.message)
    if plan.already_running:
        _open_browser()
        return 0
    docker = ensure_docker()
    if docker == "not_installed":
        print("Docker is not installed. Install Docker Desktop, open it, and double-click START-MACHAA.bat again.")
        print("https://www.docker.com/products/docker-desktop/")
        return 1
    if docker != "running":
        print("Docker is installed but not running. Open Docker Desktop, wait until it is ready, and double-click START-MACHAA.bat again.")
        return 1
    _ensure_companion_token(folder)
    companion = prepare_companion(folder)
    print(companion.message)
    if companion.spawn:
        _spawn_companion(folder)
    try:
        note = _maybe_migrate(folder)
    except Exception:
        note = "Machaa could not finish the one-time folder setup. Your .env file and saved work were kept."
    if note:
        print(note)
    mark_started(folder, os.getpid())
    print("Leave this window open. Machaa will be at http://127.0.0.1:8787")
    _open_browser()
    completed = subprocess.run(
        ["docker", "compose", "up", "--build"],
        cwd=folder,
        env=_compose_env(folder),
        check=False,
    )
    return int(completed.returncode)


def stop(root: Path | None = None) -> int:
    folder = (root or Path.cwd()).resolve()
    prepare_stop(folder)
    if shutil.which("docker"):
        subprocess.run(["docker", "compose", "stop"], cwd=folder, check=False)
    print("Machaa has stopped.")
    return 0


def _launch_docker() -> None:
    if shutil.which("docker") is None:
        return
    try:
        subprocess.run(
            ["docker", "desktop", "start"],
            check=False,
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _spawn_companion(root: Path) -> None:
    env = _compose_env(root)
    documents = Path.home() / "Documents" / "Machaa"
    documents.mkdir(parents=True, exist_ok=True)
    env["MACHAA_DOCUMENTS_DIR"] = str(documents)
    env["MACHAA_COMPANION_PORT"] = "8788"
    proc = subprocess.Popen([sys.executable, "-m", "machaa.companion"], cwd=root, env=env)
    (root / "data" / "companion.pid").write_text(str(proc.pid), encoding="utf-8")


def _compose_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    token = root / "data" / "companion.token"
    if token.is_file():
        env["MACHAA_COMPANION_TOKEN"] = token.read_text(encoding="utf-8").strip()
    env.setdefault("MACHAA_COMPANION_URL", "http://host.docker.internal:8788")
    return env


def _maybe_migrate(root: Path) -> str:
    from machaa.update.engine import migration_needed, migrate_zip
    from machaa.updater import ProcessGit

    if not migration_needed(root):
        return ""
    if shutil.which("git") is None:
        return "Git is not installed, so this zip folder was left as it is. Your files were not changed."
    return migrate_zip(root, ProcessGit())


def _ensure_companion_token(root: Path) -> None:
    token = root / "data" / "companion.token"
    if token.is_file() and token.read_text(encoding="utf-8").strip():
        return
    import secrets

    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(secrets.token_urlsafe(32), encoding="utf-8")


def _open_browser() -> None:
    import webbrowser

    webbrowser.open("http://127.0.0.1:8787")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "start"
    if command == "stop":
        return stop()
    if command == "start":
        return start()
    print("Use start or stop.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
