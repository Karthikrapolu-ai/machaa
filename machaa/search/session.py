"""Try Google, then the configured APIs, then DuckDuckGo's HTML form."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode

from machaa.config import Settings
from machaa.core.errors import StepLimitReached, TaskStopped, ToolDenied
from machaa.core.guardian import Guardian
from machaa.search.providers import (
    ProviderError,
    SearchHit,
    call_provider,
    configured_fallback_names,
    fallback_reason,
    prepare_results_document,
    provider_label,
    render_api_results_page,
)

log = logging.getLogger("machaa.search")


async def perform_search(workspace, settings: Settings, guardian: Guardian, query: str) -> dict:
    """Leave the browser showing a real results document, or say a person is needed."""

    opened = await _try_google(workspace, query)
    reason = opened.get("blocked_page")
    hits = [] if reason else _hits_from(opened.get("hits"))
    if hits:
        final = str(opened.get("url") or "")
        _refuse_if_needed(guardian, final)
        opened["provider"] = "google"
        opened["needs_human"] = False
        opened["note"] = ""
        opened["hits"] = [hit.to_dict() for hit in hits]
        return opened

    for name in configured_fallback_names(
        brave_key=settings.brave_search_api_key,
        google_key=settings.google_search_api_key,
        google_cx=settings.google_search_cx,
    ):
        try:
            found, html = await asyncio.to_thread(
                call_provider,
                name,
                query,
                brave_key=settings.brave_search_api_key,
                google_key=settings.google_search_api_key,
                google_cx=settings.google_search_cx,
            )
        except ProviderError:
            log.info("search provider %s did not return results", name)
            continue
        if not found:
            continue
        page_url = _provider_page_url(name, query)
        decision = guardian.review_navigation(page_url, resolve=False)
        if not decision.allowed:
            continue
        if name == "duckduckgo":
            document = prepare_results_document(html, "https://duckduckgo.com/")
        else:
            document = render_api_results_page(provider_label(name), query, found)
        await workspace.show_document(document)
        text = await workspace.extract_text()
        note = _fallback_note(reason or "no_results", name)
        log.info("search fallback provider=%s reason=%s", name, reason or "no_results")
        return {
            "url": page_url,
            "title": await workspace.page_title(),
            "text": text,
            "hits": [hit.to_dict() for hit in found],
            "provider": name,
            "needs_human": False,
            "note": note,
            "blocked_page": None,
        }

    log.info("search needs a person reason=%s", reason or "no_results")
    return {
        "url": str(opened.get("url") or ""),
        "title": str(opened.get("title") or ""),
        "text": str(opened.get("text") or ""),
        "hits": [],
        "provider": "",
        "needs_human": True,
        "note": _human_note(reason or "no_results"),
        "blocked_page": reason,
    }


async def _try_google(workspace, query: str) -> dict:
    try:
        return await workspace.search_google(query)
    except (ToolDenied, TaskStopped, StepLimitReached):
        raise
    except Exception:
        log.info("google search could not be opened")
        return {
            "url": "",
            "title": "",
            "text": "",
            "hits": [],
            "blocked_page": "unavailable",
        }


def _refuse_if_needed(guardian: Guardian, url: str) -> None:
    if not url:
        return
    decision = guardian.review_navigation(url, resolve=False)
    if not decision.allowed:
        raise ToolDenied(decision.reason, decision.category)


def _hits_from(raw) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for item in raw or []:
        if isinstance(item, SearchHit):
            hits.append(item)
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if title and url.startswith("http"):
            hits.append(SearchHit(title, url, str(item.get("snippet") or "").strip()))
    return hits


def _provider_page_url(name: str, query: str) -> str:
    if name == "duckduckgo":
        return "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    if name == "brave":
        return "https://api.search.brave.com/res/v1/web/search?" + urlencode({"q": query})
    return "https://www.googleapis.com/customsearch/v1?" + urlencode({"q": query})


def _fallback_note(reason: str, provider: str) -> str:
    label = provider_label(provider)
    if reason == "robot_check":
        return (
            f"Google showed a robot check. Machaa did not try to solve it "
            f"and used {label} instead."
        )
    if reason == "consent":
        return (
            f"Google showed a consent page. Machaa did not click through it "
            f"and used {label} instead."
        )
    if reason == "unavailable":
        return f"Google could not be opened. Machaa used {label} instead."
    return f"Google did not show results. Machaa used {label} instead."


def _human_note(reason: str) -> str:
    if reason == "robot_check":
        return (
            "Machaa needs a person to finish this search. Google showed a robot check, "
            "which Machaa will not solve, and no other provider returned results."
        )
    if reason == "consent":
        return (
            "Machaa needs a person to finish this search. Google showed a consent page, "
            "which Machaa will not click through, and no other provider returned results."
        )
    return (
        "Machaa needs a person to finish this search. "
        "No search provider returned results."
    )
