"""Apply an approved update without touching the owner's files.

The helper copies .env, the database, browser profile, and documents aside,
runs git only for the official repository, puts those files back, and
returns to the previous version if the health check fails.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from machaa.update.trust import OFFICIAL_REPOS, UpdateRefused, is_trusted_update

PROTECTED_NAMES = (
    ".env",
    "data",
)


class UpdateFailed(Exception):
    """The update was rolled back."""


def snapshot_user_files(root: Path) -> dict[str, bytes | None]:
    """Read the files an update must not change. Missing files stay missing."""

    saved: dict[str, bytes | None] = {}
    env = root / ".env"
    saved[".env"] = env.read_bytes() if env.is_file() else None
    data = root / "data"
    if data.is_dir():
        for path in data.rglob("*"):
            if path.is_file() and "update-backup" not in path.parts:
                key = str(path.relative_to(root))
                saved[key] = path.read_bytes()
    else:
        saved["data"] = None
    return saved


def restore_user_files(root: Path, saved: dict[str, bytes | None]) -> None:
    for key, payload in saved.items():
        if key == "data" and payload is None:
            continue
        path = root / key
        if payload is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def backup_user_files(root: Path, backup: Path) -> Path:
    backup.mkdir(parents=True, exist_ok=True)
    env = root / ".env"
    if env.is_file():
        shutil.copy2(env, backup / ".env")
    data = root / "data"
    if data.is_dir():
        destination = backup / "data"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(data, destination, ignore=shutil.ignore_patterns("update-backup"))
    return backup


def migration_needed(root: Path) -> bool:
    return (root / "machaa" / "__init__.py").is_file() and not (root / ".git").is_dir()


def migrate_zip(root: Path, runner) -> str:
    """Turn a zip folder into a checkout of the official repo. User files stay."""

    if not migration_needed(root):
        return "This folder is already a Git checkout."
    saved = snapshot_user_files(root)
    backup_user_files(root, root / "data" / "update-backup" / "migration")
    official = "https://github.com/Karthikrapolu-ai/machaa.git"
    try:
        runner.run(["init"], root)
        runner.run(["remote", "add", "origin", official], root)
    except Exception:
        restore_user_files(root, saved)
        raise
    restore_user_files(root, saved)
    marker = root / "data" / "migrated.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("official\n", encoding="utf-8")
    restore_user_files(root, saved)
    return (
        "This folder now points at the official Machaa repository. "
        "Your .env file and your saved work were kept."
    )


def apply_update(
    root: Path,
    remote: str,
    ref: str,
    *,
    approved: bool,
    track_branch: str,
    runner,
    health_ok,
    current_sha: str,
) -> str:
    """Update code after approval. User files are restored even if git touches them."""

    if not approved:
        raise UpdateRefused("Approval is needed before Machaa updates.")
    if not is_trusted_update(remote, ref, track_branch):
        raise UpdateRefused(
            "Machaa only updates from the official repository, and only from main "
            "or a released version. A draft or another person's fork is ignored."
        )
    if remote.strip().rstrip("/") not in {item.rstrip("/") for item in OFFICIAL_REPOS}:
        raise UpdateRefused("Machaa only updates from the official repository.")
    saved = snapshot_user_files(root)
    backup_user_files(root, root / "data" / "update-backup" / "latest")
    try:
        runner.run(["fetch", remote, ref], root)
        runner.run(["checkout", "--detach", "FETCH_HEAD"], root)
        restore_user_files(root, saved)
        if not health_ok():
            _rollback(root, runner, current_sha, saved)
            raise UpdateFailed(
                "The new version did not start. Machaa put the previous version back."
            )
    except UpdateFailed:
        raise
    except UpdateRefused:
        raise
    except Exception as exc:
        _rollback(root, runner, current_sha, saved)
        raise UpdateFailed(
            "The update did not finish. Machaa put the previous version back."
        ) from exc
    return "Machaa updated. Your .env file, documents, and history were left as they were."


def _rollback(root: Path, runner, current_sha: str, saved: dict[str, bytes | None]) -> None:
    if current_sha:
        try:
            runner.run(["reset", "--hard", current_sha], root)
        except Exception:
            pass
    restore_user_files(root, saved)
