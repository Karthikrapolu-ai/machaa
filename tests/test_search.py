"""Search providers: classify a Google wall, then use the next source."""

from machaa.config import Settings
from machaa.core.guardian import Guardian
from machaa.search.providers import (
    ProviderError,
    SearchHit,
    configured_fallback_names,
    fallback_reason,
    parse_duckduckgo_html,
    prepare_results_document,
    unwrap_result_url,
)
from machaa.search.session import _provider_page_url, perform_search

QUERY = "simple 2BHK interior design ideas"
SAMPLE = """
<html><head><title>results</title></head><body>
<a class="result__a" href="https://www.homelane.com/design-ideas/2bhk-house-design/">2BHK House Design</a>
<a class="result__snippet" href="https://www.homelane.com/design-ideas/2bhk-house-design/">Rooms and storage</a>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.pinterest.com%2Fideas%2F">Pinterest boards</a>
<td class="result__snippet">Saved boards</td>
<script>alert("no")</script>
</body></html>
"""


def test_robot_check_and_consent_are_classified():
    assert fallback_reason(
        "https://www.google.com/sorry/index",
        "sorry",
        "Our systems have detected unusual traffic",
    ) == "robot_check"
    assert fallback_reason(
        "https://consent.google.com/m",
        "Before you continue",
        "Before you continue to Google",
    ) == "consent"
    assert fallback_reason(
        "https://www.google.com/search?q=chairs",
        "chairs - Google Search",
        "About 1,000 results",
    ) is None


def test_duckduckgo_links_are_unwrapped_and_scripts_are_removed():
    hits = parse_duckduckgo_html(SAMPLE)
    assert hits[0] == SearchHit(
        "2BHK House Design",
        "https://www.homelane.com/design-ideas/2bhk-house-design/",
        "Rooms and storage",
    )
    assert hits[1].url == "https://www.pinterest.com/ideas/"
    assert unwrap_result_url(
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa"
    ) == "https://example.com/a"
    document = prepare_results_document(SAMPLE, "https://duckduckgo.com/")
    assert "<script" not in document.lower()
    assert 'base href="https://duckduckgo.com/"' in document
    assert "2BHK House Design" in document


def test_provider_order_and_page_urls_omit_keys():
    assert configured_fallback_names(brave_key="", google_key="", google_cx="") == ["duckduckgo"]
    assert configured_fallback_names(brave_key="x", google_key="y", google_cx="z") == [
        "brave",
        "google_cse",
        "duckduckgo",
    ]
    brave = _provider_page_url("brave", QUERY)
    cse = _provider_page_url("google_cse", QUERY)
    assert "key=" not in brave and "key=" not in cse
    assert "token" not in brave.lower()


def test_env_search_keys_default_to_empty(monkeypatch):
    for name in (
        "MACHAA_BRAVE_SEARCH_API_KEY",
        "MACHAA_GOOGLE_SEARCH_API_KEY",
        "MACHAA_GOOGLE_SEARCH_CX",
    ):
        monkeypatch.delenv(name, raising=False)
    loaded = Settings.from_env()
    assert loaded.brave_search_api_key == ""
    assert loaded.google_search_api_key == ""
    assert loaded.google_search_cx == ""


async def test_google_results_stop_the_fallback(settings, monkeypatch):
    called = False

    def explode(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("fallback should not run")

    monkeypatch.setattr("machaa.search.session.call_provider", explode)

    class Browser:
        async def search_google(self, query):
            return {
                "url": "https://www.google.com/search?q=chairs",
                "title": "chairs",
                "text": "results",
                "blocked_page": None,
                "hits": [{"title": "A chair", "url": "https://example.com/chair", "snippet": ""}],
            }

    result = await perform_search(Browser(), settings, Guardian(), "chairs")
    assert result["provider"] == "google"
    assert result["needs_human"] is False
    assert called is False


async def test_robot_check_falls_back_without_solving_it(settings, monkeypatch):
    class Browser:
        def __init__(self):
            self.document = ""

        async def search_google(self, query):
            return {
                "url": "https://www.google.com/sorry/index",
                "title": "sorry",
                "text": "unusual traffic",
                "blocked_page": "robot_check",
                "hits": [{"title": "ignore", "url": "https://www.google.com/sorry/index"}],
            }

        async def show_document(self, html):
            self.document = html

        async def extract_text(self):
            return "2BHK House Design"

        async def page_title(self):
            return QUERY

    browser = Browser()

    def fake_call(name, query, **kwargs):
        assert name == "duckduckgo"
        assert kwargs["brave_key"] == ""
        return (
            [SearchHit("2BHK House Design", "https://www.homelane.com/ideas", "rooms")],
            SAMPLE,
        )

    monkeypatch.setattr("machaa.search.session.call_provider", fake_call)
    result = await perform_search(browser, settings, Guardian(), QUERY)
    assert result["provider"] == "duckduckgo"
    assert result["needs_human"] is False
    assert result["hits"][0]["url"] == "https://www.homelane.com/ideas"
    assert "did not try to solve it" in result["note"]
    assert "<script" not in browser.document.lower()
    assert "html.duckduckgo.com" in result["url"]


async def test_every_provider_empty_needs_a_person(settings, monkeypatch):
    class Browser:
        async def search_google(self, query):
            return {
                "url": "https://www.google.com/sorry/index",
                "title": "sorry",
                "text": "unusual traffic",
                "blocked_page": "robot_check",
                "hits": [],
            }

    def empty(name, query, **kwargs):
        raise ProviderError(name)

    monkeypatch.setattr("machaa.search.session.call_provider", empty)
    result = await perform_search(Browser(), settings, Guardian(), QUERY)
    assert result["needs_human"] is True
    assert result["hits"] == []
    assert "will not solve" in result["note"]
