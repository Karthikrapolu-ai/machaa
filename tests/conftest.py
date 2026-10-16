"""Shared settings for tests. Each test gets its own data directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from machaa.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    config = Settings(
        host="127.0.0.1",
        port=8787,
        data_dir=data,
        browser_profile_dir=data / "browser-profile",
        artifacts_dir=data / "artifacts",
        database_path=data / "machaa.sqlite3",
        max_steps=8,
        task_timeout_seconds=5,
        navigation_timeout_ms=20000,
        headless=True,
        chromium_no_sandbox=True,
    )
    config.ensure_dirs()
    return config
