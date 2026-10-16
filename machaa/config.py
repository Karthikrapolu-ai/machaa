"""Runtime settings. Search API keys are optional and stay empty by default."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    return float(value)


@dataclass(frozen=True)
class Settings:
    """Local paths and limits. The browser profile always lives under data_dir."""

    host: str
    port: int
    data_dir: Path
    browser_profile_dir: Path
    artifacts_dir: Path
    database_path: Path
    max_steps: int
    task_timeout_seconds: float
    navigation_timeout_ms: int
    headless: bool
    chromium_no_sandbox: bool
    brave_search_api_key: str = ""
    google_search_api_key: str = ""
    google_search_cx: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("MACHAA_DATA_DIR", "data")).expanduser().resolve()
        profile = os.environ.get("MACHAA_BROWSER_PROFILE")
        profile_dir = (
            Path(profile).expanduser().resolve() if profile else data_dir / "browser-profile"
        )
        return cls(
            host=os.environ.get("MACHAA_HOST", "127.0.0.1"),
            port=_int(os.environ.get("MACHAA_PORT"), 8787),
            data_dir=data_dir,
            browser_profile_dir=profile_dir,
            artifacts_dir=data_dir / "artifacts",
            database_path=data_dir / "machaa.sqlite3",
            max_steps=max(1, _int(os.environ.get("MACHAA_MAX_STEPS"), 8)),
            task_timeout_seconds=_float(os.environ.get("MACHAA_TASK_TIMEOUT_SECONDS"), 120),
            navigation_timeout_ms=_int(os.environ.get("MACHAA_NAVIGATION_TIMEOUT_MS"), 30000),
            headless=_bool(os.environ.get("MACHAA_HEADLESS"), True),
            chromium_no_sandbox=_bool(os.environ.get("MACHAA_CHROMIUM_NO_SANDBOX"), False),
            brave_search_api_key=os.environ.get("MACHAA_BRAVE_SEARCH_API_KEY", "").strip(),
            google_search_api_key=os.environ.get("MACHAA_GOOGLE_SEARCH_API_KEY", "").strip(),
            google_search_cx=os.environ.get("MACHAA_GOOGLE_SEARCH_CX", "").strip(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
            or "gemini-2.5-flash",
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "home").mkdir(parents=True, exist_ok=True)
