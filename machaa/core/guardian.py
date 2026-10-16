"""Deterministic Guardian.

The allowlist is enforced inside ``review_tool_call``, which the tool
gateway runs before any handler. Checking the owner's sentence is an
extra early stop. It is not the control that matters: a checkout URL is
refused even when the original sentence looked harmless.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from machaa.browser.urls import google_search_url

ALLOWED_TOOLS = frozenset(
    {
        "browser.search_google",
        "browser.visit_public_page",
        "browser.extract_text",
        "browser.screenshot",
        "report.save_markdown",
    }
)

ALLOWED_ARGS = {
    "browser.search_google": frozenset({"query"}),
    "browser.visit_public_page": frozenset({"url"}),
    "browser.extract_text": frozenset(),
    "browser.screenshot": frozenset(),
    "report.save_markdown": frozenset({"markdown"}),
}

# Banking, payment, email, and assistant login sites. Matched on the host.
BLOCKED_HOST_SUFFIXES = (
    "paypal.com",
    "paypal.me",
    "venmo.com",
    "cash.app",
    "stripe.com",
    "squareup.com",
    "square.com",
    "adyen.com",
    "braintreepayments.com",
    "authorize.net",
    "worldpay.com",
    "klarna.com",
    "affirm.com",
    "afterpay.com",
    "coinbase.com",
    "binance.com",
    "kraken.com",
    "wellsfargo.com",
    "bankofamerica.com",
    "chase.com",
    "citi.com",
    "citibank.com",
    "capitalone.com",
    "americanexpress.com",
    "discover.com",
    "hsbc.com",
    "barclays.com",
    "barclays.co.uk",
    "lloydsbank.com",
    "revolut.com",
    "wise.com",
    "westernunion.com",
    "moneygram.com",
    "chatgpt.com",
    "openai.com",
    "claude.ai",
    "anthropic.com",
    "gmail.com",
    "googlemail.com",
)

SENSITIVE_GOOGLE_PREFIXES = (
    "accounts.",
    "myaccount.",
    "mail.",
    "pay.",
    "payments.",
    "wallet.",
    "gemini.",
    "drive.",
    "docs.",
    "calendar.",
    "photos.",
    "contacts.",
    "admin.",
)

CHECKOUT_PATH_MARKERS = (
    "/checkout",
    "/cart",
    "/payment",
    "/payments",
    "/billing",
    "/add-to-cart",
    "/place-order",
)

DOWNLOAD_EXTENSIONS = (
    ".exe",
    ".msi",
    ".dmg",
    ".pkg",
    ".deb",
    ".rpm",
    ".apk",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".7z",
    ".iso",
    ".dll",
    ".scr",
    ".jar",
    ".appimage",
    ".msix",
    ".cab",
    ".bin",
)

PAYMENT_INTENT = re.compile(
    r"\b("
    r"buy|purchase|purchasing|"
    r"checkout|check\s*out|"
    r"add\s+to\s+cart|place\s+(an\s+)?order|"
    r"pay|pays|payment|payments|"
    r"credit\s*cards?|debit\s*cards?|"
    r"cvv|cvc|card\s*numbers?|"
    r"wire\s+transfers?|bank\s+transfers?|send\s+money|"
    r"paypal|venmo|cash\s*app"
    r")\b",
    re.IGNORECASE,
)

DOWNLOAD_INTENT = re.compile(
    r"\b(download|wget)\b|\bcurl\b[^\n]{0,40}\s-O\b",
    re.IGNORECASE,
)

DESTRUCTIVE_INTENT = re.compile(
    r"("
    r"\brm\s+-"
    r"|\bmkfs\b"
    r"|\b(shutdown|poweroff|reboot)\b"
    r"|\b(format|wipe)\b[^\n]{0,48}\b(disk|drive|computer|files|laptop|machine)\b"
    r"|\bdelete\b[^\n]{0,48}\b(files|disk|everything|system|computer)\b"
    r"|\bdrop\s+(database|table)\b"
    r"|\bchmod\s+-R\s+777\b"
    r")",
    re.IGNORECASE,
)

CARD_NUMBER = re.compile(r"\b(?:\d[ -]?){13,19}\b")

MESSAGES = {
    "payment": (
        "Machaa blocked this because it asks for a purchase, payment, "
        "credit card, checkout, or other financial transaction."
    ),
    "download": (
        "Machaa blocked this because it asks to download a file. Downloads are not allowed."
    ),
    "destructive": (
        "Machaa blocked this because it asks for a destructive action on the computer."
    ),
    "url": (
        "Machaa blocked this website. Banking, payment, email, login, "
        "and non-public addresses are not allowed."
    ),
    "tool": (
        "Machaa blocked this action because it is not on the allowlist of safe browser actions."
    ),
}

MAX_MARKDOWN_LEN = 100_000


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    category: str

    @classmethod
    def allow(cls) -> Decision:
        return cls(True, "", "ok")

    @classmethod
    def deny(cls, category: str, reason: str) -> Decision:
        return cls(False, reason, category)


class Guardian:
    """Allow a fixed set of browser actions and refuse everything else."""

    def review_instruction(self, instruction: str) -> Decision:
        """Reject a request before a browser starts. Tool review still runs later."""

        if not instruction or not instruction.strip():
            return Decision.deny("tool", "Tell Machaa what to look up.")
        if PAYMENT_INTENT.search(instruction) or CARD_NUMBER.search(instruction):
            return Decision.deny("payment", MESSAGES["payment"])
        if DESTRUCTIVE_INTENT.search(instruction):
            return Decision.deny("destructive", MESSAGES["destructive"])
        if DOWNLOAD_INTENT.search(instruction):
            return Decision.deny("download", MESSAGES["download"])
        for url in urls_in_text(instruction):
            decision = self.review_navigation(url, resolve=False)
            if not decision.allowed:
                return decision
        return Decision.allow()

    def review_tool_call(self, tool: str, arguments: dict) -> Decision:
        """Decide whether this exact call may run. This is the enforcement point."""

        if tool not in ALLOWED_TOOLS:
            return Decision.deny("tool", MESSAGES["tool"])
        if set(arguments) != ALLOWED_ARGS[tool]:
            return Decision.deny(
                "tool",
                "Machaa blocked this action because its arguments are not allowed.",
            )
        if tool == "browser.search_google":
            return self._review_search(arguments["query"])
        if tool == "browser.visit_public_page":
            return self.review_navigation(str(arguments["url"]), resolve=True)
        if tool == "report.save_markdown":
            return self._review_markdown(arguments["markdown"])
        return Decision.allow()

    def review_navigation(self, url: str, *, resolve: bool) -> Decision:
        """Apply the public-web rules to one address."""

        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return Decision.deny("url", MESSAGES["url"])
        host = parsed.hostname
        if not host:
            return Decision.deny("url", MESSAGES["url"])
        try:
            host = host.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError:
            return Decision.deny("url", MESSAGES["url"])
        if _host_is_blocked(host):
            return Decision.deny("url", MESSAGES["url"])
        ip_decision = _review_ip_literal(host)
        if ip_decision is not None:
            return ip_decision
        if "." not in host:
            return Decision.deny("url", MESSAGES["url"])
        haystack = unquote((parsed.path or "") + "?" + (parsed.query or "")).lower()
        if any(marker in haystack for marker in CHECKOUT_PATH_MARKERS):
            return Decision.deny("payment", MESSAGES["payment"])
        if _path_suffix(unquote(parsed.path or "").lower()) in DOWNLOAD_EXTENSIONS:
            return Decision.deny("download", MESSAGES["download"])
        if resolve:
            dns_decision = _review_dns(host)
            if not dns_decision.allowed:
                return dns_decision
        return Decision.allow()

    def _review_search(self, query: object) -> Decision:
        if not isinstance(query, str):
            return Decision.deny("tool", "Machaa blocked this search because the query is invalid.")
        cleaned = query.strip()
        if not cleaned or len(cleaned) > 300 or any(ord(char) < 32 for char in cleaned):
            return Decision.deny("tool", "Machaa blocked this search because the query is invalid.")
        if CARD_NUMBER.search(cleaned):
            return Decision.deny("payment", MESSAGES["payment"])
        try:
            url = google_search_url(cleaned)
        except ValueError:
            return Decision.deny("tool", "Machaa blocked this search because the query is invalid.")
        return self.review_navigation(url, resolve=True)

    def _review_markdown(self, markdown: object) -> Decision:
        # Page text is data being saved, not an instruction. Do not scan it
        # for words like "buy": a design article can mention shopping.
        if not isinstance(markdown, str) or len(markdown) > MAX_MARKDOWN_LEN:
            return Decision.deny("tool", "Machaa blocked this report because the contents are invalid.")
        return Decision.allow()


def urls_in_text(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"https?://[^\s<>\"']+", text, flags=re.IGNORECASE):
        found.append(match.group(0).rstrip(".,);"))
    return found


def _host_is_blocked(host: str) -> bool:
    for suffix in BLOCKED_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return True
    if host == "google.com" or host.endswith(".google.com"):
        return host.startswith(SENSITIVE_GOOGLE_PREFIXES)
    return False


def _review_ip_literal(host: str) -> Decision | None:
    if host.isdigit():
        return Decision.deny("url", MESSAGES["url"])
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if not ip.is_global:
        return Decision.deny("url", MESSAGES["url"])
    return Decision.deny("url", MESSAGES["url"])


def _review_dns(host: str) -> Decision:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return Decision.deny("url", "Machaa could not confirm this website is a public address.")
    if not infos:
        return Decision.deny("url", "Machaa could not confirm this website is a public address.")
    for info in infos:
        raw = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return Decision.deny("url", MESSAGES["url"])
        if not ip.is_global:
            return Decision.deny("url", MESSAGES["url"])
    return Decision.allow()


def _path_suffix(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".tar.gz"):
        return ".gz"
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]
