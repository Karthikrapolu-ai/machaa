"""The gateway is the enforcement point, not the wording of a prompt."""

import socket

import pytest

from machaa.core.errors import ToolDenied
from machaa.core.guardian import ALLOWED_TOOLS, Guardian
from machaa.tools.gateway import ToolGateway


def _handlers():
    called = []

    async def handler(arguments):
        called.append(arguments)
        return {"ok": True, "url": arguments.get("url", "")}

    return called, {name: handler for name in ALLOWED_TOOLS}


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("os.system", {"cmd": "rm -rf /"}),
        ("browser.download", {"url": "https://example.com/setup.exe"}),
        ("computer.click", {"x": 1, "y": 2}),
        ("shell.exec", {"command": "shutdown"}),
    ],
)
async def test_unknown_tools_never_run(tool, arguments):
    called, handlers = _handlers()
    gateway = ToolGateway(Guardian(), handlers)
    with pytest.raises(ToolDenied):
        await gateway.execute(tool, arguments)
    assert called == []


async def test_checkout_url_is_denied_even_after_a_safe_sentence():
    called, handlers = _handlers()
    gateway = ToolGateway(Guardian(), handlers)
    with pytest.raises(ToolDenied) as caught:
        await gateway.execute(
            "browser.visit_public_page",
            {"url": "https://www.paypal.com/checkoutnow"},
        )
    assert caught.value.category in {"payment", "url"}
    assert called == []


async def test_executable_download_url_is_denied():
    called, handlers = _handlers()
    gateway = ToolGateway(Guardian(), handlers)
    with pytest.raises(ToolDenied) as caught:
        await gateway.execute(
            "browser.visit_public_page",
            {"url": "https://example.com/files/setup.exe"},
        )
    assert caught.value.category == "download"
    assert called == []


async def test_report_may_quote_a_page_that_mentions_checkout():
    called, handlers = _handlers()
    gateway = ToolGateway(Guardian(), handlers)
    result = await gateway.execute(
        "report.save_markdown",
        {"markdown": "The article says to compare a credit card before you checkout."},
    )
    assert result["ok"] is True
    assert called


async def test_gateway_refuses_to_register_a_shell():
    async def handler(arguments):
        return {}

    with pytest.raises(ValueError):
        ToolGateway(Guardian(), {"os.system": handler})


async def test_hostname_that_resolves_to_loopback_is_denied(monkeypatch):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("machaa.core.guardian.socket.getaddrinfo", fake_getaddrinfo)
    called, handlers = _handlers()
    gateway = ToolGateway(Guardian(), handlers)
    with pytest.raises(ToolDenied):
        await gateway.execute("browser.visit_public_page", {"url": "https://example.com"})
    assert called == []
