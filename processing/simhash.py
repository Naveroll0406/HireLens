"""
SimHash near-duplicate fingerprinting.

Two posts with the same job description but a different intro line, a
different recruiter name, or a couple of edited words produce fingerprints
that differ in only a few bits. We treat a Hamming distance of
NEAR_DUPLICATE_MAX_DISTANCE or less as a *candidate* duplicate; unrelated
64-bit fingerprints differ by ~32 bits. The fingerprint can't tell "same JD,
different years" from "same JD, extra hashtag", so the Deduplicator adds a
semantic tie-break (extracted title + experience must agree).

Short posts (< MIN_TOKENS_FOR_NEAR_DUP words) produce unstable fingerprints
and are only ever matched exactly, via RawPost.content_hash.

Pure stdlib — 64-bit fingerprints built from word unigrams + bigrams.
Measured on sample posts: same JD with a different intro/hashtags → 1-7 bits,
same JD with a changed experience range → 6, changed title → 4, unrelated → ~30.
"""

from __future__ import annotations

import hashlib
import re

NEAR_DUPLICATE_MAX_DISTANCE = 8
MIN_TOKENS_FOR_NEAR_DUP = 40
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def simhash(text: str) -> int:
    """Return a 64-bit SimHash of the text.

    Returns 0 (= "no fingerprint") for empty or very short text so callers
    never near-match on a handful of words.
    """
    tokens = _tokens(text)
    if len(tokens) < MIN_TOKENS_FOR_NEAR_DUP:
        return 0

    features = tokens + [f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)]

    weights = [0] * 64
    for feature in features:
        h = int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            if (h >> bit) & 1:
                weights[bit] += 1
            else:
                weights[bit] -= 1

    fingerprint = 0
    for bit, w in enumerate(weights):
        if w > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def is_near_duplicate(a: int, b: int, max_distance: int = NEAR_DUPLICATE_MAX_DISTANCE) -> bool:
    """True when two fingerprints are within max_distance bits of each other.

    A fingerprint of 0 means "no content" and never matches anything.
    """
    if a == 0 or b == 0:
        return False
    return hamming_distance(a, b) <= max_distance
