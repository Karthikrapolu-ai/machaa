"""Turn one sentence into a search, a page visit, a Word brief, a social post, or a desktop action.

Search and Word-document requests stay on fixed steps. A social post is the
request the planner is allowed to turn into a short list of actions.
Desktop sentences are recognised before a social post, so a caption that
should be typed into Notepad is not turned into a Word document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DOCUMENT = re.compile(
    r"\b(?:write|create|make|draft|prepare)\b.{0,60}\b(?:word document|word doc|\.docx|docx)\b",
    re.IGNORECASE,
)
_TOPIC = re.compile(r"\b(?:about|on|for)\s+(.+)$", re.IGNORECASE)
_SEARCH_FOR = re.compile(r"\bsearch(?:\s+google)?\s+for\s+(.+)$", re.IGNORECASE)
_GOOGLE_SEARCH = re.compile(r"\bgoogle\s+search\s+(?:for\s+)?(.+)$", re.IGNORECASE)
_SEARCH_GOOGLE = re.compile(r"\bsearch\s+google\s+(?:for\s+)?(.+)$", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"']*)?)", re.IGNORECASE)
_VISIT_VERB = re.compile(r"\b(visit|open|go\s+to|browse)\b", re.IGNORECASE)
_PLATFORM = re.compile(
    r"\b(instagram|facebook|linkedin|tiktok|pinterest|twitter)\b",
    re.IGNORECASE,
)
_SOCIAL_ASK = re.compile(
    r"\b(content document|captions?|hashtags?|post concepts?|social posts?|social media)\b",
    re.IGNORECASE,
)
_FOR_ABOUT = re.compile(
    r"\bfor\s+(.+?)\s+about\s+(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_AUDIENCE = re.compile(
    r"\b(?:audience|aimed at|for an audience of)\s+(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_DESKTOP = re.compile(
    r"\b(notepad|calculator|file explorer|machaa documents|open machaa)\b",
    re.IGNORECASE,
)
_PLATFORM_NAMES = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "tiktok": "TikTok",
    "pinterest": "Pinterest",
    "twitter": "Twitter",
}
DEFAULT_AUDIENCE = "people who might hire this brand"


@dataclass(frozen=True)
class ResearchPlan:
    kind: str
    query: str | None = None
    url: str | None = None
    brand: str | None = None
    platform: str | None = None
    audience: str | None = None


def parse_research_request(instruction: str) -> ResearchPlan | None:
    """Return a search, a page visit, a Word brief, a social post, or nothing."""

    text = " ".join(instruction.strip().split())
    if not text:
        return None
    query = _search_query(text)
    if query:
        return ResearchPlan(kind="search", query=query)
    document_query = _document_query(text)
    if document_query:
        return ResearchPlan(kind="document", query=document_query)
    if _DESKTOP.search(text):
        return ResearchPlan(kind="desktop", query=text[:300])
    social = _social_plan(text)
    if social is not None:
        return social
    url = _explicit_url(text)
    if url and (_VISIT_VERB.search(text) or text.lower().startswith("http")):
        return ResearchPlan(kind="visit", url=url)
    return None


def _social_plan(text: str) -> ResearchPlan | None:
    """A social post names a platform and asks for captions or a content document."""

    if _SOCIAL_ASK.search(text) is None:
        return None
    platform_match = _PLATFORM.search(text)
    if platform_match is None and re.search(r"\bsocial media\b", text, re.IGNORECASE) is None:
        return None
    platform = (
        _PLATFORM_NAMES.get(platform_match.group(1).lower(), "Instagram")
        if platform_match
        else "Instagram"
    )
    brand = "the brand"
    topic = ""
    match = _FOR_ABOUT.search(text)
    if match:
        brand = match.group(1).strip().strip("\"'")
        topic = match.group(2).strip().strip("\"'").rstrip(".")
    else:
        topic_match = _TOPIC.search(text)
        if topic_match:
            topic = topic_match.group(1).strip().strip("\"'").rstrip(".")
    if not topic:
        topic = text[:300]
    audience_match = _AUDIENCE.search(text)
    audience = (
        audience_match.group(1).strip().strip("\"'").rstrip(".")
        if audience_match
        else DEFAULT_AUDIENCE
    )
    if not brand or not topic:
        return None
    return ResearchPlan(
        kind="social",
        query=topic[:300],
        brand=brand[:200],
        platform=platform[:40],
        audience=audience[:200],
    )


def _document_query(text: str) -> str | None:
    if _DOCUMENT.search(text) is None:
        return None
    match = _TOPIC.search(text)
    query = match.group(1).strip().strip("\"'").rstrip(".") if match else text
    if not query:
        return None
    return query[:300]


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
