"""
Deduplication engine for the LinkedIn Job Post Monitor.

Prevents duplicate notifications by checking posts against the database
using both post URN (ID) and content hash matching.
"""

from __future__ import annotations

import logging

from storage.database import Database
from storage.models import RawPost

logger = logging.getLogger(__name__)


class Deduplicator:
    """Checks posts against the database to identify new (unseen) posts."""

    def __init__(self, db: Database):
        self.db = db

    def filter_new_posts(self, posts: list[RawPost]) -> list[RawPost]:
        """Filter out posts that already exist in the database.

        Uses dual-check:
        1. Post URN matching (LinkedIn's unique identifier)
        2. Content hash matching (catches reposts / URN changes)

        Returns only posts that are truly new.
        """
        new_posts: list[RawPost] = []
        seen_urns_this_batch: set[str] = set()
        seen_hashes_this_batch: set[tuple[str, str]] = set()

        for post in posts:
            # Skip within-batch duplicates (same post from different keyword searches)
            if post.post_urn and post.post_urn in seen_urns_this_batch:
                logger.info("REJECTED (deduplication - batch URN dup): %s", post.post_urn[:30])
                continue

            content_hash = post.content_hash
            author_name = post.author_name or ""
            
            if (content_hash, author_name) in seen_hashes_this_batch:
                logger.info("REJECTED (deduplication - batch hash dup): %s", post.post_urn[:30] if post.post_urn else "no-urn")
                continue

            # Check against database (use content_hash if no URN)
            urn_for_check = post.post_urn or ""
            if self.db.is_duplicate(urn_for_check, content_hash, author_name):
                logger.info("REJECTED (deduplication - DB dup): %s", post.post_urn[:30] if post.post_urn else "no-urn")
                if post.post_urn:
                    seen_urns_this_batch.add(post.post_urn)
                seen_hashes_this_batch.add((content_hash, author_name))
                continue

            # Truly new post
            new_posts.append(post)
            if post.post_urn:
                seen_urns_this_batch.add(post.post_urn)
            seen_hashes_this_batch.add((content_hash, author_name))

        logger.info(
            "Deduplication: %d input → %d new (removed %d duplicates)",
            len(posts),
            len(new_posts),
            len(posts) - len(new_posts),
        )

        return new_posts
