"""Refuse every browser profile except the one Machaa creates for itself."""

from __future__ import annotations

from pathlib import Path

from machaa.config import Settings
from machaa.core.errors import ProfileRefusal

# Path fragments that identify a person's installed browser profile.
_PERSONAL_PROFILE_MARKERS = (
    "google-chrome",
    "google/chrome",
    "chromium",
    "microsoft/edge",
    "microsoft edge",
    "user data",
)


def assert_dedicated_profile(settings: Settings) -> Path:
    """Return the dedicated profile directory, or refuse to continue.

    The directory must be inside Machaa's data directory. A path that
    points at Chrome, Chromium, or Edge on the owner's machine is refused
    before Playwright starts.
    """

    data_dir = settings.data_dir.resolve()
    profile = settings.browser_profile_dir.resolve()
    try:
        profile.relative_to(data_dir)
    except ValueError as exc:
        raise ProfileRefusal(
            "Refusing to use a browser profile outside the Machaa data directory. "
            "Machaa never attaches to a personal Chrome profile."
        ) from exc
    if profile == data_dir:
        raise ProfileRefusal("The browser profile must be its own directory inside the data folder.")
    lowered = str(profile).lower().replace("\\", "/")
    for marker in _PERSONAL_PROFILE_MARKERS:
        if marker in lowered:
            raise ProfileRefusal(
                "Refusing to attach to a personal Chrome, Chromium, or Edge profile."
            )
    return profile
