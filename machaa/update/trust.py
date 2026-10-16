"""Decide whether an update source is the official Machaa repository."""

from __future__ import annotations

import re

OFFICIAL_REPOS = frozenset(
    {
        "https://github.com/Karthikrapolu-ai/machaa",
        "https://github.com/Karthikrapolu-ai/machaa.git",
        "git@github.com:Karthikrapolu-ai/machaa.git",
        "ssh://git@github.com/Karthikrapolu-ai/machaa.git",
    }
)

_RELEASE = re.compile(r"^refs/tags/v\d+\.\d+\.\d+$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,80}$")


class UpdateRefused(Exception):
    """The update was not applied."""


def normalize_remote(remote: str) -> str:
    return (remote or "").strip().rstrip("/")


def is_official_remote(remote: str) -> bool:
    return normalize_remote(remote) in OFFICIAL_REPOS


def is_allowed_ref(ref: str, track_branch: str = "") -> bool:
    """Allow main and version tags. A draft branch only when the founder opted in."""

    name = (ref or "").strip()
    if not name or name.startswith("refs/pull/") or ".." in name:
        return False
    if name in {"main", "refs/heads/main"}:
        return True
    if _RELEASE.fullmatch(name):
        return True
    tracked = (track_branch or "").strip()
    if not tracked or not _BRANCH.fullmatch(tracked) or tracked in {"main", "master"}:
        return False
    return name in {tracked, f"refs/heads/{tracked}"}


def is_trusted_update(remote: str, ref: str, track_branch: str = "") -> bool:
    return is_official_remote(remote) and is_allowed_ref(ref, track_branch)


def parse_ls_remote(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            found.append((parts[0], parts[1]))
    return found


def choose_update(entries: list[tuple[str, str]], current: str, track_branch: str = "") -> dict | None:
    """Pick one allowed ref. Drafts and forks are never chosen."""

    main: tuple[str, str] | None = None
    release: tuple[str, str] | None = None
    tracked: tuple[str, str] | None = None
    wanted = (track_branch or "").strip()
    for sha, ref in entries:
        if not is_allowed_ref(ref, wanted):
            continue
        if wanted and ref in {wanted, f"refs/heads/{wanted}"}:
            tracked = (sha, ref)
        elif ref in {"main", "refs/heads/main"}:
            main = (sha, ref)
        elif _RELEASE.fullmatch(ref) and (release is None or ref > release[1]):
            release = (sha, ref)
    chosen = tracked or main or release
    if chosen is None:
        return None
    sha, ref = chosen
    label = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
    return {
        "available": sha != current,
        "sha": sha,
        "ref": ref,
        "version": label,
        "current": current,
    }
