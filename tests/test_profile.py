"""The browser profile must be Machaa's, never the owner's Chrome profile."""

from pathlib import Path

import pytest

from machaa.browser.profile import assert_dedicated_profile
from machaa.browser.workspace import PlaywrightWorkspace
from machaa.config import Settings
from machaa.core.errors import ProfileRefusal


def _settings(tmp_path: Path, profile: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    return Settings(
        host="127.0.0.1",
        port=8787,
        data_dir=data,
        browser_profile_dir=profile,
        artifacts_dir=data / "artifacts",
        database_path=data / "machaa.sqlite3",
        max_steps=8,
        task_timeout_seconds=5,
        navigation_timeout_ms=1000,
        headless=True,
        chromium_no_sandbox=True,
    )


def test_dedicated_profile_inside_the_data_dir_is_accepted(tmp_path):
    data = tmp_path / "data"
    profile = assert_dedicated_profile(_settings(tmp_path, data / "browser-profile"))
    assert profile == (data / "browser-profile").resolve()


def test_profile_outside_the_data_dir_is_refused(tmp_path):
    with pytest.raises(ProfileRefusal):
        assert_dedicated_profile(
            _settings(tmp_path, Path("/home/someone/.config/google-chrome/Default"))
        )


def test_personal_chrome_folder_name_is_refused_even_inside_data(tmp_path):
    data = tmp_path / "data"
    with pytest.raises(ProfileRefusal):
        assert_dedicated_profile(_settings(tmp_path, data / "google-chrome"))


async def test_workspace_refuses_before_launch(tmp_path):
    workspace = PlaywrightWorkspace(
        _settings(tmp_path, Path("/home/someone/Library/Application Support/Google/Chrome"))
    )
    with pytest.raises(ProfileRefusal):
        async with workspace:
            pass


def test_browser_source_does_not_attach_to_installed_chrome():
    text = Path("machaa/browser/workspace.py").read_text(encoding="utf-8")
    assert "channel=" not in text
    assert "connect_over_cdp" not in text
    assert "user_agent=" not in text
    assert "Chrome/131" not in text
    assert "launch_persistent_context" in text
    assert "user_data_dir" in text


@pytest.mark.browser
async def test_profile_file_survives_a_second_launch(tmp_path):
    profile = tmp_path / "data" / "browser-profile"
    settings = _settings(tmp_path, profile)
    async with PlaywrightWorkspace(settings):
        pass
    marker = profile / "machaa-profile-marker.txt"
    marker.write_text("kept", encoding="utf-8")
    async with PlaywrightWorkspace(settings):
        assert marker.read_text(encoding="utf-8") == "kept"
        assert profile.is_dir()
