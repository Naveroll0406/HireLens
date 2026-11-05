"""Shared pytest configuration and fixtures for HireLens tests.

Ensures the project root is importable and provides small factories for
building RawPost / ParsedPost objects without touching the scraper or network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the project root importable (config, processing, storage, ...).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from storage.models import ParsedPost, RawPost  # noqa: E402


def _make_raw(
    *,
    content: str = "",
    post_urn: str = "urn:li:activity:1",
    author_name: str = "Jane Recruiter",
    author_headline: str = "Talent @ Acme",
    keyword_matched: str = "AI Engineer",
    post_url: str = "https://www.linkedin.com/feed/update/urn:li:activity:1/",
    author_url: str = "https://www.linkedin.com/in/jane/",
    timestamp_text: str = "2h",
    extracted_urls: list[str] | None = None,
) -> RawPost:
    return RawPost(
        post_urn=post_urn,
        author_name=author_name,
        author_headline=author_headline,
        content=content,
        post_url=post_url,
        author_url=author_url,
        timestamp_text=timestamp_text,
        keyword_matched=keyword_matched,
        extracted_urls=extracted_urls or [],
    )


def _make_parsed(
    *,
    role: str | None = None,
    experience_min: int | None = None,
    experience_max: int | None = None,
    locations: list[str] | None = None,
    is_hiring: bool = True,
    content: str = "We are hiring.",
    keyword_matched: str = "AI Engineer",
) -> ParsedPost:
    raw = _make_raw(content=content, keyword_matched=keyword_matched)
    return ParsedPost(
        raw=raw,
        role=role,
        experience_min=experience_min,
        experience_max=experience_max,
        locations=locations or [],
        is_hiring=is_hiring,
    )


@pytest.fixture
def make_raw():
    return _make_raw


@pytest.fixture
def make_parsed():
    return _make_parsed


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    """Keep the suite hermetic.

    A real GEMINI_API_KEY in the developer's .env would otherwise make the
    pipeline tests call Gemini for every run: slow, billable, and it changes
    the scores the rule-engine assertions are written against. Tests that
    want the LLM path mock `classify_texts` and set `find_api_key` themselves,
    which still works because this only clears the default lookup.
    """
    from processing import llm_scoring

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(llm_scoring, "find_api_key", lambda: None)
