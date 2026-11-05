"""
Tests for the optional Gemini scoring pass.

The point of these is the *fallback*: the pipeline must behave identically to
the rule-only version whenever the LLM is missing, misconfigured, offline or
returning nonsense.  Nothing here makes a real network call.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from processing import llm_scoring
from processing.scoring import score_post
from storage.models import ParsedPost, RawPost

# Captured at import time, before conftest's autouse fixture stubs it out, so
# the discovery logic itself can still be tested.
REAL_FIND_API_KEY = llm_scoring.find_api_key


def make_parsed(content: str = "Hiring an AI Engineer in Hyderabad, 3 years.",
                author: str = "Recruiter") -> ParsedPost:
    raw = RawPost(
        post_urn="urn:li:activity:1", post_url="", author_name=author,
        author_headline="", author_url="", content=content,
        timestamp_text="2h", keyword_matched="AI Engineer",
        scraped_at=datetime.now(),
    )
    parsed = ParsedPost(raw=raw)
    parsed.relevance_score = 55
    return parsed


# ---------------------------------------------------------------------------
# Key discovery
# ---------------------------------------------------------------------------

def test_env_file_parsing_tolerates_shell_syntax(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "PLAIN=abc123\n"
        'export EXPORTED="def456"\n'
        '$env:POWERSHELL = "ghi789"\n'
        "set CMDSTYLE=jkl012\n"
        "BLANKLINE\n",
        encoding="utf-8",
    )
    values = llm_scoring._parse_env_file(env)
    assert values["PLAIN"] == "abc123"
    assert values["EXPORTED"] == "def456"
    assert values["POWERSHELL"] == "ghi789"      # the paste that broke things
    assert values["CMDSTYLE"] == "jkl012"
    assert "BLANKLINE" not in values


def test_find_api_key_prefers_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "  from-env  ")
    assert REAL_FIND_API_KEY() == "from-env"


def test_find_api_key_strips_quotes_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", '"quoted-key"')
    assert REAL_FIND_API_KEY() == "quoted-key"


def test_is_configured_false_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: None)
    assert llm_scoring.is_configured() is False


# ---------------------------------------------------------------------------
# Fallback behaviour - the important part
# ---------------------------------------------------------------------------

def test_apply_keeps_rule_score_when_no_key(monkeypatch):
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: None)
    posts = [make_parsed()]
    engine, detail = llm_scoring.apply(posts)
    assert engine == "rules"
    assert "no API key" in detail
    assert posts[0].relevance_score == 55
    assert posts[0].rule_score == 55
    assert posts[0].scored_by == "rules"


def test_apply_keeps_rule_score_when_api_errors(monkeypatch):
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")

    def boom(*args, **kwargs):
        raise llm_scoring.LLMError("HTTP 503: upstream down")

    monkeypatch.setattr(llm_scoring, "classify_texts", boom)
    posts = [make_parsed()]
    engine, _ = llm_scoring.apply(posts)
    assert engine == "rules"
    assert posts[0].relevance_score == 55
    assert posts[0].scored_by == "rules"


def test_apply_keeps_rule_score_on_garbage_response(monkeypatch):
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")
    monkeypatch.setattr(llm_scoring, "classify_texts", lambda *a, **k: [])
    posts = [make_parsed()]
    engine, _ = llm_scoring.apply(posts)
    assert engine == "rules"
    assert posts[0].relevance_score == 55


def test_apply_overrides_score_and_records_engine(monkeypatch):
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")
    monkeypatch.setattr(llm_scoring, "classify_texts", lambda *a, **k: [
        llm_scoring.Verdict(index=0, is_hiring=True, score=92,
                            role="Senior AI Engineer", reason="strong match"),
    ])
    posts = [make_parsed()]
    engine, _ = llm_scoring.apply(posts)
    assert engine == "gemini"
    assert posts[0].relevance_score == 92
    assert posts[0].rule_score == 55          # original kept for comparison
    assert posts[0].scored_by == "gemini"
    assert posts[0].role == "Senior AI Engineer"
    assert "strong match" in posts[0].filter_reason


def test_non_vacancy_is_forced_below_threshold(monkeypatch):
    """A high relevance number must not sneak a non-vacancy through."""
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")
    monkeypatch.setattr(llm_scoring, "classify_texts", lambda *a, **k: [
        llm_scoring.Verdict(index=0, is_hiring=False, score=85,
                            role="", reason="author is job hunting"),
    ])
    posts = [make_parsed()]
    llm_scoring.apply(posts)
    assert posts[0].relevance_score <= 20


def test_partial_batch_failure_is_reported(monkeypatch):
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")
    monkeypatch.setattr(llm_scoring, "BATCH_SIZE", 1)
    calls = {"n": 0}

    def flaky(items, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return [llm_scoring.Verdict(0, True, 90, "AI Engineer", "good")]
        raise llm_scoring.LLMError("timeout")

    monkeypatch.setattr(llm_scoring, "classify_texts", flaky)
    posts = [make_parsed(), make_parsed()]
    engine, detail = llm_scoring.apply(posts)
    assert engine == "gemini-partial"
    assert "1/2" in detail
    assert posts[0].scored_by == "gemini"
    assert posts[1].scored_by == "rules"       # the failed one is untouched
    assert posts[1].relevance_score == 55


def test_empty_input_is_safe(monkeypatch):
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")
    engine, _ = llm_scoring.apply([])
    assert engine == "rules"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def test_parse_verdicts_reads_a_well_formed_response():
    raw = {"candidates": [{"content": {"parts": [{"text":
        '[{"index":0,"is_hiring":true,"relevance":80,"role":"ML Engineer","reason":"ok"}]'
    }]}}]}
    verdicts = llm_scoring._parse_verdicts(raw)
    assert len(verdicts) == 1
    assert verdicts[0].score == 80
    assert verdicts[0].role == "ML Engineer"


def test_parse_verdicts_clamps_out_of_range_scores():
    raw = {"candidates": [{"content": {"parts": [{"text":
        '[{"index":0,"is_hiring":true,"relevance":5000,"reason":"x"},'
        ' {"index":1,"is_hiring":true,"relevance":-20,"reason":"y"}]'
    }]}}]}
    verdicts = llm_scoring._parse_verdicts(raw)
    assert verdicts[0].score == 100
    assert verdicts[1].score == 0


def test_parse_verdicts_skips_malformed_items():
    raw = {"candidates": [{"content": {"parts": [{"text":
        '[{"no_index":1}, {"index":1,"is_hiring":true,"relevance":50,"reason":"ok"}]'
    }]}}]}
    verdicts = llm_scoring._parse_verdicts(raw)
    assert [v.index for v in verdicts] == [1]


@pytest.mark.parametrize("raw,expected", [
    ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, "empty response"),
    ({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}, "not valid JSON"),
    ({"candidates": [{"content": {"parts": [{"text": '{"a":1}'}]}}]}, "not a JSON array"),
])
def test_parse_verdicts_raises_llm_error_on_bad_shapes(raw, expected):
    with pytest.raises(llm_scoring.LLMError, match=expected):
        llm_scoring._parse_verdicts(raw)


# ---------------------------------------------------------------------------
# The rule engine still works on its own
# ---------------------------------------------------------------------------

def test_rule_engine_unchanged_without_llm():
    parsed = make_parsed()
    score_post(parsed, target_locations=["Hyderabad"], experience_range=(0, 15))
    assert 0 <= parsed.relevance_score <= 100
    assert parsed.filter_reason           # breakdown is still populated


# ---------------------------------------------------------------------------
# The candidate profile drives the relevance score
# ---------------------------------------------------------------------------

def test_prompt_embeds_the_candidate_profile():
    profile = "3 years Python and RAG. No data-analyst or Java roles."
    prompt = llm_scoring._prompt([("Rec", "post body")], ["Hyderabad"], (0, 5), profile)
    assert profile in prompt
    # The grader must be told to judge against the profile, not AI roles at large.
    assert "THE CANDIDATE" in prompt
    assert "not against AI roles" in prompt


def test_prompt_falls_back_to_the_default_profile():
    for empty in (None, "", "   "):
        prompt = llm_scoring._prompt([("Rec", "body")], [], (0, 5), empty)
        assert llm_scoring.DEFAULT_PROFILE.strip()[:40] in prompt


def test_prompt_includes_locations_and_experience():
    prompt = llm_scoring._prompt([("Rec", "body")], ["Pune", "Goa"], (2, 7))
    assert "Pune, Goa" in prompt
    assert "2-7 years" in prompt


def test_prompt_truncates_long_posts():
    long_body = "zz" * llm_scoring.CONTENT_CHARS      # 2x the budget
    prompt = llm_scoring._prompt([("Rec", long_body)], [], (0, 5))
    # "z" appears nowhere else in the prompt, so this counts the body alone.
    assert prompt.count("z") == llm_scoring.CONTENT_CHARS


def test_apply_forwards_the_profile_to_the_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")

    def capture(items, key, model, targets, exp_range, profile=None):
        seen["profile"] = profile
        return [llm_scoring.Verdict(0, True, 70, "AI Engineer", "ok")]

    monkeypatch.setattr(llm_scoring, "classify_texts", capture)
    llm_scoring.apply([make_parsed()], profile="my bespoke profile")
    assert seen["profile"] == "my bespoke profile"


def test_rescore_rows_forwards_the_profile(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: "k")

    def capture(items, key, model, targets, exp_range, profile=None):
        seen["profile"] = profile
        return [llm_scoring.Verdict(0, True, 80, "X", "ok")]

    monkeypatch.setattr(llm_scoring, "classify_texts", capture)
    results = list(llm_scoring.rescore_rows([(7, "Rec", "body")],
                                            profile="bespoke again"))
    assert seen["profile"] == "bespoke again"
    assert results[0][0] == 7          # the post id is carried through
