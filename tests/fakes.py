"""A browser double. Security tests use this to prove the real browser never starts."""

from __future__ import annotations

from pathlib import Path

from machaa.browser.urls import google_search_url


class FakeBrowser:
    launched = 0

    def __init__(self, settings) -> None:
        FakeBrowser.launched += 1
        self.settings = settings
        self.closed = False

    async def __aenter__(self) -> FakeBrowser:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.closed = True

    async def search_google(self, query: str) -> dict:
        return {
            "url": google_search_url(query),
            "title": "Google Search",
            "text": f"results for {query}",
            "site_blocked": False,
            "blocked_page": None,
            "hits": [
                {
                    "title": "Example result",
                    "url": "https://example.com/ideas",
                    "snippet": f"ideas for {query}",
                }
            ],
        }

    async def show_document(self, html: str) -> None:
        return None

    async def page_title(self) -> str:
        return "Google Search"

    async def visit(self, url: str) -> dict:
        return {
            "url": url,
            "title": "Example Domain",
            "text": "Example Domain",
            "site_blocked": False,
        }

    async def extract_text(self) -> str:
        return "Example Domain"

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    async def blank(self) -> None:
        return None


class ExplodingBrowser:
    """Fails the test if a blocked request reaches the browser."""

    def __init__(self, settings) -> None:
        raise AssertionError("browser should not start")
