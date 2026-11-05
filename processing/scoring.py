"""
Relevance scoring for parsed posts.

Replaces the old chain of yes/no gates with a 0-100 score built from
additive signals (weights live in config.SCORE_WEIGHTS). Every signal that
fires is recorded in ``ParsedPost.score_breakdown`` so a misfire can be
explained from the dashboard instead of guessed at.

The score is the *only* thing the pipeline uses to decide whether a post is
shown; the threshold is config.RELEVANCE_THRESHOLD (overridable per run).
"""

from __future__ import annotations

import re

import config
from storage.models import ParsedPost

_NON_AI_TITLE_RE = re.compile(
    "|".join(r"\b" + re.escape(t.strip()) + r"\b" for t in config.NON_AI_ROLE_TITLES),
    re.IGNORECASE,
)
_AI_TITLE_RE = re.compile(
    "|".join(r"\b" + re.escape(t) + r"\b" for t in config.AI_ROLE_KEYWORDS),
    re.IGNORECASE,
)
_STRONG_AI_RE = re.compile(
    "|".join(r"\b" + re.escape(t) + r"\b" for t in config.STRONG_AI_KEYWORDS),
    re.IGNORECASE,
)
_GENERIC_TITLE_RE = re.compile(
    r"\b(?:software engineer|developer|engineer|architect|programmer|researcher|scientist)\b",
    re.IGNORECASE,
)


def _strip_locations(keyword: str) -> str:
    """'ai engineer pune' -> 'ai engineer' so the keyword-hit check isn't location-bound."""
    base = keyword.lower()
    for loc in config.TARGET_LOCATIONS:
        base = re.sub(r"\b" + re.escape(loc.lower()) + r"\b", "", base)
    return " ".join(base.split())


def score_post(parsed: ParsedPost,
               target_locations: list[str] | None = None,
               experience_range: tuple[int, int] | None = None) -> ParsedPost:
    """Compute relevance_score / score_breakdown / filter_reason in place and return the post."""
    w = config.SCORE_WEIGHTS
    breakdown: dict[str, int] = {}
    content = parsed.raw.clean_content or ""
    role = parsed.role or ""
    user_min, user_max = experience_range or (config.EXPERIENCE_MIN, config.EXPERIENCE_MAX)
    targets = {loc.lower() for loc in (target_locations if target_locations is not None else config.TARGET_LOCATIONS)}

    # --- Is it a job post at all? ---------------------------------------
    if not parsed.is_hiring and parsed.hiring_confidence == 0.0:
        # detect_hiring_signal returns (False, 0.0) for absolute rejects *and*
        # for "no signal"; distinguish by re-checking the kill list.
        from processing.parser import _ABSOLUTE_REJECT_RE  # noqa: PLC0415
        if _ABSOLUTE_REJECT_RE.search(content):
            breakdown["absolute_reject"] = w["absolute_reject"]
        else:
            breakdown["no_hiring_signal"] = w["no_hiring_signal"]
    elif not parsed.is_hiring:
        breakdown["no_hiring_signal"] = w["no_hiring_signal"]
    elif parsed.hiring_confidence >= 0.6:
        breakdown["hiring_signal_strong"] = w["hiring_signal_strong"]
    else:
        breakdown["hiring_signal_weak"] = w["hiring_signal_weak"]

    # --- Is it an AI role? ----------------------------------------------
    ai_in_title = bool(role and _AI_TITLE_RE.search(role))
    non_ai_title = bool(role and _NON_AI_TITLE_RE.search(role))
    strong_ai_in_body = bool(_STRONG_AI_RE.search(content))

    if ai_in_title:
        breakdown["ai_role_in_title"] = w["ai_role_in_title"]
    elif non_ai_title:
        breakdown["non_ai_role"] = w["non_ai_role"]

    if strong_ai_in_body:
        breakdown["strong_ai_skill"] = w["strong_ai_skill"]
    elif not ai_in_title and (not role or _GENERIC_TITLE_RE.search(role)):
        breakdown["generic_role_no_ai"] = w["generic_role_no_ai"]

    keyword = parsed.raw.keyword_matched or ""
    if keyword and keyword != "direct_url":
        base_kw = _strip_locations(keyword)
        if base_kw and re.search(r"\b" + re.escape(base_kw) + r"\b", role + " " + content, re.IGNORECASE):
            breakdown["search_keyword_hit"] = w["search_keyword_hit"]

    # --- Location -------------------------------------------------------
    if parsed.locations:
        if {loc.lower() for loc in parsed.locations} & targets:
            breakdown["location_match"] = w["location_match"]
        else:
            breakdown["location_mismatch"] = w["location_mismatch"]

    # --- Experience -----------------------------------------------------
    pmin, pmax = parsed.experience_min, parsed.experience_max
    if pmin is not None and pmin > user_max:
        breakdown["experience_too_high"] = w["experience_too_high"]
    elif pmin is not None or pmax is not None:
        lo = pmin if pmin is not None else 0
        hi = pmax if pmax is not None else 99
        if lo <= user_max and hi >= user_min:
            breakdown["experience_overlap"] = w["experience_overlap"]

    # --- Actionability --------------------------------------------------
    if parsed.primary_url or parsed.extracted_urls:
        breakdown["has_apply_url"] = w["has_apply_url"]
    if parsed.emails:
        breakdown["has_email"] = w["has_email"]

    # --- Seniority (soft penalty, no longer a gate) ---------------------
    if parsed.is_senior_role:
        breakdown["senior_title"] = w["senior_title"]

    score = max(0, min(100, sum(breakdown.values())))
    parsed.relevance_score = score
    parsed.score_breakdown = breakdown
    parsed.filter_reason = format_breakdown(breakdown)
    return parsed


def format_breakdown(breakdown: dict[str, int]) -> str:
    """'ai_role_in_title +40, location_match +15, senior_title -25'."""
    parts = sorted(breakdown.items(), key=lambda kv: -abs(kv[1]))
    return ", ".join(f"{name} {value:+d}" for name, value in parts)
