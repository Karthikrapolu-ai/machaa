"""Turn three post ideas into a specific, editable brief.

Prices and generic filler are removed. Missing pieces are filled with
plain labels so an older reply can still become a Word document.
"""

from __future__ import annotations

import re

_PRICE = re.compile(
    r"(₹|\$|€|£|\b(?:rs\.?|inr|usd)\s*\d|\b\d[\d,]*\s*(?:rupees|dollars|lakh|lakhs)\b)",
    re.IGNORECASE,
)
_GENERIC = re.compile(
    r"\b(delve|unlock|game[- ]changer|in today's world|nestled|tapestry|elevate your)\b",
    re.IGNORECASE,
)
_FORMATS = ("reel", "carousel", "static")


def clean_copy(text: str) -> str:
    """Drop invented prices and stock phrases. Keep the rest of the sentence."""

    cleaned = _PRICE.sub("", text or "")
    cleaned = _GENERIC.sub("", cleaned)
    return " ".join(cleaned.split())


def enrich_concepts(concepts: list, tone: str = "") -> list[dict]:
    """Give each concept a hook, both captions, a format, and a direction."""

    prepared: list[dict] = []
    chosen_tone = clean_copy(tone)[:40] or "plain and specific"
    for index, item in enumerate(concepts[:3]):
        if not isinstance(item, dict):
            continue
        caption = clean_copy(str(item.get("caption") or ""))
        short = clean_copy(str(item.get("short_caption") or caption))
        long = clean_copy(str(item.get("long_caption") or caption))
        hook = clean_copy(str(item.get("hook") or "")) or _first_sentence(short or long)
        cta = clean_copy(str(item.get("cta") or "")) or "Save this for the next room you plan."
        visual = clean_copy(str(item.get("visual_direction") or item.get("image_suggestion") or ""))
        if not visual:
            visual = "Show the room itself. Do not invent a photo that was not licensed."
        raw_format = str(item.get("format") or "").strip().lower()
        post_format = raw_format if raw_format in _FORMATS else _FORMATS[index % 3]
        name = clean_copy(str(item.get("name") or f"Post {index + 1}"))[:120] or f"Post {index + 1}"
        prepared.append(
            {
                "name": name,
                "caption": short or caption,
                "short_caption": short or caption,
                "long_caption": long or short or caption,
                "hook": hook or name,
                "cta": cta,
                "format": post_format,
                "visual_direction": visual[:400],
                "hashtags": item.get("hashtags") if isinstance(item.get("hashtags"), list) else [],
                "image_suggestion": visual[:400],
                "source_urls": item.get("source_urls") if isinstance(item.get("source_urls"), list) else [],
                "tone": chosen_tone,
            }
        )
    return prepared


def _first_sentence(text: str) -> str:
    piece = text.split(".", 1)[0].strip()
    return piece[:140]
