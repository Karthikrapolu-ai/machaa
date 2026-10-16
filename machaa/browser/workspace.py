"""Playwright Chromium with a profile that belongs to Machaa.

Launch uses Playwright's own Chromium and a dedicated user-data directory.
It does not select the owner's installed Chrome and it does not attach to
a browser that is already running. The profile path is checked first.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

from machaa.browser.profile import assert_dedicated_profile
from machaa.browser.urls import google_search_url, is_google_host
from machaa.config import Settings

# A normal desktop browser string. Playwright's default says "HeadlessChrome",
# which makes ordinary sites treat the dedicated browser as a test harness.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_CONSENT_BUTTON = re.compile(
    r"^(reject all|accept all|i agree|accept everything|reject everything)$",
    re.IGNORECASE,
)
_ROBOT_MARKERS = (
    "unusual traffic from your computer",
    "our systems have detected unusual traffic",
    "detected unusual traffic",
)


class PlaywrightWorkspace:
    """One Chromium window for one task, then closed."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> PlaywrightWorkspace:
        profile = assert_dedicated_profile(self.settings)
        profile.mkdir(parents=True, exist_ok=True)
        try:
            return await self._launch(profile)
        except (Exception, asyncio.CancelledError):
            await self.close()
            raise

    async def _launch(self, profile: Path) -> PlaywrightWorkspace:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_args = [
            "--disable-sync",
            "--disable-extensions",
            "--disable-default-apps",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-dev-shm-usage",
            "--disable-translate",
        ]
        if self.settings.chromium_no_sandbox:
            # Used in Docker, where the process is already non-root and
            # capabilities are dropped. It is not used to reach a personal profile.
            launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox"])
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=self.settings.headless,
            accept_downloads=False,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            user_agent=_USER_AGENT,
            args=launch_args,
            ignore_https_errors=False,
        )
        self._context.on("download", lambda download: asyncio.create_task(download.cancel()))
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()
        self._page.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        self._page.set_default_timeout(self.settings.navigation_timeout_ms)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def blank(self) -> None:
        if self._page is not None:
            try:
                await self._page.goto("about:blank", wait_until="domcontentloaded")
            except Exception:
                pass

    async def search_google(self, query: str) -> dict:
        url = google_search_url(query)
        opened = await self._open(url)
        await self._dismiss_google_consent()
        if _host(self._page.url).startswith("consent."):
            opened = await self._open(url)
            await self._dismiss_google_consent()
        await self._search_from_homepage(query)
        if self._page is not None:
            try:
                await self._page.wait_for_selector("div#search, div#rso, #result-stats", timeout=8000)
            except Exception:
                pass
        return await self._describe()

    async def visit(self, url: str) -> dict:
        await self._open(url)
        return await self._describe()

    async def extract_text(self) -> str:
        if self._page is None:
            return ""
        text = await self._page.evaluate("() => (document.body && document.body.innerText) || ''")
        if not isinstance(text, str):
            return ""
        cleaned = text.replace("\r\n", "\n").strip()
        if len(cleaned) > 20000:
            return cleaned[:20000] + "\n\n[truncated]"
        return cleaned

    async def screenshot(self, path: Path) -> None:
        if self._page is None:
            raise RuntimeError("The browser is not open.")
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path), full_page=False, type="png")

    async def _open(self, url: str) -> dict:
        if self._page is None:
            raise RuntimeError("The browser is not open.")
        await self._page.goto(url, wait_until="domcontentloaded")
        try:
            await self._page.wait_for_function(
                "() => document.body && document.body.innerText && document.body.innerText.length > 40",
                timeout=8000,
            )
        except Exception:
            pass
        return await self._describe()

    async def _describe(self) -> dict:
        if self._page is None:
            return {"url": "", "title": "", "text": "", "site_blocked": True}
        title = await self._page.title()
        final = self._page.url
        text = await self.extract_text()
        return {
            "url": final,
            "title": title,
            "text": text,
            "site_blocked": _looks_like_robot_check(final, title, text),
        }

    async def _dismiss_google_consent(self) -> None:
        """Click a consent button only on a real Google host."""

        if self._page is None or not is_google_host(_host(self._page.url)):
            return
        for _ in range(2):
            clicked = False
            for target in (self._page, *self._page.frames):
                locator = target.get_by_role("button", name=_CONSENT_BUTTON)
                try:
                    if await locator.count() == 0:
                        continue
                    await locator.first.click(timeout=2000)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                return
            try:
                await self._page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                return
            if not is_google_host(_host(self._page.url)):
                return

    async def _search_from_homepage(self, query: str) -> None:
        """If Google showed the homepage, submit the search box. Nowhere else."""

        if self._page is None or not is_google_host(_host(self._page.url)):
            return
        path = urlparse(self._page.url).path
        if path not in {"", "/"}:
            return
        box = self._page.locator("textarea[name='q'], input[name='q']")
        try:
            if await box.count() == 0:
                return
            await box.first.fill(query)
            await box.first.press("Enter")
            await self._page.wait_for_load_state("domcontentloaded")
        except Exception:
            return


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _looks_like_robot_check(url: str, title: str, text: str) -> bool:
    if "/sorry/" in url.lower():
        return True
    blob = f"{title}\n{text[:4000]}".lower()
    return any(marker in blob for marker in _ROBOT_MARKERS)
