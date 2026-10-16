"""URLs Machaa is allowed to build itself. Searches always go to Google."""

from __future__ import annotations

from urllib.parse import urlencode

MAX_QUERY_LEN = 300


def google_search_url(query: str) -> str:
    """Return the only address a Google search may open."""

    cleaned = query.strip()
    if not cleaned or len(cleaned) > MAX_QUERY_LEN:
        raise ValueError("invalid query")
    if any(ord(char) < 32 for char in cleaned):
        raise ValueError("invalid query")
    return "https://www.google.com/search?" + urlencode(
        {
            "q": cleaned,
            "hl": "en",
            "pws": "0",
            "num": "10",
        }
    )


def is_google_host(host: str) -> bool:
    """True for Google search and the Google cookie-consent host only."""

    host = host.lower().rstrip(".")
    if host == "google.com" or host.endswith(".google.com"):
        return True
    parts = host.split(".")
    if len(parts) == 2 and parts[0] == "google" and len(parts[1]) == 2:
        return True
    if len(parts) == 3 and parts[0] == "www" and parts[1] == "google" and len(parts[2]) == 2:
        return True
    if len(parts) == 3 and parts[0] == "google" and parts[1] == "co" and len(parts[2]) == 2:
        return True
    if (
        len(parts) == 4
        and parts[0] == "www"
        and parts[1] == "google"
        and parts[2] == "co"
        and len(parts[3]) == 2
    ):
        return True
    return False
