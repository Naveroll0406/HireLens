"""
Data models for the LinkedIn Job Post Monitor.

Uses Python dataclasses for lightweight, framework-free data structures.
These are used throughout the pipeline to pass structured data between stages.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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

    @property
    def content_hash(self) -> str:
        """SHA-256 hash of normalized content for deduplication."""
        import re
        normalized = self.content.lower().strip()
        # Remove all numbers to ignore changing likes, comments, and dates
        normalized = re.sub(r'\d+', '', normalized)
        # Remove common LinkedIn UI noise words that might get caught in innerText
        noise = ['likes', 'like', 'comments', 'comment', 'reposts', 'repost', 'send', 'share', 'h', 'd', 'w', 'm', 'follow', 'following', 'connect', 'message', 'see', 'more', 'and', 'others', 'reaction']
        for word in noise:
            normalized = re.sub(rf'\b{word}\b', '', normalized)
            
        author = re.sub(r'[^a-z]', '', self.author_name.lower().strip())
        
        # Remove extra whitespace and take first 200 chars to avoid trailing dynamic content
        normalized = " ".join(normalized.split())[:200]
        
        core_text = f"{author}_{normalized}"
        return hashlib.sha256(core_text.encode("utf-8")).hexdigest()


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
        """Newline-separated skills for Telegram."""
        return "\n".join(f"• {s}" for s in self.skills) if self.skills else "Not Specified"


@dataclass
class FilteredPost:
    """Post that has passed all filters and is ready for notification."""

    parsed: ParsedPost
    relevance_score: int = 0  # 0-100, used in V2 with LLM scoring
    filter_reason: str = ""  # Why it passed / what matched





@dataclass
class RunStats:
    """Statistics for a single monitor run."""

    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    keywords_searched: int = 0
    posts_found: int = 0
    new_posts: int = 0

    errors: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    def summary(self) -> str:
        return (
            f"Run completed in {self.duration_seconds:.1f}s | "
            f"Keywords: {self.keywords_searched} | "
            f"Posts found: {self.posts_found} | "
            f"New: {self.new_posts} | "
            f"Errors: {len(self.errors)}"
        )
