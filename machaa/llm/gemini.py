"""Ask Gemini for a Word-document draft. The reply is text, not a command."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from machaa.core.errors import MachaaError

DEFAULT_MODEL = "gemini-2.5-flash"
KEY_HELP = (
    "Machaa needs a free Gemini key to write this Word document. "
    "In the Machaa folder, open the file named .env (create it if it is missing) "
    "and add a line GEMINI_API_KEY= followed by the key. "
    "Get a free key at https://aistudio.google.com/apikey . "
    "Save the file, then start Machaa again. "
    "On Windows, click the start.bat window, press Ctrl+C, and double-click start.bat."
)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class MissingKeyError(MachaaError):
    """No Gemini key is configured. Nothing was sent to Google."""


class DraftError(MachaaError):
    """Gemini did not return a usable document."""


class GeminiClient:
    """Call the public Gemini JSON API. The key stays in a request header."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 30) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip() or DEFAULT_MODEL
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def draft(self, instruction: str, sources: str) -> dict:
        """Return a title and sections. Raises MissingKeyError before any network call."""

        if not self.api_key:
            raise MissingKeyError(KEY_HELP)
        if not _MODEL.fullmatch(self.model):
            raise DraftError("Machaa could not use the configured Gemini model name.")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _prompt(instruction, sources)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise DraftError(
                f"Gemini did not return a document (HTTP {exc.code})."
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DraftError("Machaa could not reach Gemini.") from exc
        try:
            body = json.loads(raw)
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DraftError("Gemini did not return a document.") from exc
        return parse_draft(text)


def parse_draft(text: str) -> dict:
    """Accept the JSON document shape and drop anything that is not a section."""

    cleaned = _FENCE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise DraftError("Gemini did not return a document.") from exc
    if not isinstance(data, dict):
        raise DraftError("Gemini did not return a document.")
    title = " ".join(str(data.get("title") or "").split())
    if not title or len(title) > 200:
        raise DraftError("Gemini did not return a document title.")
    sections_in = data.get("sections")
    if not isinstance(sections_in, list) or not sections_in:
        raise DraftError("Gemini did not return any sections.")
    sections: list[dict] = []
    for item in sections_in[:8]:
        if not isinstance(item, dict):
            continue
        heading = " ".join(str(item.get("heading") or "").split())
        paragraphs_in = item.get("paragraphs")
        if not heading or not isinstance(paragraphs_in, list):
            continue
        paragraphs = [
            " ".join(str(paragraph).split())
            for paragraph in paragraphs_in[:6]
            if " ".join(str(paragraph).split())
        ]
        paragraphs = [paragraph[:1200] for paragraph in paragraphs]
        if paragraphs and len(heading) <= 160:
            sections.append({"heading": heading[:160], "paragraphs": paragraphs})
    if not sections:
        raise DraftError("Gemini did not return any sections.")
    return {"title": title, "sections": sections}


def _prompt(instruction: str, sources: str) -> str:
    notes = sources.strip()[:8000] or "(No source notes were collected.)"
    return (
        "Write a short document for someone at home. "
        "Use only the source notes. If the notes do not support a point, say so. "
        "Do not invent prices, phone numbers, or instructions to buy or pay. "
        "Return JSON only, with this shape: "
        '{"title":"...","sections":[{"heading":"...","paragraphs":["..."]}]}. '
        "Use three to five sections.\n\n"
        f"Request: {instruction.strip()[:2000]}\n\n"
        f"Source notes:\n{notes}\n"
    )
