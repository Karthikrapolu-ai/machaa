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


SOCIAL = (
    "Machaa, prepare an Instagram content document for Vistaara Interiors "
    "about affordable premium-looking 2BHK interiors. Research design ideas, "
    "find a suitably licensed reference image, and create 3 captions with hashtags."
)


def test_acceptance_social_sentence_is_a_social_plan():
    plan = parse_research_request(SOCIAL)
    assert plan is not None
    assert plan.kind == "social"
    assert plan.platform == "Instagram"
    assert plan.brand == "Vistaara Interiors"
    assert plan.query == "affordable premium-looking 2BHK interiors"


def test_notepad_captions_are_desktop_not_a_social_post():
    sentence = (
        "Machaa, write three Instagram caption ideas for Vistaara Interiors in Notepad."
    )
    plan = parse_research_request(sentence)
    assert plan is not None
    assert plan.kind == "desktop"


def test_bedroom_search_stays_a_search():
    plan = parse_research_request(
        "Machaa, open Google and search for modern bedroom interiors."
    )
    assert plan is not None
    assert plan.kind == "search"
    assert plan.query == "modern bedroom interiors"


def test_word_document_stays_a_document():
    plan = parse_research_request("Write a Word document about simple 2BHK interior design ideas")
    assert plan is not None
    assert plan.kind == "document"
    assert plan.query == "simple 2BHK interior design ideas"
