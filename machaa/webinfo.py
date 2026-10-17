"""Which build the dashboard is serving. Used to bust caches and label the header."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from machaa import __version__

WEB_DIR = Path(__file__).resolve().parent / "web"
_SAFE = re.compile(r"[^0-9A-Za-z._-]")


def _commit() -> str:
    raw = os.environ.get("MACHAA_COMMIT", "").strip() or "nogit"
    cleaned = _SAFE.sub("", raw)[:12]
    return cleaned or "nogit"


def _file_hash() -> str:
    digest = hashlib.sha256((WEB_DIR / "app.js").read_bytes()).hexdigest()
    return digest[:8]


def asset_version() -> str:
    """Changes when the script or the recorded commit changes."""

    return f"{__version__}-{_commit()}-{_file_hash()}"


def build_label() -> str:
    """Plain text for the dashboard header."""

    return f"v{__version__} · {_commit()} · {_file_hash()}"
