"""Founder fixes: speech in the box, and the Companion window."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from fastapi.testclient import TestClient

from machaa.companion.client import COMPANION_HELP
from machaa.companion.server import CompanionServer, peer_allowed
from machaa.core.errors import VoiceUnavailable
from machaa.launcher import wait_for_companion
from machaa.main import create_app
from machaa.voice.transcribe import transcribe_audio
from tests.fakes import ExplodingBrowser


def test_speech_uses_the_browser_and_send_submits():
    page = Path("machaa/web/index.html").read_text(encoding="utf-8")
    script = Path("machaa/web/app.js").read_text(encoding="utf-8")
    assert 'data-testid="recording-send"' in page
    assert 'data-testid="recording-stop"' in page
    assert 'data-testid="recording-cancel"' in page
    assert 'data-testid="start-companion"' in page
    assert "webkitSpeechRecognition" in script
    assert "en-IN" in script
    assert "en-US" in script
    assert "interimResults" in script
    assert "getUserMedia" in script
    start = script.index("async function uploadRecording")
    end = script.index("desktopSwitch.addEventListener")
    assert "requestSubmit" not in script[start:end]
    assert "input.value" in script[start:end]
    assert "form.requestSubmit" in script
    assert "hideRecording" in script


def test_gemini_transcribes_when_the_browser_has_no_words(monkeypatch):
    monkeypatch.setattr("machaa.voice.transcribe.voice_ready", lambda: False)

    def fake(self, audio, mime):
        assert audio == b"spoken"
        assert mime == "audio/webm"
        assert self.api_key == "test-key"
        return "open notepad"

    monkeypatch.setattr("machaa.llm.gemini.GeminiClient.transcribe_speech", fake)
    assert transcribe_audio(b"spoken", api_key="test-key", mime="audio/webm") == "open notepad"


def test_a_missing_transcript_is_a_visible_error(monkeypatch):
    monkeypatch.setattr("machaa.voice.transcribe.voice_ready", lambda: False)
    try:
        transcribe_audio(b"spoken", api_key="")
    except VoiceUnavailable as exc:
        message = str(exc)
    else:
        raise AssertionError("expected an error")
    assert "type" in message.lower()
    assert "faster-whisper" not in message
    assert message.strip()


def test_companion_message_no_longer_names_the_old_file():
    assert "start-machaa-windows.bat" not in COMPANION_HELP
    assert "START-MACHAA.bat" in COMPANION_HELP
    assert "not running" in COMPANION_HELP
    bat = Path("START-MACHAA.bat").read_text(encoding="utf-8")
    assert 'start "Machaa Companion"' in bat
    assert "winget install -e --id Python.Python.3.12" in bat
    assert "/health" in bat
    assert "Startup" in bat
    assert "machaa.launcher start" in bat
    assert "docker compose up --build" not in bat
    assert "companion-login.bat" in Path("START-MACHAA.bat").read_text(encoding="utf-8")


def test_start_companion_button_cannot_launch_from_docker(settings):
    client = TestClient(create_app(settings, ExplodingBrowser))
    response = client.post("/api/companion/start")
    assert response.status_code == 200
    body = response.json()
    assert body["started"] is False
    assert "Docker" in body["detail"]
    assert "START-MACHAA.bat" in body["detail"]
    assert "start-machaa-windows.bat" not in body["detail"]


def test_companion_health_answers_without_a_token(tmp_path: Path):
    documents = tmp_path / "Machaa"
    server = CompanionServer("local-token", documents, 0)
    server.start_background()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/health", timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        assert body["ok"] is True
    finally:
        server.shutdown()
    assert peer_allowed("127.0.0.1") is True
    assert peer_allowed("192.168.65.3") is True
    assert peer_allowed("8.8.8.8") is False
    assert peer_allowed("192.168.1.20") is True


def test_wait_for_companion_retries_then_sees_health():
    calls = {"n": 0}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def opener(url, timeout=1):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("down")
        assert url.endswith("/health")
        return Response()

    assert wait_for_companion(attempts=3, pause=lambda: None, opener=opener) is True
    assert calls["n"] == 2
