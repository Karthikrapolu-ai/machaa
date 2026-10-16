"""Denials that must hold at tool execution, whatever the prompt said."""

import pytest

from machaa.core.errors import ToolDenied
from machaa.core.guardian import ALLOWED_TOOLS, Guardian
from machaa.tools.gateway import ToolGateway

PAYMENT_URLS = [
    "https://www.paypal.com/checkoutnow",
    "https://checkout.stripe.com/pay/cs_test",
    "https://example.com/cart",
    "https://shop.example/checkout",
    "https://billing.example/payments/new",
]

DOWNLOAD_URLS = [
    "https://example.com/Machaa.dmg",
    "https://example.com/setup.exe",
    "https://example.com/archive.zip",
    "https://example.com/install.sh",
]

PRIVATE_URLS = [
    "http://127.0.0.1/",
    "http://10.0.0.8/",
    "http://192.168.1.20/admin",
    "http://169.254.169.254/",
    "file:///etc/passwd",
    "chrome://settings",
]


def _gateway():
    called = []

    async def handler(arguments):
        called.append(arguments)
        return {"ok": True}

    return called, ToolGateway(Guardian(), {name: handler for name in ALLOWED_TOOLS})


@pytest.mark.parametrize("url", PAYMENT_URLS + DOWNLOAD_URLS + PRIVATE_URLS)
async def test_dangerous_navigation_does_not_reach_the_handler(url):
    called, gateway = _gateway()
    with pytest.raises(ToolDenied):
        await gateway.execute("browser.visit_public_page", {"url": url})
    assert called == []


@pytest.mark.parametrize(
    "instruction",
    [
        "Buy a sofa and pay with my credit card at checkout",
        "Place an order and add it to cart",
        "Send money with paypal",
        "Use card number 4111111111111111",
        "rm -rf /home",
        "shutdown the computer",
        "download the zip",
    ],
)
def test_dangerous_instructions_are_blocked(instruction):
    decision = Guardian().review_instruction(instruction)
    assert decision.allowed is False


def test_safe_search_is_not_blocked():
    decision = Guardian().review_instruction(
        "Open Google and search for simple 2BHK interior design ideas"
    )
    assert decision.allowed is True
