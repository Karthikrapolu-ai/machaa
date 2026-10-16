"""Separate update helper.

Run ``python -m machaa.updater`` with a small JSON plan. It does not import
the dashboard, so it can still roll back if the dashboard fails to start.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from machaa.update.engine import UpdateFailed, apply_update
from machaa.update.trust import UpdateRefused


class ProcessGit:
    def run(self, args: list[str], cwd: Path) -> str:
        import subprocess

        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "git failed").strip()
            raise RuntimeError(message[:500])
        return completed.stdout


def health_ok(url: str = "http://127.0.0.1:8787/api/health") -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Machaa updater needs a plan file.")
        return 1
    plan = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    root = Path(plan.get("root") or ".").resolve()
    try:
        message = apply_update(
            root,
            str(plan.get("remote") or ""),
            str(plan.get("ref") or ""),
            approved=bool(plan.get("approved")),
            track_branch=str(plan.get("track_branch") or ""),
            runner=ProcessGit(),
            health_ok=lambda: health_ok(str(plan.get("health_url") or "http://127.0.0.1:8787/api/health")),
            current_sha=str(plan.get("current_sha") or ""),
        )
    except (UpdateRefused, UpdateFailed) as exc:
        print(str(exc))
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
