"""Push-to-talk transcription. Audio is not saved and is not uploaded.

The optional recognizer is faster-whisper, installed on the Windows PC
by the owner. It is not part of the Docker image. Typed chat works
without it.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from machaa.core.errors import VoiceUnavailable

MAX_AUDIO_BYTES = 5 * 1024 * 1024

_OPEN = re.compile(r"^(?:machaa[,:]?\s+)?open machaa[.!]?$", re.IGNORECASE)


def voice_ready() -> bool:
    """True only when the optional local recognizer can be imported."""

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def is_open_machaa(text: str) -> bool:
    return _OPEN.fullmatch(" ".join((text or "").strip().split())) is not None


def transcribe_audio(data: bytes) -> str:
    """Turn one short recording into text. The bytes are not written to data/."""

    if not data:
        raise VoiceUnavailable("That recording was empty. You can still type.")
    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceUnavailable("That recording was too long. You can still type.")
    if not voice_ready():
        raise VoiceUnavailable(
            "Voice typing needs an optional free program on this computer. "
            "Typed chat still works. On Windows, later, you can run: "
            "py -3 -m pip install faster-whisper"
        )
    from faster_whisper import WhisperModel

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as handle:
        handle.write(data)
        handle.flush()
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(handle.name, language="en")
        text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise VoiceUnavailable("Machaa could not hear any words. You can still type.")
    return text[:2000]


def recordings_in(folder: Path) -> list[Path]:
    """Helper for tests. Machaa should not leave recordings behind."""

    if not folder.exists():
        return []
    found = []
    for path in folder.rglob("*"):
        if path.suffix.lower() in {".wav", ".webm", ".mp3", ".m4a", ".ogg"}:
            found.append(path)
    return found
