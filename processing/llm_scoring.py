"""
Optional LLM relevance scoring via the Gemini API.

The rule engine in :mod:`processing.scoring` is still the baseline and still
runs on every post.  When a Gemini API key is configured, this module runs a
second pass that *overrides* the score with the model's judgement, which
catches things regex cannot: that "Aspiring Software Engineer | 450+ DSA
problems" is someone's headline rather than a vacancy, or that a post listing
six unrelated roles is only partly relevant.

Design rules:
  * Never fatal.  Any failure - missing key, bad JSON, HTTP error, timeout -
    leaves the rule score untouched and the run continues.  The pipeline must
    work offline and with no key at all.
  * The rule score is always kept in ``ParsedPost.rule_score`` so the two
    engines can be compared in the dashboard.
  * Standard library only, matching the rest of the project (no SDK pulled in
    for one HTTP call).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import config
from storage.models import ParsedPost

logger = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta"
KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
DEFAULT_MODEL = getattr(config, "LLM_MODEL", "gemini-2.5-flash")
BATCH_SIZE = getattr(config, "LLM_BATCH_SIZE", 6)
CONTENT_CHARS = getattr(config, "LLM_CONTENT_CHARS", 1500)
TIMEOUT = getattr(config, "LLM_TIMEOUT_SECONDS", 90)
DEFAULT_PROFILE = getattr(
    config, "CANDIDATE_PROFILE",
    "AI, GenAI, LLM, RAG, MLOps, Machine Learning and Data Science engineering roles.")


# ---------------------------------------------------------------------------
# Key discovery
# ---------------------------------------------------------------------------

def _parse_env_file(path: Path) -> dict[str, str]:
    """Read a .env file, tolerating the shell syntax people paste into them."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        stripped = re.sub(r"^export\s+", "", stripped)
        stripped = re.sub(r"^\$env:", "", stripped)              # PowerShell
        stripped = re.sub(r"^set\s+", "", stripped, flags=re.I)  # cmd
        name, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name.strip():
            values[name.strip()] = value.strip()
    return values


def find_api_key() -> str | None:
    """The Gemini key from the environment, else from the project's .env."""
    for name in KEY_NAMES:
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip().strip("\"'").strip()
    root = Path(__file__).resolve().parent.parent
    for path in (root / ".env", Path.cwd() / ".env"):
        if path.is_file():
            values = _parse_env_file(path)
            for name in KEY_NAMES:
                if values.get(name):
                    return values[name]
    return None


def is_configured() -> bool:
    """Whether a key exists at all.  Does not make a network call."""
    return find_api_key() is not None


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class LLMError(RuntimeError):
    """Any failure talking to Gemini.  Always caught by the caller."""


def _post(model: str, key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent", data=data, method="POST")
    # Header auth, not ?key= - query strings leak into logs and history.
    req.add_header("x-goog-api-key", key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as err:
        try:
            detail = json.loads(err.read().decode("utf-8")).get("error", {})
            message = detail.get("message", "")
        except (ValueError, AttributeError):
            message = ""
        raise LLMError(f"HTTP {err.code}: {message or err.reason}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise LLMError(f"network: {err}") from None


def check_key(key: str | None = None, model: str | None = None) -> tuple[bool, str]:
    """(works, message) - a cheap round trip used by the dashboard badge."""
    key = key or find_api_key()
    if not key:
        return False, "No GEMINI_API_KEY found in the environment or .env"
    req = urllib.request.Request(f"{BASE}/models")
    req.add_header("x-goog-api-key", key)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as err:
        return False, f"Key rejected (HTTP {err.code})"
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return False, f"Could not reach Google: {err}"
    usable = [m for m in body.get("models", [])
              if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if not usable:
        return False, "Key works but no model allows generateContent"
    return True, f"{len(usable)} models available"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    """One post's judgement from the model."""
    index: int
    is_hiring: bool
    score: int
    role: str = ""
    reason: str = ""


_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "index": {"type": "INTEGER"},
            "is_hiring": {"type": "BOOLEAN"},
            "relevance": {"type": "INTEGER"},
            "role": {"type": "STRING"},
            "reason": {"type": "STRING"},
        },
        "required": ["index", "is_hiring", "relevance", "reason"],
    },
}


def _prompt(items: list[tuple[str, str]], targets: list[str],
            exp_range: tuple[int, int], profile: str | None = None) -> str:
    """Build the batch prompt from (author, content) pairs.

    *profile* is the user's own description of what they are looking for; it
    is what the relevance score is measured against, so the more specific it
    is the sharper the filtering.
    """
    lines = [
        "You are screening LinkedIn posts for a job seeker.",
        "",
        "THE CANDIDATE:",
        # A whitespace-only profile is truthy, so strip before falling back -
        # otherwise the candidate section comes out empty and the model has
        # nothing to score against.
        (profile or "").strip() or DEFAULT_PROFILE.strip(),
        "",
        f"Preferred locations: {', '.join(targets) if targets else 'any'}.",
        f"Experience range: {exp_range[0]}-{exp_range[1]} years.",
        "",
        "For EACH post, decide:",
        "  is_hiring  - true only if it advertises a real, currently open vacancy.",
        "               Career advice, course ads, 'I am looking for work' posts,",
        "               webinars, hiring-process commentary and someone's own",
        "               profile headline are NOT vacancies.",
        "  relevance  - 0-100 for how well it fits the candidate above.",
        "               0-30 irrelevant, not a vacancy, or a role the candidate",
        "               said they do not want. 40-60 adjacent or vague. 70-90 a",
        "               solid match. 90+ an excellent match on role, location",
        "               and experience.",
        "               Score against THE CANDIDATE above, not against AI roles",
        "               in general.",
        "  role       - the actual job title, cleaned up. Empty if not a vacancy.",
        "  reason     - one short clause (max 15 words) explaining the score.",
        "",
        "Return one object per post, echoing its index. Judge only what the text",
        "supports; do not invent details.",
        "",
    ]
    for i, (author, content) in enumerate(items):
        lines.append(f"--- POST {i} ---")
        if author:
            lines.append(f"Author: {author}")
        lines.append((content or "")[:CONTENT_CHARS].strip())
        lines.append("")
    return "\n".join(lines)


def _parse_verdicts(raw: dict) -> list[Verdict]:
    """Pull the JSON array out of a Gemini response."""
    candidate = (raw.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = next((p["text"] for p in parts if p.get("text")), "")
    if not text.strip():
        reason = candidate.get("finishReason", "unknown")
        raise LLMError(f"empty response (finishReason={reason})")
    try:
        data = json.loads(text)
    except ValueError:
        raise LLMError("response was not valid JSON") from None
    if not isinstance(data, list):
        raise LLMError("response was not a JSON array")

    out = []
    for item in data:
        if not isinstance(item, dict) or "index" not in item:
            continue
        try:
            out.append(Verdict(
                index=int(item["index"]),
                is_hiring=bool(item.get("is_hiring", False)),
                score=max(0, min(100, int(item.get("relevance", 0)))),
                role=str(item.get("role") or "").strip(),
                reason=str(item.get("reason") or "").strip(),
            ))
        except (TypeError, ValueError):
            continue
    return out


def classify_texts(items: list[tuple[str, str]], key: str, model: str,
                   targets: list[str], exp_range: tuple[int, int],
                   profile: str | None = None) -> list[Verdict]:
    """Judge one batch of (author, content) pairs.  Raises LLMError on failure.

    Taking raw text rather than ParsedPost lets the dashboard re-score rows
    that are already in the database, where only the stored columns exist.
    """
    response = _post(model, key, {
        "contents": [{"parts": [{"text": _prompt(items, targets, exp_range, profile)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
            "temperature": 0,
            # 2.5 models spend output tokens thinking before they answer.
            "maxOutputTokens": 8192,
        },
    })
    return _parse_verdicts(response)


def apply(parsed_posts: list[ParsedPost],
          target_locations: list[str] | None = None,
          experience_range: tuple[int, int] | None = None,
          model: str | None = None,
          key: str | None = None,
          profile: str | None = None) -> tuple[str, str]:
    """Override rule scores with Gemini's judgement, in place.

    Returns ``(engine, detail)`` where engine is "gemini", "gemini-partial"
    or "rules".  The caller does not need to handle exceptions: a failure
    simply leaves every rule score as it was.
    """
    for parsed in parsed_posts:
        parsed.rule_score = parsed.relevance_score
        parsed.scored_by = "rules"

    if not parsed_posts:
        return "rules", "nothing to score"

    key = key or find_api_key()
    if not key:
        return "rules", "no API key configured"
    model = model or DEFAULT_MODEL
    targets = list(target_locations if target_locations is not None
                   else config.TARGET_LOCATIONS)
    exp_range = experience_range or (config.EXPERIENCE_MIN, config.EXPERIENCE_MAX)

    scored = 0
    failures: list[str] = []
    for start in range(0, len(parsed_posts), BATCH_SIZE):
        batch = parsed_posts[start:start + BATCH_SIZE]
        items = [(p.raw.author_name or "",
                  p.raw.clean_content or p.raw.content or "") for p in batch]
        try:
            verdicts = classify_texts(items, key, model, targets, exp_range, profile)
        except LLMError as err:
            logger.warning("Gemini batch %d failed, keeping rule scores: %s",
                           start // BATCH_SIZE, err)
            failures.append(str(err))
            continue

        for verdict in verdicts:
            if not 0 <= verdict.index < len(batch):
                continue
            parsed = batch[verdict.index]
            parsed.relevance_score = verdict.score
            parsed.scored_by = "gemini"
            parsed.filter_reason = (
                f"gemini: {verdict.reason}" if verdict.reason else "gemini")
            # The model's title is usually cleaner than the regex's, but never
            # let it blank out a title the parser did find.
            if verdict.role:
                parsed.role = verdict.role
            if not verdict.is_hiring:
                # Not a vacancy at all - force it below any sane threshold.
                parsed.relevance_score = min(parsed.relevance_score, 20)
            scored += 1

    if scored == 0:
        return "rules", failures[0] if failures else "no verdicts returned"
    if scored < len(parsed_posts):
        return "gemini-partial", f"{scored}/{len(parsed_posts)} scored by Gemini"
    return "gemini", f"{scored} posts scored by Gemini ({model})"


def rescore_rows(rows: list[tuple[int, str, str]],
                 target_locations: list[str] | None = None,
                 experience_range: tuple[int, int] | None = None,
                 model: str | None = None,
                 key: str | None = None,
                 profile: str | None = None):
    """Re-judge posts that are already stored.

    *rows* is ``[(post_id, author_name, content), ...]``.  Yields
    ``(post_id, Verdict)`` for each post the model returned a verdict for, so
    the caller can stream progress into a UI instead of waiting for the lot.
    Batches that fail are skipped, leaving those rows as they were.
    """
    key = key or find_api_key()
    if not key or not rows:
        return
    model = model or DEFAULT_MODEL
    targets = list(target_locations if target_locations is not None
                   else config.TARGET_LOCATIONS)
    exp_range = experience_range or (config.EXPERIENCE_MIN, config.EXPERIENCE_MAX)

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        items = [(author or "", content or "") for _, author, content in batch]
        try:
            verdicts = classify_texts(items, key, model, targets, exp_range, profile)
        except LLMError as err:
            logger.warning("Re-score batch %d failed: %s", start // BATCH_SIZE, err)
            continue
        for verdict in verdicts:
            if 0 <= verdict.index < len(batch):
                yield batch[verdict.index][0], verdict
