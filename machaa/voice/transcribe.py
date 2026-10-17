"""Turn speech into text for the message box.

Chrome and Edge type the words in the browser. When that is not available,
this module can read one short recording. A local faster-whisper install is
used when it is already present. Otherwise the recording is sent to Gemini
with the key already in .env. The file is not saved.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from machaa.core.errors import VoiceUnavailable
from machaa.llm.gemini import GeminiClient, MissingKeyError

MAX_AUDIO_BYTES = 5 * 1024 * 1024

_OPEN = re.compile(r"^(?:machaa[,:]?\s+)?open machaa[.!]?$", re.IGNORECASE)
_HEARD_NOTHING = "Machaa could not hear any words. You can still type."
_COULD_NOT = "Machaa could not turn that speech into text. You can still type."


def voice_ready() -> bool:
    """True only when the optional local recognizer can be imported."""

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def is_open_machaa(text: str) -> bool:
    return _OPEN.fullmatch(" ".join((text or "").strip().split())) is not None


def transcribe_audio(data: bytes, api_key: str = "", mime: str = "audio/webm") -> str:
    """Turn one short recording into text. The bytes are not written to data/."""

    if not data:
        raise VoiceUnavailable("That recording was empty. You can still type.")
    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceUnavailable("That recording was too long. You can still type.")
    if voice_ready():
        heard = _whisper(data)
        if heard:
            return heard[:2000]
    key = (api_key or "").strip()
    if not key:
        raise VoiceUnavailable(_COULD_NOT)
    try:
        heard = _gemini_transcript(data, mime or "audio/webm", key)
    except VoiceUnavailable:
        raise
    except Exception as exc:
        raise VoiceUnavailable(_COULD_NOT) from exc
    if not heard.strip():
        raise VoiceUnavailable(_HEARD_NOTHING)
    return heard.strip()[:2000]


def _gemini_transcript(data: bytes, mime: str, api_key: str) -> str:
    client = GeminiClient(api_key)
    try:
        return client.transcribe_speech(data, mime)
    except MissingKeyError as exc:
        raise VoiceUnavailable(_COULD_NOT) from exc


def _whisper(data: bytes) -> str:
    from faster_whisper import WhisperModel

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as handle:
        handle.write(data)
        handle.flush()
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(handle.name, language="en")
        return " ".join(segment.text.strip() for segment in segments).strip()


def recordings_in(folder: Path) -> list[Path]:
    """Helper for tests. Machaa should not leave recordings behind."""

    if not folder.exists():
        return []
    found = []
    for path in folder.rglob("*"):
        if path.suffix.lower() in {".wav", ".webm", ".mp3", ".m4a", ".ogg"}:
            found.append(path)
    return found
