"""Word documents: a missing Gemini key stops early, and a stand-in reply writes a file."""

import json
import shutil
from pathlib import Path

from machaa.config import Settings
from machaa.core.service import TaskService
from machaa.llm.gemini import GeminiClient, MissingKeyError, parse_draft
from machaa.main import create_app
from machaa.reports.docx_writer import write_brief
from tests.fakes import ExplodingBrowser, FakeBrowser

WORD = "Write a Word document about simple 2BHK interior design ideas"
PAYMENT = "Buy a sofa and pay with my credit card at checkout"
DRAFT = {
    "title": "Simple 2BHK interior design ideas",
    "sections": [
        {
            "heading": "Living room",
            "paragraphs": ["Keep one sofa on the long wall and leave a path to the balcony."],
        },
        {
            "heading": "Bedroom",
            "paragraphs": ["A single wardrobe along the shorter wall leaves room to walk."],
        },
    ],
}


class FakeGemini:
    def __init__(self) -> None:
        self.calls = 0

    def draft(self, instruction: str, sources: str) -> dict:
        self.calls += 1
        assert "2BHK" in instruction
        assert "https://example.com/ideas" in sources
        return DRAFT


async def test_missing_key_stops_before_gemini_and_the_browser(settings):
    service = TaskService(settings, ExplodingBrowser)
    finished = await service.submit(WORD)
    assert finished["status"] == "needs_key"
    assert "GEMINI_API_KEY" in finished["summary"]
    assert finished["has_document"] is False
    assert "aistudio.google.com/apikey" in finished["summary"]


async def test_payment_still_blocks_a_word_request(settings):
    service = TaskService(settings, ExplodingBrowser)
    finished = await service.submit(
        "Write a Word document about paying with my credit card at checkout"
    )
    assert finished["status"] == "blocked"
    assert finished["has_document"] is False


async def test_stand_in_gemini_writes_a_docx(settings):
    keyed = Settings(**{**settings.__dict__, "gemini_api_key": "test-key"})
    gemini = FakeGemini()
    service = TaskService(keyed, FakeBrowser, gemini)
    created = await service.submit(WORD)
    for _ in range(100):
        current = service.get(created["id"])
        if current["status"] not in {"queued", "running"}:
            break
        import asyncio

        await asyncio.sleep(0.05)
    else:
        raise AssertionError(service.get(created["id"]))
    assert current["status"] == "completed", current["summary"]
    assert current["has_document"] is True
    assert gemini.calls == 1
    path = service.artifact(created["id"], "document")
    assert path is not None
    assert path.name == "brief.docx"
    text = _docx_text(path)
    assert "Living room" in text
    assert "https://example.com/ideas" in text
    assert "test-key" not in text
    evidence = Path("/opt/cursor/artifacts")
    if evidence.is_dir():
        shutil.copy(path, evidence / "day2_brief.docx")


def test_gemini_client_refuses_to_call_without_a_key(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("machaa.llm.gemini.urllib.request.urlopen", explode)
    client = GeminiClient("")
    try:
        client.draft("Write a Word document about chairs", "notes")
    except MissingKeyError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected MissingKeyError")


def test_gemini_client_sends_the_key_only_in_a_header(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(DRAFT),
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout=0):
        seen["url"] = request.full_url
        seen["header"] = request.get_header("X-goog-api-key")
        return Response()

    monkeypatch.setattr("machaa.llm.gemini.urllib.request.urlopen", fake_urlopen)
    draft = GeminiClient("secret-value").draft("Write a note", "A public page.")
    assert draft["title"] == DRAFT["title"]
    assert "secret-value" not in seen["url"]
    assert seen["header"] == "secret-value"
    assert "key=" not in seen["url"]


def test_parse_draft_strips_a_fence():
    text = "```json\n" + json.dumps(DRAFT) + "\n```"
    assert parse_draft(text)["sections"][0]["heading"] == "Living room"


def test_write_brief_is_a_real_docx(tmp_path):
    path = tmp_path / "brief.docx"
    write_brief(
        path,
        DRAFT["title"],
        json.dumps({"sections": DRAFT["sections"], "sources": []}),
    )
    assert path.read_bytes().startswith(b"PK")
    assert "Bedroom" in _docx_text(path)


def test_health_says_when_the_key_is_missing(settings):
    from fastapi.testclient import TestClient

    client = TestClient(create_app(settings, FakeBrowser))
    body = client.get("/api/health").json()
    assert body["day"] == 2
    assert body["gemini_configured"] is False
    page = client.get("/")
    assert "GEMINI_API_KEY" in page.text
    assert "aistudio.google.com/apikey" in page.text


def _docx_text(path: Path) -> str:
    import zipfile

    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return xml.replace("<", "\n")
