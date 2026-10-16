"""Turn one sentence into a search or a single public page. No model is called."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEARCH_FOR = re.compile(r"\bsearch(?:\s+google)?\s+for\s+(.+)$", re.IGNORECASE)
_GOOGLE_SEARCH = re.compile(r"\bgoogle\s+search\s+(?:for\s+)?(.+)$", re.IGNORECASE)
_SEARCH_GOOGLE = re.compile(r"\bsearch\s+google\s+(?:for\s+)?(.+)$", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"']*)?)", re.IGNORECASE)
_VISIT_VERB = re.compile(r"\b(visit|open|go\s+to|browse)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ResearchPlan:
    kind: str
    query: str | None = None
    url: str | None = None


def parse_research_request(instruction: str) -> ResearchPlan | None:
    """Return a search, a page visit, or nothing when Day 1 cannot do it."""

    text = " ".join(instruction.strip().split())
    if not text:
        return None
    query = _search_query(text)
    if query:
        return ResearchPlan(kind="search", query=query)
    url = _explicit_url(text)
    if url and (_VISIT_VERB.search(text) or text.lower().startswith("http")):
        return ResearchPlan(kind="visit", url=url)
    return None


def _search_query(text: str) -> str | None:
    for pattern in (_SEARCH_FOR, _GOOGLE_SEARCH, _SEARCH_GOOGLE):
        match = pattern.search(text)
        if not match:
            continue
        query = match.group(1).strip().strip("\"'").rstrip(".")
        if query:
            return query[:300]
    return None


def _explicit_url(text: str) -> str | None:
    match = _URL.search(text)
    if match:
        return match.group(0).rstrip(".,);")
    if not _VISIT_VERB.search(text):
        return None
    bare = _BARE_DOMAIN.search(text)
    if bare is None:
        return None
    host = bare.group(1).split("/", 1)[0].lower()
    if host in {"google.com", "www.google.com"}:
        return None
    return "https://" + bare.group(1).rstrip(".,);")
