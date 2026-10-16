"""Ask Gemini for a Word-document draft. The reply is text, not a command."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from machaa.core.errors import MachaaError

# Google's current recommendation for a new free-tier project.
# gemini-2.5-flash still exists, but a new key is often told it is not found.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
)
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
        prompt = _prompt(instruction, sources)
        not_found: list[str] = []
        tried: set[str] = set()
        queue = [self.model]
        while queue:
            model = queue.pop(0)
            if model in tried or not _MODEL.fullmatch(model):
                continue
            tried.add(model)
            try:
                draft = self._generate(model, prompt)
            except _ModelNotFound as missing:
                not_found.append(f"{model}: {missing.detail}")
                for name in FALLBACK_MODELS:
                    if name not in tried and name not in queue:
                        queue.append(name)
                continue
            draft["model"] = model
            return draft
        details = " ".join(not_found) or "The model was not found."
        raise DraftError(f"Gemini did not return a document (HTTP 404). {details}")

    def _generate(self, model: str, prompt: str) -> dict:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
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
            detail = _http_detail(exc, self.api_key)
            if exc.code == 404:
                raise _ModelNotFound(detail) from exc
            message = f"Gemini did not return a document (HTTP {exc.code})."
            if detail:
                message = f"{message} {detail}"
            raise DraftError(message) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DraftError("Machaa could not reach Gemini.") from exc
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DraftError("Gemini did not return a document.") from exc
        return parse_draft(_answer_text(body))


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


class _ModelNotFound(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _http_detail(exc: urllib.error.HTTPError, api_key: str) -> str:
    """The message Gemini sent, with the key removed if it was echoed."""

    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:
        return ""
    message = ""
    try:
        payload = json.loads(raw)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "")
    except json.JSONDecodeError:
        message = raw
    message = " ".join(message.split())
    if api_key:
        message = message.replace(api_key, "[key]")
    return message[:500]


def _answer_text(body: dict) -> str:
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        reason = ""
        if isinstance(body, dict):
            feedback = body.get("promptFeedback")
            if isinstance(feedback, dict):
                reason = str(feedback.get("blockReason") or "")
        extra = f" {reason}" if reason else ""
        raise DraftError(f"Gemini did not return a document.{extra}") from exc
    texts = [
        str(part.get("text"))
        for part in parts
        if isinstance(part, dict) and part.get("text")
    ]
    if not texts:
        raise DraftError("Gemini did not return a document.")
    return texts[-1]


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
