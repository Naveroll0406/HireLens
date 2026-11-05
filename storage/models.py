"""
Data models for the LinkedIn Job Post Monitor.

Uses Python dataclasses for lightweight, framework-free data structures.
These are used throughout the pipeline to pass structured data between stages.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Lines LinkedIn's innerText adds around a post that are not part of the
# content: reaction counts, "…more", "Like / Comment / Repost" toolbars.
_UI_NOISE_LINE = re.compile(
    r"^\s*(?:\d[\d,.]*\s*(?:k|m)?\s*)?"
    r"(?:likes?|comments?|reposts?|reactions?|send|share|follow|"
    r"…\s*more|\.\.\.\s*more|see more|show more|"
    r"like\s+comment\s+(?:repost|share)\s+send)\s*$",
    re.IGNORECASE,
)
_RELATIVE_TIME_LINE = re.compile(r"^\s*\d+\s*(?:h|d|w|mo|m|y|hr|hrs|min|mins)\b.*$", re.IGNORECASE)


@dataclass
class RawPost:
    """Raw post data as scraped from LinkedIn."""

    post_urn: str  # LinkedIn's unique post identifier (e.g., "urn:li:activity:123")
    author_name: str
    author_headline: str
    content: str  # Full text of the post
    post_url: str
    author_url: str  # Profile URL of the author
    timestamp_text: str  # Relative time like "2h", "1d", etc.
    keyword_matched: str  # Which search keyword found this post
    extracted_urls: list[str] = field(default_factory=list)  # ALL URLs scraped from <a> tags and embedded cards
    scraped_at: datetime = field(default_factory=datetime.now)
    posted_at: Optional[datetime] = None  # Absolute post time derived from timestamp_text at scrape time

    @property
    def clean_content(self) -> str:
        """Returns the content with fancy Unicode formatting normalized to standard ASCII."""
        if not self.content:
            return ""
        return unicodedata.normalize('NFKD', self.content)

    @property
    def normalized_content(self) -> str:
        """Content with LinkedIn UI chrome stripped, lower-cased, whitespace-collapsed.

        Only whole noise *lines* (reaction counts, toolbars, relative timestamps)
        are removed — digits inside the body ("2-4 years", "5 LPA") are kept so
        two different postings from the same recruiter stay distinct.
        """
        lines = []
        for line in self.clean_content.splitlines():
            if not line.strip():
                continue
            if _UI_NOISE_LINE.match(line) or _RELATIVE_TIME_LINE.match(line):
                continue
            lines.append(line)
        return " ".join(" ".join(lines).lower().split())

    @property
    def content_hash(self) -> str:
        """SHA-256 of (author, normalized content) for exact-duplicate detection."""
        author = re.sub(r"[^a-z]", "", self.author_name.lower().strip())
        core_text = f"{author}_{self.normalized_content}"
        return hashlib.sha256(core_text.encode("utf-8")).hexdigest()

    @property
    def simhash(self) -> int:
        """64-bit SimHash fingerprint for near-duplicate detection across authors."""
        from processing.simhash import simhash
        return simhash(self.normalized_content)


@dataclass
class ParsedPost:
    """Post with extracted structured information."""

    # Original raw data
    raw: RawPost

    # Extracted fields
    role: Optional[str] = None
    experience_min: Optional[int] = None
    experience_max: Optional[int] = None
    locations: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    primary_url: Optional[str] = None  # The most relevant job URL
    extracted_urls: list[str] = field(default_factory=list)  # All other found URLs
    company_url: Optional[str] = None  # Author's company page URL (fallback)
    author_url: Optional[str] = None  # Author's profile URL

    # Classification
    is_hiring: bool = False
    hiring_confidence: float = 0.0

    # Seniority flag
    is_senior_role: bool = False

    # Relevance scoring (filled in by processing.scoring)
    relevance_score: int = 0
    score_breakdown: dict[str, int] = field(default_factory=dict)
    filter_reason: str = ""

    # The rule engine's own score, kept even when an LLM overrides
    # relevance_score, so the two can be compared in the dashboard.
    rule_score: int = 0
    scored_by: str = "rules"   # "rules" | "gemini"

    @property
    def experience_str(self) -> str:
        """Human-readable experience string."""
        if self.experience_min is not None and self.experience_max is not None:
            return f"{self.experience_min}-{self.experience_max} Years"
        elif self.experience_min is not None:
            return f"{self.experience_min}+ Years"
        elif self.experience_max is not None:
            return f"0-{self.experience_max} Years"
        return "Not Specified"

    @property
    def location_str(self) -> str:
        """Comma-separated locations."""
        return ", ".join(self.locations) if self.locations else "Not Specified"

    @property
    def skills_str(self) -> str:
        """Newline-separated skills for display."""
        return "\n".join(f"• {s}" for s in self.skills) if self.skills else "Not Specified"


@dataclass
class FilteredPost:
    """Post that scored at or above the relevance threshold."""

    parsed: ParsedPost
    relevance_score: int = 0  # 0-100
    filter_reason: str = ""  # Human-readable summary of the score breakdown





@dataclass
class RunStats:
    """Statistics for a single monitor run."""

    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    keywords_searched: int = 0
    posts_found: int = 0          # raw posts scraped
    duplicates_removed: int = 0   # already-seen posts dropped by dedup
    filtered_out: int = 0         # unseen posts that failed the filters
    new_posts: int = 0            # posts that passed all filters (relevant)
    notified: int = 0             # posts pushed to Telegram
    blocked: bool = False         # LinkedIn challenged / blocked the session
    deep_scan: bool = False       # this run used the long lookback window
    scored_by: str = "rules"      # which engine scored this run's posts

    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.blocked:
            return "blocked"
        if self.errors:
            return "error"
        return "ok"

    @property
    def duration_seconds(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    def summary(self) -> str:
        return (
            f"Run completed in {self.duration_seconds:.1f}s | "
            f"Keywords: {self.keywords_searched} | "
            f"Scraped: {self.posts_found} | "
            f"Duplicates: {self.duplicates_removed} | "
            f"Filtered out: {self.filtered_out} | "
            f"New: {self.new_posts} | "
            f"Notified: {self.notified} | "
            f"Status: {self.status}"
        )
