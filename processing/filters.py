"""
Post filters for the LinkedIn Job Post Monitor.

Applies experience, location, seniority, and hiring-signal filters
to parsed posts. Posts that pass all filters become notification candidates.
"""

from __future__ import annotations

import logging
from typing import Optional

import config

from storage.models import FilteredPost, ParsedPost

logger = logging.getLogger(__name__)


def filter_by_experience(parsed: ParsedPost,
                         user_min: int | None = None,
                         user_max: int | None = None) -> tuple[bool, str]:
    """Check if the post's experience requirement overlaps with the user's range.

    Rules:
    - If no experience is mentioned → ACCEPT (don't miss opportunities)
    - If experience overlaps with [user_min, user_max] → ACCEPT
    - If experience is clearly above the max → REJECT
    """
    if user_min is None:
        user_min = config.EXPERIENCE_MIN
    if user_max is None:
        user_max = config.EXPERIENCE_MAX

    post_min = parsed.experience_min
    post_max = parsed.experience_max

    # No experience mentioned → accept
    if post_min is None and post_max is None:
        return (True, "No experience mentioned — accepted by default")

    # Post has a range (e.g., 2-4 years)
    if post_min is not None and post_max is not None:
        # Check overlap: post range [post_min, post_max] overlaps with [user_min, user_max]
        if post_min <= user_max and post_max >= user_min:
            return (True, f"Experience {post_min}-{post_max}y overlaps with {user_min}-{user_max}y")
        else:
            return (False, f"Experience {post_min}-{post_max}y outside range {user_min}-{user_max}y")

    # Post has only minimum (e.g., "3+ years")
    if post_min is not None:
        if post_min <= user_max:
            return (True, f"Minimum {post_min}y within range")
        else:
            return (False, f"Minimum {post_min}y exceeds max {user_max}y")

    # Post has only maximum (rare, e.g., "up to 2 years")
    if post_max is not None:
        if post_max >= user_min:
            return (True, f"Maximum {post_max}y within range")
        else:
            return (False, f"Maximum {post_max}y below min {user_min}y")

    return (True, "Experience check passed")


def filter_by_location(parsed: ParsedPost,
                       target_locations: list[str] | None = None) -> tuple[bool, str]:
    """Check if the post mentions any target location.

    Rules:
    - If no location is mentioned → ACCEPT (don't miss remote/unlisted)
    - If any target location matches → ACCEPT
    - If locations are mentioned but none match → REJECT
    """
    if not parsed.locations:
        return (True, "No location mentioned — accepted by default")

    locs_to_check = target_locations if target_locations is not None else list(config.TARGET_LOCATIONS)
    target_set = {loc.lower() for loc in locs_to_check}
    post_locations = {loc.lower() for loc in parsed.locations}

    matching = post_locations & target_set
    if matching:
        matched_str = ", ".join(matching)
        return (True, f"Location match: {matched_str}")

    return (False, f"Locations {parsed.locations} not in target list")


def filter_by_seniority(parsed: ParsedPost) -> tuple[bool, str]:
    """Reject posts that are clearly for senior positions.

    Rules:
    - If the role title contains senior keywords AND experience ≥ 5 → REJECT
    - If just senior in title but experience is within range → ACCEPT (could be title inflation)
    - Default → ACCEPT
    """
    if not parsed.is_senior_role:
        return (True, "Not a senior role")

    # Senior title + high experience → reject
    if parsed.experience_min is not None and parsed.experience_min >= 5:
        return (False, f"Senior role with {parsed.experience_min}+ years required")

    # Senior title but experience within range or not specified → accept with note
    return (True, "Senior title but experience may be within range")


def filter_by_hiring_signal(parsed: ParsedPost) -> tuple[bool, str]:
    """Check if the post is actually a hiring post vs. discussion/news.

    Rules:
    - Must have at least one hiring signal keyword
    - Low confidence → still accept (err on the side of inclusion)
    """
    if parsed.is_hiring:
        return (True, f"Hiring signal detected (confidence: {parsed.hiring_confidence:.0%})")

    return (False, "No hiring signals detected")


def filter_by_ai_role(parsed: ParsedPost) -> tuple[bool, str]:
    """Check if the post is strictly for an AI/ML role, rejecting QA, Backend, etc.

    Rules:
    - If the role contains non-AI specializations (Java, QA, Data Engineer, etc.) without explicitly mentioning AI in the role → REJECT
    - If the extracted role matches any keyword in AI_ROLE_KEYWORDS → ACCEPT
    - If the original search keyword (keyword_matched) is in the role or content → ACCEPT
    - If the role is generic (Software Engineer, Developer) and content has AI skills → ACCEPT
    - Otherwise → REJECT
    """
    content_lower = parsed.raw.content.lower() if parsed.raw.content else ""
    role_lower = parsed.role.lower() if parsed.role else ""

    # 0. Explicit Reject List for non-AI specializations
    reject_roles = [
        "data engineer", "java", "backend", "front-end", "frontend", "fullstack", "full-stack",
        "qa", "quality assurance", "devops", "ios", "android", "react", "angular",
        "c++", "c#", ".net", "php", "ruby", "sales", "marketing", "hr", "recruiter",
        "scrum master", "agile coach", "project manager"
    ]
    
    has_rejected_specialization = any(r in role_lower.split() or r in role_lower for r in reject_roles)
    has_ai_keyword_in_role = any(kw.lower() in role_lower for kw in config.AI_ROLE_KEYWORDS)
    
    if has_rejected_specialization and not has_ai_keyword_in_role:
        return (False, f"Role '{parsed.role}' is for a non-AI specialization")

    # 1. Direct match with AI_ROLE_KEYWORDS
    for keyword in config.AI_ROLE_KEYWORDS:
        kw_lower = keyword.lower()
        if kw_lower in role_lower:
            return (True, f"Role '{parsed.role}' matches AI keyword '{keyword}'")

    # 2. Match with the search keyword that found this post
    keyword_matched = parsed.raw.keyword_matched.lower() if parsed.raw.keyword_matched else ""
    if keyword_matched and keyword_matched != "direct_url":
        # Remove location from keyword if present (e.g., 'ai engineer pune' -> 'ai engineer')
        base_keyword = keyword_matched
        for loc in config.TARGET_LOCATIONS:
            if loc.lower() in base_keyword:
                base_keyword = base_keyword.replace(loc.lower(), "").strip()
                
        if base_keyword and (base_keyword in role_lower or base_keyword in content_lower):
            return (True, f"Content/Role contains search keyword '{base_keyword}'")

    # 3. Generic role + AI content
    generic_roles = ["software engineer", "developer", "data scientist", "researcher", "engineer", "architect", "programmer"]
    is_generic_role = any(r in role_lower for r in generic_roles) or not role_lower
    
    if is_generic_role:
        strong_ai_keywords = ["llm", "langchain", "rag", "generative ai", "genai", "prompt engineering", "openai", "machine learning"]
        for kw in strong_ai_keywords:
            if kw in content_lower:
                return (True, f"Generic role '{parsed.role}' but content has AI skill '{kw}'")

    return (False, f"Role '{parsed.role}' and content do not meet AI criteria")


def apply_all_filters(parsed: ParsedPost,
                      target_locations: list[str] | None = None,
                      experience_range: tuple[int, int] | None = None,
                      ) -> Optional[FilteredPost]:
    """Apply all filters to a parsed post.

    Returns a FilteredPost if all filters pass, None otherwise.
    Filter order: hiring signal → experience → location → seniority.

    Optional overrides:
      target_locations — list of location strings to accept.
      experience_range — (min, max) years of experience.
    """

    # Filter 1: Is this strictly an AI/ML role?
    passed, reason = filter_by_ai_role(parsed)
    if not passed:
        logger.info("REJECTED (non-AI role): %s — %s", parsed.raw.post_urn[:30] if parsed.raw.post_urn else "no-urn", reason)
        return None

    # Filter 2: Is this actually a hiring post?
    passed, reason = filter_by_hiring_signal(parsed)
    if not passed:
        logger.info("REJECTED (hiring signal): %s — %s", parsed.raw.post_urn[:30] if parsed.raw.post_urn else "no-urn", reason)
        return None

    # Filter 3: Experience range check
    exp_min = experience_range[0] if experience_range else None
    exp_max = experience_range[1] if experience_range else None
    passed, reason = filter_by_experience(parsed, user_min=exp_min, user_max=exp_max)
    if not passed:
        logger.info("REJECTED (experience): %s — %s", parsed.raw.post_urn[:30] if parsed.raw.post_urn else "no-urn", reason)
        return None

    # Filter 4: Location check
    passed, reason = filter_by_location(parsed, target_locations=target_locations)
    if not passed:
        logger.info("REJECTED (location): %s — %s", parsed.raw.post_urn[:30] if parsed.raw.post_urn else "no-urn", reason)
        return None

    # Filter 5: Seniority check
    passed, reason = filter_by_seniority(parsed)
    if not passed:
        logger.info("REJECTED (seniority): %s — %s", parsed.raw.post_urn[:30] if parsed.raw.post_urn else "no-urn", reason)
        return None

    logger.info(
        "ACCEPTED: [%s] %s — %s | %s | %s",
        parsed.raw.post_urn[:30],
        parsed.role or "Unknown Role",
        parsed.experience_str,
        parsed.location_str,
        reason,
    )

    return FilteredPost(
        parsed=parsed,
        filter_reason=reason,
    )
