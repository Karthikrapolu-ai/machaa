"""Dashboard API. Blocked requests are recorded and do not start a browser."""

from fastapi.testclient import TestClient

from machaa.main import create_app
from tests.fakes import ExplodingBrowser, FakeBrowser

ACCEPTANCE = "Open Google and search for simple 2BHK interior design ideas"
PAYMENT = "Buy a sofa and pay with my credit card at checkout"


def test_health_and_dashboard_title(settings):
    client = TestClient(create_app(settings, FakeBrowser))
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["product"] == "MACHAA"
    page = client.get("/")
    assert page.status_code == 200
    assert "<title>MACHAA</title>" in page.text
    assert "<h1>MACHAA</h1>" in page.text
    assert "Content-Security-Policy" in page.headers


def test_payment_instruction_is_blocked_without_a_browser(settings):
    client = TestClient(create_app(settings, ExplodingBrowser))
    response = client.post("/api/tasks", json={"instruction": PAYMENT})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "blocked"
    assert body["block_reason"]
    assert body["has_screenshot"] is False
    listed = client.get("/api/tasks").json()["tasks"]
    assert listed[-1]["id"] == body["id"]
    assert listed[-1]["status"] == "blocked"


def test_destructive_action_and_download_are_blocked(settings):
    client = TestClient(create_app(settings, ExplodingBrowser))
    destructive = client.post("/api/tasks", json={"instruction": "wipe the disk"})
    download = client.post("/api/tasks", json={"instruction": "download https://example.com/tool.sh"})
    assert destructive.json()["status"] == "blocked"
    assert download.json()["status"] == "blocked"


def test_bank_login_url_is_blocked(settings):
    client = TestClient(create_app(settings, ExplodingBrowser))
    response = client.post(
        "/api/tasks",
        json={"instruction": "Visit https://accounts.google.com and sign in"},
    )
    assert response.json()["status"] == "blocked"


def test_stop_endpoint_and_unknown_task(settings):
    app = create_app(settings, FakeBrowser)
    client = TestClient(app)
    created = app.state.service.store.create(ACCEPTANCE)
    response = client.post(f"/api/tasks/{created.id}/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    missing = client.post("/api/tasks/task_not_real/stop")
    assert missing.status_code == 404


def test_blank_instruction_is_rejected(settings):
    client = TestClient(create_app(settings, FakeBrowser))
    response = client.post("/api/tasks", json={"instruction": "   "})
    assert response.status_code == 422


def test_computer_agent_is_not_pretending_to_run(settings):
    client = TestClient(create_app(settings, ExplodingBrowser))
    response = client.post("/api/tasks", json={"instruction": "Move the mouse on my desktop"})
    body = response.json()
    assert body["status"] == "completed"
    assert body["agent"] == "computer"
    assert "not built yet" in body["summary"]
