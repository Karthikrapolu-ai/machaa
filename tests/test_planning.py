"""Deterministic plans. No model is involved."""

from machaa.agents.planning import parse_research_request

ACCEPTANCE = "Open Google and search for simple 2BHK interior design ideas"


def test_acceptance_sentence_is_a_google_search():
    plan = parse_research_request(ACCEPTANCE)
    assert plan is not None
    assert plan.kind == "search"
    assert plan.query == "simple 2BHK interior design ideas"


def test_other_search_phrasings():
    assert parse_research_request("search for red chairs").query == "red chairs"
    assert parse_research_request("search google for red chairs").query == "red chairs"
    assert parse_research_request("google search for red chairs").query == "red chairs"


def test_visit_a_public_url():
    plan = parse_research_request("Visit https://example.com and extract the page text")
    assert plan is not None
    assert plan.kind == "visit"
    assert plan.url == "https://example.com"


def test_visit_a_bare_domain():
    plan = parse_research_request("Open example.com")
    assert plan is not None
    assert plan.kind == "visit"
    assert plan.url == "https://example.com"


def test_open_google_without_a_query_is_not_a_search():
    assert parse_research_request("Open Google") is None


def test_desktop_control_is_not_research():
    assert parse_research_request("Move the mouse and click the button") is None
