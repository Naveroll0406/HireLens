"""
Deduplication engine for the LinkedIn Job Post Monitor.

Three layers, cheapest first:
1. Post URN — LinkedIn's own id (exact).
2. (author, content_hash) — same recruiter, same text minus UI chrome (exact).
3. SimHash — same job description cross-posted by different recruiters or
   lightly edited (near match, see processing.simhash), confirmed by a
   semantic tie-break: the extracted title and experience range must not
   contradict each other, so "AI Engineer 2-4 yrs" and "AI Engineer 5-7 yrs"
   with the same boilerplate stay separate.
"""

from __future__ import annotations

import logging

from processing.parser import extract_experience, extract_role, normalize_unicode
from processing.simhash import NEAR_DUPLICATE_MAX_DISTANCE, is_near_duplicate
from storage.database import Database
from storage.models import RawPost

logger = logging.getLogger(__name__)

Signature = tuple[str | None, int | None, int | None]


def _signature(post: RawPost) -> Signature:
    """(title, exp_min, exp_max) — the fields that distinguish two near-identical JDs."""
    content = normalize_unicode(post.content or "")
    role = extract_role(content, normalize_unicode(post.author_headline or ""))
    exp_min, exp_max = extract_experience(content)
    return (role.lower() if role else None, exp_min, exp_max)


def _compatible(a: Signature, b: Signature) -> bool:
    """Signatures agree when every field is equal or unknown on either side."""
    return all(x is None or y is None or x == y for x, y in zip(a, b))


class Deduplicator:
    """Checks posts against the database (and each other) to find unseen posts."""

    def __init__(self, db: Database, near_duplicate_distance: int = NEAR_DUPLICATE_MAX_DISTANCE):
        self.db = db
        self.near_duplicate_distance = near_duplicate_distance

    def filter_new_posts(self, posts: list[RawPost]) -> list[RawPost]:
        """Return only posts that are truly new, in their original order."""
        new_posts: list[RawPost] = []
        seen_urns: set[str] = set()
        seen_hashes: set[tuple[str, str]] = set()
        seen_fingerprints: list[tuple[int, Signature]] = []
        removed = {"urn": 0, "hash": 0, "near": 0, "db": 0, "db_near": 0}

        for post in posts:
            urn = post.post_urn or ""
            label = urn[:30] if urn else "no-urn"
            content_hash = post.content_hash
            author = post.author_name or ""
            fingerprint = post.simhash
            signature: Signature = _signature(post) if fingerprint else (None, None, None)

            def remember(urn=urn, content_hash=content_hash, author=author,
                         fingerprint=fingerprint, signature=signature) -> None:
                if urn:
                    seen_urns.add(urn)
                seen_hashes.add((content_hash, author))
                if fingerprint:
                    seen_fingerprints.append((fingerprint, signature))

            # --- within this batch ---
            if urn and urn in seen_urns:
                removed["urn"] += 1
                logger.debug("dup (batch urn): %s", label)
                continue
            if (content_hash, author) in seen_hashes:
                removed["hash"] += 1
                logger.debug("dup (batch hash): %s", label)
                continue
            if fingerprint and any(
                is_near_duplicate(fingerprint, fp, self.near_duplicate_distance) and _compatible(signature, sig)
                for fp, sig in seen_fingerprints
            ):
                removed["near"] += 1
                logger.info("dup (batch near-duplicate): %s by %s", label, author or "?")
                remember()
                continue

            # --- against the database ---
            if self.db.is_duplicate(urn, content_hash, author):
                removed["db"] += 1
                logger.debug("dup (db): %s", label)
                remember()
                continue
            if fingerprint:
                match = next(
                    (
                        m for m in self.db.find_near_duplicates(fingerprint, max_distance=self.near_duplicate_distance)
                        if _compatible(signature, ((m["role"] or "").lower() or None,
                                                   m["experience_min"], m["experience_max"]))
                    ),
                    None,
                )
                if match is not None:
                    removed["db_near"] += 1
                    logger.info("dup (db near-duplicate of post #%d): %s by %s", match["id"], label, author or "?")
                    remember()
                    continue

            new_posts.append(post)
            remember()

        logger.info(
            "Deduplication: %d input → %d new (removed %d: urn=%d hash=%d near=%d db=%d db_near=%d)",
            len(posts), len(new_posts), len(posts) - len(new_posts),
            removed["urn"], removed["hash"], removed["near"], removed["db"], removed["db_near"],
        )
        return new_posts
