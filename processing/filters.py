"""
Post filters for the LinkedIn Job Post Monitor.

The individual ``filter_by_*`` checks are still exposed (they're useful for
explaining a post and in tests), but the pipeline no longer chains them as
hard gates. ``apply_all_filters`` scores the post (see processing.scoring)
and accepts it when the score clears the threshold, so one wrong regex
lowers a score instead of silently deleting a good post.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import config
from processing.scoring import score_post
from storage.models import FilteredPost, ParsedPost

logger = logging.getLogger(__name__)

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


def filter_by_experience(parsed: ParsedPost,
                         user_min: int | None = None,
                         user_max: int | None = None) -> tuple[bool, str]:
    """Check if the post's experience requirement overlaps with the user's range.

    - No experience mentioned → ACCEPT (don't miss opportunities)
    - Range overlaps [user_min, user_max] → ACCEPT
    - Minimum clearly above the max → REJECT
    """
    if user_min is None:
        user_min = config.EXPERIENCE_MIN
    if user_max is None:
        user_max = config.EXPERIENCE_MAX

    post_min, post_max = parsed.experience_min, parsed.experience_max

    if post_min is None and post_max is None:
        return (True, "No experience mentioned — accepted by default")

    if post_min is not None and post_max is not None:
        if post_min <= user_max and post_max >= user_min:
            return (True, f"Experience {post_min}-{post_max}y overlaps with {user_min}-{user_max}y")
        return (False, f"Experience {post_min}-{post_max}y outside range {user_min}-{user_max}y")

    if post_min is not None:
        if post_min <= user_max:
            return (True, f"Minimum {post_min}y within range")
        return (False, f"Minimum {post_min}y exceeds max {user_max}y")

    if post_max >= user_min:
        return (True, f"Maximum {post_max}y within range")
    return (False, f"Maximum {post_max}y below min {user_min}y")


def filter_by_location(parsed: ParsedPost,
                       target_locations: list[str] | None = None) -> tuple[bool, str]:
    """Accept if no location is mentioned, or any mentioned location is a target."""
    if not parsed.locations:
        return (True, "No location mentioned — accepted by default")

    locs_to_check = target_locations if target_locations is not None else list(config.TARGET_LOCATIONS)
    matching = {loc.lower() for loc in parsed.locations} & {loc.lower() for loc in locs_to_check}
    if matching:
        return (True, f"Location match: {', '.join(sorted(matching))}")
    return (False, f"Locations {parsed.locations} not in target list")


def filter_by_hiring_signal(parsed: ParsedPost) -> tuple[bool, str]:
    """Is this actually a hiring post vs. discussion/news?"""
    if parsed.is_hiring:
        return (True, f"Hiring signal detected (confidence: {parsed.hiring_confidence:.0%})")
    return (False, "No hiring signals detected")


def filter_by_ai_role(parsed: ParsedPost) -> tuple[bool, str]:
    """Is the post for an AI/ML role (as opposed to QA, Backend, Java-only ...)?

    - Non-AI title without an AI keyword in it → REJECT
    - Title matches AI_ROLE_KEYWORDS → ACCEPT
    - Search keyword appears in title/body → ACCEPT
    - Generic/absent title but strong AI keyword in body → ACCEPT
    """
    content = parsed.raw.clean_content or ""
    role = parsed.role or ""

    if role and _NON_AI_TITLE_RE.search(role) and not _AI_TITLE_RE.search(role):
        return (False, f"Role '{role}' explicitly rejected (non-AI specialization)")

    m = _AI_TITLE_RE.search(role) if role else None
    if m:
        return (True, f"Role '{role}' matches AI keyword '{m.group(0)}'")

    keyword = (parsed.raw.keyword_matched or "").lower()
    if keyword and keyword != "direct_url":
        base_keyword = keyword
        for loc in config.TARGET_LOCATIONS:
            base_keyword = re.sub(r"\b" + re.escape(loc.lower()) + r"\b", "", base_keyword)
        base_keyword = " ".join(base_keyword.split())
        if base_keyword and re.search(r"\b" + re.escape(base_keyword) + r"\b", role + " " + content, re.IGNORECASE):
            return (True, f"Content/Role contains search keyword '{base_keyword}'")

    m = _STRONG_AI_RE.search(content)
    if m:
        return (True, f"Role '{role or 'unknown'}' but content has AI skill '{m.group(0)}'")

    return (False, f"Role '{role or 'unknown'}' and content do not meet AI criteria")


def apply_all_filters(parsed: ParsedPost,
                      target_locations: list[str] | None = None,
                      experience_range: tuple[int, int] | None = None,
                      threshold: int | None = None,
                      rescore: bool = True,
                      ) -> Optional[FilteredPost]:
    """Score the post and return a FilteredPost if it clears the threshold.

    The score and its breakdown are always written onto ``parsed`` (and later
    persisted), so rejected posts can be inspected and the weights tuned.
    """
    if threshold is None:
        threshold = config.RELEVANCE_THRESHOLD

    # rescore=False is used after an LLM pass has already set the score, so
    # the rule engine does not overwrite the model's judgement.
    if rescore:
        score_post(parsed, target_locations=target_locations, experience_range=experience_range)
    urn = parsed.raw.post_urn[:30] if parsed.raw.post_urn else "no-urn"

    if parsed.relevance_score < threshold:
        logger.info("REJECTED (score %d < %d): %s — %s", parsed.relevance_score, threshold, urn, parsed.filter_reason)
        return None

    logger.info(
        "ACCEPTED (score %d): [%s] %s — %s | %s | %s",
        parsed.relevance_score, urn, parsed.role or "Unknown Role",
        parsed.experience_str, parsed.location_str, parsed.filter_reason,
    )
    return FilteredPost(
        parsed=parsed,
        relevance_score=parsed.relevance_score,
        filter_reason=parsed.filter_reason,
    )
