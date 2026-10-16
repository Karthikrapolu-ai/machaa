"""Guardian decisions, including the Day 1 acceptance sentence."""

from machaa.browser.urls import google_search_url
from machaa.core.guardian import Guardian

ACCEPTANCE = "Open Google and search for simple 2BHK interior design ideas"
PAYMENT = "Buy a sofa and pay with my credit card at checkout"


def test_acceptance_search_is_allowed():
    decision = Guardian().review_instruction(ACCEPTANCE)
    assert decision.allowed
    assert "2BHK" in google_search_url("simple 2BHK interior design ideas")


def test_payment_instruction_is_blocked():
    decision = Guardian().review_instruction(PAYMENT)
    assert not decision.allowed
    assert decision.category == "payment"
    assert "credit card" in decision.reason or "payment" in decision.reason or "purchase" in decision.reason


def test_destructive_instruction_is_blocked():
    decision = Guardian().review_instruction("Please rm -rf / on my computer")
    assert not decision.allowed
    assert decision.category == "destructive"


def test_download_instruction_is_blocked():
    decision = Guardian().review_instruction("Download the installer from https://example.com/app.exe")
    assert not decision.allowed
    assert decision.category == "download"


def test_public_page_instruction_is_allowed():
    decision = Guardian().review_instruction("Visit https://example.com and extract the page text")
    assert decision.allowed


def test_login_and_bank_urls_are_blocked():
    guardian = Guardian()
    for url in (
        "https://mail.google.com/mail/u/0/",
        "https://accounts.google.com/signin",
        "https://chatgpt.com/",
        "https://gemini.google.com/app",
        "https://www.paypal.com/checkout",
        "https://pay.google.com/",
    ):
        decision = guardian.review_instruction(f"Visit {url}")
        assert not decision.allowed, url


def test_private_and_file_urls_are_blocked():
    guardian = Guardian()
    for url in (
        "file:///etc/passwd",
        "http://127.0.0.1:8787",
        "http://localhost/admin",
        "http://10.1.2.3/",
        "http://192.168.0.5/",
        "http://169.254.169.254/latest/meta-data",
        "javascript:alert(1)",
        "https://8.8.8.8/",
    ):
        decision = guardian.review_navigation(url, resolve=False)
        assert not decision.allowed, url
