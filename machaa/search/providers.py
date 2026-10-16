"""Find result titles and links without solving a robot check.

Google is opened in Chromium first. A robot check, an unusual-traffic
page, or a consent wall is not clicked through. The next provider is
used instead. Brave Search and Google Programmable Search run only when
their keys are set. DuckDuckGo's public HTML form is the keyless default.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

# Identifies this program. It does not pretend to be a browser.
MACHAA_USER_AGENT = "Machaa/0.1 (+https://github.com/Karthikrapolu-ai/machaa)"

_ROBOT_MARKERS = (
    "unusual traffic",
    "our systems have detected",
    "detected unusual traffic",
)
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def fallback_reason(url: str, title: str, text: str) -> str | None:
    """Return why this Google page cannot be used, or None when it can.

    This only classifies the page. It does not interact with it.
    """

    host = (urlparse(url).hostname or "").lower()
    blob = f"{title}\n{text[:5000]}".lower()
    if "/sorry/" in url.lower() or any(marker in blob for marker in _ROBOT_MARKERS):
        return "robot_check"
    if host == "consent.google.com" or host.startswith("consent.google."):
        return "consent"
    if "before you continue" in blob and (host == "google.com" or host.endswith(".google.com")):
        return "consent"
    return None


def fetch_duckduckgo_html(query: str, timeout: float = 20) -> tuple[str, list[SearchHit]]:
    """Submit DuckDuckGo's public HTML search form and read the document it returns."""

    payload = urllib.parse.urlencode({"q": query}).encode()
    request = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=payload,
        headers={
            "User-Agent": MACHAA_USER_AGENT,
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", "replace")
    return html, parse_duckduckgo_html(html)


def fetch_brave(query: str, api_key: str, timeout: float = 20) -> list[SearchHit]:
    """Call Brave's official web search API. The key stays in the request header."""

    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": "10"}
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": MACHAA_USER_AGENT,
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    hits: list[SearchHit] = []
    for item in (payload.get("web") or {}).get("results") or []:
        title = str(item.get("title") or "").strip()
        link = str(item.get("url") or "").strip()
        if title and link.startswith("http"):
            hits.append(SearchHit(title, link, str(item.get("description") or "").strip()))
    return hits[:8]


def fetch_google_programmable_search(
    query: str,
    api_key: str,
    cx: str,
    timeout: float = 20,
) -> list[SearchHit]:
    """Call Google's official Programmable Search JSON API."""

    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(
        {"key": api_key, "cx": cx, "q": query, "num": "8"}
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": MACHAA_USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    hits: list[SearchHit] = []
    for item in payload.get("items") or []:
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        if title and link.startswith("http"):
            hits.append(SearchHit(title, link, str(item.get("snippet") or "").strip()))
    return hits[:8]


def parse_duckduckgo_html(html: str) -> list[SearchHit]:
    parser = _DuckDuckGoParser()
    parser.feed(html)
    parser.close()
    return parser.hits[:8]


def unwrap_result_url(href: str) -> str:
    """Turn a DuckDuckGo redirect into the public page it points at."""

    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower()
    if host.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target.startswith("http"):
            return target
    return href


def prepare_results_document(html: str, base_url: str) -> str:
    """Keep the results markup and do not run scripts from the results page."""

    document = _SCRIPT.sub("", html)
    if "<base " in document[:3000].lower():
        return document
    base = f'<base href="{base_url}">'
    match = re.search(r"<head[^>]*>", document, re.IGNORECASE)
    if match:
        end = match.end()
        return document[:end] + base + document[end:]
    return f"<!DOCTYPE html><html><head>{base}</head><body>{document}</body></html>"


def render_api_results_page(provider: str, query: str, hits: list[SearchHit]) -> str:
    """A plain page of the titles and links an official API returned."""

    items = []
    for hit in hits:
        snippet = f"<p>{_escape(hit.snippet)}</p>" if hit.snippet else ""
        items.append(
            f"<li><a href=\"{_escape(hit.url)}\">{_escape(hit.title)}</a>{snippet}</li>"
        )
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>{_escape(query)}</title></head><body>"
        f"<h1>{_escape(provider)} results</h1>"
        f"<p>Query: {_escape(query)}</p><ol>{''.join(items)}</ol>"
        "</body></html>"
    )


def provider_label(name: str) -> str:
    return {
        "google": "Google",
        "brave": "Brave Search",
        "google_cse": "Google Programmable Search",
        "duckduckgo": "DuckDuckGo",
    }.get(name, name)


class ProviderError(Exception):
    """A provider did not return results. The next provider can be tried."""


def call_provider(name: str, query: str, *, brave_key: str, google_key: str, google_cx: str):
    """Return hits, and for DuckDuckGo the HTML document as well."""

    try:
        if name == "brave":
            return fetch_brave(query, brave_key), ""
        if name == "google_cse":
            return fetch_google_programmable_search(query, google_key, google_cx), ""
        if name == "duckduckgo":
            html, hits = fetch_duckduckgo_html(query)
            return hits, html
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise ProviderError(name) from exc
    raise ProviderError(name)


def configured_fallback_names(*, brave_key: str, google_key: str, google_cx: str) -> list[str]:
    names: list[str] = []
    if brave_key:
        names.append("brave")
    if google_key and google_cx:
        names.append("google_cse")
    names.append("duckduckgo")
    return names


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[SearchHit] = []
        self._kind = ""
        self._href = ""
        self._parts: list[str] = []
        self._pending_title = ""
        self._pending_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" and tag != "td":
            return
        attr = {key: value or "" for key, value in attrs}
        classes = attr.get("class", "").split()
        if tag == "a" and "result__a" in classes:
            self._start("title", attr.get("href", ""))
        elif "result__snippet" in classes:
            self._start("snippet", "")

    def handle_endtag(self, tag: str) -> None:
        if not self._kind:
            return
        if tag not in {"a", "td", "div"}:
            return
        text = " ".join("".join(self._parts).split())
        if self._kind == "title":
            url = unwrap_result_url(self._href)
            if text and url.startswith("http"):
                self._pending_title = text
                self._pending_url = url
        elif self._kind == "snippet" and self._pending_title:
            self.hits.append(SearchHit(self._pending_title, self._pending_url, text))
            self._pending_title = ""
            self._pending_url = ""
        self._kind = ""
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._kind:
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        if self._pending_title:
            self.hits.append(SearchHit(self._pending_title, self._pending_url))

    def _start(self, kind: str, href: str) -> None:
        self._kind = kind
        self._href = href
        self._parts = []


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
