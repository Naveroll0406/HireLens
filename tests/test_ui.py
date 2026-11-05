"""Unit tests for the dashboard presentation layer and author recovery.

`ui.components` is deliberately pure (data in, HTML string out), so the card
markup can be asserted on without a running Streamlit server.
"""

from __future__ import annotations

import pytest

from processing.parser import (
    author_from_content,
    author_from_url,
    headline_from_content,
    resolve_author_headline,
    resolve_author_name,
)

components = pytest.importorskip("ui.components")
C = components


# ---------------------------------------------------------------------------
# Escaping — a post must not be able to break out of the card markup
# ---------------------------------------------------------------------------

def test_esc_escapes_angle_brackets_quotes_and_ampersands():
    assert C.esc('<script>alert("x")</script>') == (
        "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
    )
    # The old dashboard replaced < and > but not &, mangling "R&D".
    assert C.esc("R&D") == "R&amp;D"


def test_esc_maps_missing_values_to_fallback():
    assert C.esc(None, "Unknown") == "Unknown"
    assert C.esc("nan", "Unknown") == "Unknown"
    assert C.esc("", "Unknown") == "Unknown"


def test_job_card_escapes_hostile_fields():
    card = C.job_card({
        "role": '<img src=x onerror="alert(1)">',
        "author": "Acme & Co </div>",
        "skills": ["<b>Python</b>"],
        "content": "<script>bad()</script>",
        "score": 70,
    })
    # Every angle bracket from the data is neutralised, so the injected
    # markup is inert text rather than live elements.
    assert "<script>" not in card
    assert "<img" not in card
    assert "&lt;script&gt;" in card
    # The author's "</div>" must arrive escaped, not as a real closing tag.
    assert "&lt;/div&gt;" in card
    assert "Acme &amp; Co" in card
    # The card's own wrapper is still intact.
    assert card.count('<div class="hl-card"') == 1


def test_safe_url_rejects_dangerous_schemes():
    assert C.safe_url("javascript:alert(1)") == ""
    assert C.safe_url("data:text/html;base64,PHN2Zz4=") == ""
    assert C.safe_url("https://acme.com/jobs") == "https://acme.com/jobs"
    assert C.safe_url("mailto:hr@acme.com") == "mailto:hr@acme.com"
    assert C.safe_url(None) == ""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lo,hi,expected", [
    (2, 5, "2-5 yrs"),
    (5, None, "5+ yrs"),
    (None, 3, "up to 3 yrs"),
    (None, None, "Any experience"),
    (float("nan"), float("nan"), "Any experience"),
])
def test_format_experience(lo, hi, expected):
    assert C.format_experience(lo, hi) == expected


def test_parse_json_list_tolerates_junk():
    assert C.parse_json_list('["Python", "RAG"]') == ["Python", "RAG"]
    assert C.parse_json_list("[]") == []
    assert C.parse_json_list("not json") == []
    assert C.parse_json_list(None) == []
    assert C.parse_json_list(["a", "b"]) == ["a", "b"]


def test_is_linkedin_search_url():
    assert C.is_linkedin_search_url("https://www.linkedin.com/search/results/content/?keywords=ai")
    assert C.is_linkedin_search_url("https://linkedin.com/feed/")
    assert not C.is_linkedin_search_url("https://evil.com/linkedin.com/x")
    assert not C.is_linkedin_search_url("not a url")
    assert not C.is_linkedin_search_url("")


# ---------------------------------------------------------------------------
# Excerpt cleaning
# ---------------------------------------------------------------------------

def test_clean_excerpt_drops_the_actor_block():
    content = (
        "Feed post\n\nFireAI\n\n21h • \n\nFollow\n\n"
        "We're hiring a Senior Full Stack AI Engineer in Hyderabad."
    )
    cleaned = C.clean_excerpt(content, author="FireAI")
    assert cleaned.startswith("We're hiring")
    assert "Feed post" not in cleaned
    assert "Follow" not in cleaned


def test_clean_excerpt_drops_headline_and_connection_degree():
    content = (
        "Feed post\n\nEmmanuel N\n\n• 3rd+\n\n"
        "HR Specialist | Content Writer\n\n5h •\n\nFollow\n\n"
        "We are hiring an AI/ML Engineer."
    )
    cleaned = C.clean_excerpt(content, "Emmanuel N", "HR Specialist | Content Writer")
    assert cleaned == "We are hiring an AI/ML Engineer."


def test_clean_excerpt_keeps_body_that_has_no_actor_block():
    body = "We're hiring: AI Engineer\nLocation: Hyderabad\nApply\n2"
    # "Apply" and the trailing count look like chrome but are not leading, so
    # they must survive.
    assert C.clean_excerpt(body) == body


def test_clean_excerpt_never_returns_empty_for_nonempty_input():
    assert C.clean_excerpt("Follow\nFeed post") != ""


# ---------------------------------------------------------------------------
# Author / headline recovery
# ---------------------------------------------------------------------------

def test_author_from_content_skips_chrome():
    assert author_from_content("Feed post\n\nFireAI\n\n21h •\n\nFollow\n\nbody") == "FireAI"


def test_author_from_content_strips_connection_degree():
    assert author_from_content("Feed post\n\nSri Sahasra M • 3rd+\n\n23h •") == "Sri Sahasra M"


def test_author_from_content_ignores_body_text():
    # A post scraped without its actor block must not be attributed to a
    # sentence fragment such as "Required Skills:".
    assert author_from_content("Required Skills:\nPython, RAG") == ""
    assert author_from_content("What you'll do?\nBuild models") == ""
    assert author_from_content("\U0001F6A8 URGENT HIRING | Hyderabad") == ""


def test_author_from_url():
    assert author_from_url("https://www.linkedin.com/company/fireaiglobal/") == "Fireaiglobal"
    assert author_from_url("https://www.linkedin.com/in/shubham-mantri/") == "Shubham Mantri"
    assert author_from_url("https://example.com/in/x") == ""
    assert author_from_url("") == ""


def test_resolve_author_name_prefers_scraped_then_content_then_url():
    assert resolve_author_name("Scraped Name", "Feed post\n\nOther\n", "") == "Scraped Name"
    assert resolve_author_name("", "Feed post\n\nFromBody\n\n2h •", "") == "FromBody"
    assert resolve_author_name("", "Required Skills:",
                               "https://www.linkedin.com/company/acme/") == "Acme"
    assert resolve_author_name("", "", "") == ""


def test_headline_recovery_only_takes_pipe_separated_straplines():
    content = ("Feed post\n\nEmmanuel N\n\n• 3rd+\n\n"
               "HR Specialist | Content Writer\n\n5h •")
    assert headline_from_content(content, "Emmanuel N") == "HR Specialist | Content Writer"
    # A company post has no headline - the next line is the body.
    assert headline_from_content("Feed post\n\nFireAI\n\n21h •\n\nFollow\n\nWe're hiring",
                                 "FireAI") == ""
    assert resolve_author_headline("Scraped", content, "Emmanuel N") == "Scraped"


# ---------------------------------------------------------------------------
# Card content
# ---------------------------------------------------------------------------

def test_job_card_shows_apply_cta_when_a_link_exists():
    card = C.job_card({"role": "AI Engineer", "score": 90,
                       "primary_url": "https://acme.greenhouse.io/jobs/1"})
    assert "hl-cta" in card
    assert "acme.greenhouse.io" in card
    assert "No apply link" not in card


def test_job_card_warns_when_no_link_or_email():
    card = C.job_card({"role": "AI Engineer", "score": 50})
    assert "hl-apply-empty" in card
    assert "No apply link" in card


def test_job_card_drops_unsafe_links_from_the_apply_bar():
    card = C.job_card({"role": "X", "score": 10,
                       "primary_url": "javascript:alert(1)",
                       "extra_urls": ["javascript:alert(2)", "https://ok.com/a"]})
    assert "javascript:" not in card
    assert "ok.com" in card


def test_job_card_stagger_delay_increases_with_index():
    first = C.job_card({"role": "A", "score": 10}, index=0)
    third = C.job_card({"role": "A", "score": 10}, index=3)
    assert "--hl-delay:0ms" in first
    assert "--hl-delay:135ms" in third


def test_score_colour_bands_differ():
    from ui.theme import score_palette
    assert score_palette(95)[0] != score_palette(20)[0]
    assert score_palette(95)[0] == score_palette(80)[0]


# ---------------------------------------------------------------------------
# Markdown-safety of the emitted HTML
# ---------------------------------------------------------------------------

def assert_markdown_safe(html: str) -> None:
    """No blank line may be followed by 4+ spaces of indentation.

    Streamlit renders component HTML through a markdown parser, which turns
    that pattern into an indented *code block* - the markup then shows up as
    literal text on the page instead of rendering.
    """
    lines = html.splitlines()
    for i, line in enumerate(lines[1:], start=1):
        if not lines[i - 1].strip() and line.startswith("    "):
            raise AssertionError(
                f"line {i + 1} is indented 4+ spaces after a blank line, "
                f"markdown will render it as a code block: {line!r}"
            )


def test_masthead_is_markdown_safe_without_a_pill():
    # Regression: an empty pill_text left a bare line before indented markup,
    # and the whole masthead rendered as literal <span> text.
    assert_markdown_safe(C.masthead(False, "subtitle", ""))
    assert_markdown_safe(C.masthead(True, "subtitle", ""))


def test_masthead_renders_pill_and_status():
    html = C.masthead(False, "sub", "21 live roles")
    assert "21 live roles" in html
    assert "IDLE" in html
    assert "hl-status-live" not in html

    running = C.masthead(True, "sub", "")
    assert "SCRAPING" in running
    assert "hl-status-live" in running
    assert "hl-progress" in running


@pytest.mark.parametrize("html", [
    C.empty_state("t", "b"),
    C.empty_state("t", "b", ["one", "two"]),
    C.stat_tile("i", 1, "label"),
    C.run_row(0, None, 1, 2, 3, 4),
    C.run_row(0, None, 1, 2, 3, 4, "blocked"),
    C.job_card({"role": "r", "score": 50}),
    C.job_card({"role": "r", "score": 50, "skills": ["a"], "content": "body"}),
    C.section_heading("h"),
    C.group_heading("a", 2),
])
def test_components_are_markdown_safe(html):
    assert_markdown_safe(html)


def test_gemini_chip_appears_only_for_llm_scored_posts():
    rules = C.job_card({"role": "r", "score": 50, "scored_by": "rules"})
    assert "Gemini" not in rules

    llm = C.job_card({"role": "r", "score": 90, "scored_by": "gemini",
                      "rule_score": 40})
    assert "Gemini" in llm
    # the tooltip explains the gap between the two engines
    assert "rule engine said 40" in llm
