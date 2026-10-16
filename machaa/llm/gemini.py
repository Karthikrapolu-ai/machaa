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
    "Machaa needs a free Gemini key to write this Word document or social post. "
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


class QuotaError(MachaaError):
    """Gemini refused the call because the free quota was used up."""


class TokenLimitError(MachaaError):
    """This task has used the token budget Machaa allows."""


class GeminiClient:
    """Call the public Gemini JSON API. The key stays in a request header."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float = 30,
        max_tokens: int = 8000,
        max_retries: int = 1,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip() or DEFAULT_MODEL
        self.timeout = timeout
        self.max_tokens = max(1, max_tokens)
        self.max_retries = max(0, max_retries)
        self.tokens_used = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def reset_budget(self) -> None:
        """Start a new task with a fresh token count. The limit is per task."""

        self.tokens_used = 0

    def draft(self, instruction: str, sources: str) -> dict:
        """Return a title and sections. Raises MissingKeyError before any network call."""

        text, model = self._complete(_prompt(instruction, sources))
        draft = parse_draft(text)
        draft["model"] = model
        return draft

    def plan_actions(self, instruction: str, feedback: str = "", max_steps: int = 8) -> list:
        """Ask for a short action list. The caller still has to validate it."""

        text, _model = self._complete(_plan_prompt(instruction, feedback, max_steps))
        return parse_plan(text)

    def plan_desktop(self, instruction: str, feedback: str = "", max_steps: int = 8) -> list:
        """Ask for a desktop plan. The caller still has to validate it."""

        text, _model = self._complete(_desktop_prompt(instruction, feedback, max_steps))
        return parse_plan(text)

    def write_social(
        self,
        brand: str,
        topic: str,
        platform: str,
        audience: str,
        sources: str,
        image_note: str,
    ) -> dict:
        """Return three post concepts. The reply is document text, not a command."""

        text, model = self._complete(
            _social_prompt(brand, topic, platform, audience, sources, image_note)
        )
        social = parse_social(text)
        social["model"] = model
        return social

    def _complete(self, prompt: str) -> tuple[str, str]:
        if not self.api_key:
            raise MissingKeyError(KEY_HELP)
        if not _MODEL.fullmatch(self.model):
            raise DraftError("Machaa could not use the configured Gemini model name.")
        not_found: list[str] = []
        tried: set[str] = set()
        queue = [self.model]
        while queue:
            model = queue.pop(0)
            if model in tried or not _MODEL.fullmatch(model):
                continue
            tried.add(model)
            try:
                body = self._request(model, prompt)
            except _ModelNotFound as missing:
                not_found.append(f"{model}: {missing.detail}")
                for name in FALLBACK_MODELS:
                    if name not in tried and name not in queue:
                        queue.append(name)
                continue
            return _answer_text(body), model
        details = " ".join(not_found) or "The model was not found."
        raise DraftError(f"Gemini did not return a document (HTTP 404). {details}")

    def _request(self, model: str, prompt: str) -> dict:
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
        body_bytes = json.dumps(payload).encode("utf-8")
        quota_detail = ""
        for attempt in range(self.max_retries + 1):
            self._ensure_budget()
            request = urllib.request.Request(
                url,
                data=body_bytes,
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
                if exc.code in {429, 503}:
                    quota_detail = detail or f"HTTP {exc.code}"
                    if attempt < self.max_retries:
                        continue
                    message = f"Gemini is out of quota (HTTP {exc.code})."
                    if quota_detail:
                        message = f"{message} {quota_detail}"
                    raise QuotaError(message) from exc
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
            answer = _answer_text(body)
            self._charge(body, prompt, answer)
            return body
        raise QuotaError(f"Gemini is out of quota. {quota_detail}".strip())

    def _ensure_budget(self) -> None:
        if self.tokens_used >= self.max_tokens:
            raise TokenLimitError(
                "This task reached its token limit. Machaa stopped before another Gemini call."
            )

    def _charge(self, body: dict, prompt: str, answer: str) -> None:
        usage = body.get("usageMetadata") if isinstance(body, dict) else None
        count = usage.get("totalTokenCount") if isinstance(usage, dict) else None
        if not isinstance(count, int):
            count = max(1, (len(prompt) + len(answer)) // 4)
        self.tokens_used += max(0, count)


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


def parse_plan(text: str) -> list:
    """Return the action list. Approval happens later, in the Guardian."""

    cleaned = _FENCE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise DraftError("The planner did not return a list of actions.") from exc
    if isinstance(data, dict):
        data = data.get("actions")
    if not isinstance(data, list):
        raise DraftError("The planner did not return a list of actions.")
    return data


def parse_social(text: str) -> dict:
    """Keep three post concepts and drop anything that is not one of those fields."""

    cleaned = _FENCE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise DraftError("Gemini did not return three post concepts.") from exc
    if not isinstance(data, dict):
        raise DraftError("Gemini did not return three post concepts.")
    title = " ".join(str(data.get("title") or "").split())
    if not title or len(title) > 200:
        raise DraftError("Gemini did not return a title for the social post.")
    incoming = data.get("concepts")
    if not isinstance(incoming, list) or len(incoming) < 3:
        raise DraftError("Gemini did not return three post concepts.")
    concepts: list[dict] = []
    for index, item in enumerate(incoming[:3], start=1):
        if not isinstance(item, dict):
            raise DraftError("Gemini did not return three post concepts.")
        caption = " ".join(str(item.get("caption") or "").split())
        suggestion = " ".join(str(item.get("image_suggestion") or "").split())
        if not caption or not suggestion:
            raise DraftError("Gemini did not return three post concepts.")
        name = " ".join(str(item.get("name") or f"Post {index}").split())[:120]
        hashtags = _hashtags(item.get("hashtags"))
        if not hashtags:
            raise DraftError("Gemini did not return hashtags.")
        urls = _http_urls(item.get("source_urls"))
        concepts.append(
            {
                "name": name,
                "caption": caption[:800],
                "hashtags": hashtags,
                "image_suggestion": suggestion[:400],
                "source_urls": urls,
            }
        )
    if len(concepts) != 3:
        raise DraftError("Gemini did not return three post concepts.")
    return {"title": title, "concepts": concepts}


def _hashtags(value: object) -> list[str]:
    raw: list[str] = []
    if isinstance(value, str):
        raw = value.split()
    elif isinstance(value, list):
        raw = [str(item) for item in value]
    tags: list[str] = []
    for item in raw:
        tag = "".join(str(item).split())
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag
        if len(tag) > 60:
            continue
        tags.append(tag)
        if len(tags) == 8:
            break
    return tags


def _http_urls(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    for item in value:
        url = str(item).strip().rstrip(".,);")
        if url.startswith("https://") or url.startswith("http://"):
            urls.append(url[:500])
        if len(urls) == 4:
            break
    return urls


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


def _plan_prompt(instruction: str, feedback: str, max_steps: int) -> str:
    repair = ""
    if feedback.strip():
        repair = (
            "The previous plan was rejected: "
            f"{feedback.strip()[:500]}. Return a different plan that passes.\n"
        )
    return (
        "Turn the request into a JSON list of actions Machaa can run. "
        f"Use at most {max_steps} actions. "
        "Allowed tools and their exact argument names are:\n"
        '- browser.search_google with {"query": "..."}\n'
        '- image.find_licensed with {"query": "..."}\n'
        '- content.write_social with {"brand","topic","platform","audience"}\n'
        '- browser.screenshot with {}\n'
        '- browser.extract_text with {}\n'
        "Do not use a shell, a download command, or any other tool. "
        "Do not add argument names that are not listed. "
        "For a social post, use search, then a licensed image, then content.write_social. "
        'Return JSON only: {"actions":[{"tool":"...","arguments":{},"label":"..."}]}.\n'
        f"{repair}"
        f"Request: {instruction.strip()[:2000]}\n"
    )


def _desktop_prompt(instruction: str, feedback: str, max_steps: int) -> str:
    repair = ""
    if feedback.strip():
        repair = (
            "The previous plan was rejected: "
            f"{feedback.strip()[:500]}. Return a different plan that passes.\n"
        )
    return (
        "Turn the request into a JSON list of desktop actions. "
        f"Use at most {max_steps} actions. "
        "Allowed tools and their exact argument names are:\n"
        '- desktop.open_notepad with {}\n'
        '- desktop.open_calculator with {}\n'
        '- desktop.open_explorer with {}\n'
        '- desktop.focus_dashboard with {}\n'
        '- desktop.type_notepad with {"text": "..."}\n'
        '- desktop.save_text with {"filename": "name.txt", "text": "..."}\n'
        '- desktop.read_file with {"filename": "name.txt"}\n'
        '- desktop.open_website with {"url": "https://..."}\n'
        "filename must be a simple .txt or .md name with no folders. "
        "Do not use a shell, PowerShell, cmd, or any other tool. "
        'Return JSON only: {"actions":[{"tool":"...","arguments":{},"label":"..."}]}.\n'
        f"{repair}"
        f"Request: {instruction.strip()[:2000]}\n"
    )


def _social_prompt(
    brand: str,
    topic: str,
    platform: str,
    audience: str,
    sources: str,
    image_note: str,
) -> str:
    notes = sources.strip()[:6000] or "(No source notes were collected.)"
    picture = image_note.strip()[:1000] or "No reusable image was found."
    return (
        "Write three social posts. Use only the source notes and the image note. "
        "Do not invent a photograph, a price, a phone number, or a person. "
        "Image suggestions are words about what a photo could show. "
        "They are not a claim that a photo exists. "
        "Put source URLs only if they appear in the notes. "
        "Return JSON only with this shape: "
        '{"title":"...","concepts":[{"name":"...","caption":"...","hashtags":["#tag"],'
        '"image_suggestion":"...","source_urls":["https://..."]}]}. '
        "The concepts array must contain exactly three items.\n\n"
        f"Brand: {brand.strip()[:200]}\n"
        f"Platform: {platform.strip()[:40]}\n"
        f"Audience: {audience.strip()[:200]}\n"
        f"Topic: {topic.strip()[:300]}\n"
        f"Image note: {picture}\n\n"
        f"Source notes:\n{notes}\n"
    )
