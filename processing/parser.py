"""
Regex-based information extraction from LinkedIn post content.

No LLM required. Extracts: role title, experience range, locations, skills,
emails, URLs, hiring signals, seniority, and an absolute posted-at time.

Design rules (learned from real misfires):
- Every keyword match uses word boundaries. Substring checks like
  ``"apply" in text`` fire on "applying ML to…" and ``"course"`` on "of course".
- The role is looked for *right after a hiring anchor* ("hiring", "role:",
  "looking for") before we fall back to scanning the whole post, so a Backend
  post that mentions "our ML Engineers" isn't labelled "ML Engineer".
- A location only counts if it sits next to a location cue ("based in",
  "office", "📍", "Location:"), so "Delhi Public School alumni" doesn't tag Delhi.
- Experience takes the *strictest* minimum in the post — that is what
  disqualifies a candidate — not the number nearest the title.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import config
from storage.models import ParsedPost, RawPost

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Regex helpers
# --------------------------------------------------------------------------

def _phrase_pattern(phrases: list[str], plural: bool = False) -> re.Pattern:
    """Compile a list of phrases into one word-bounded, case-insensitive regex.

    ``\\b`` doesn't work next to '#' or '@', so hashtags and handles get a
    lookbehind/lookahead on whitespace instead. ``plural`` allows a trailing
    's' ("LLM Engineers") outside the phrase.
    """
    parts = []
    for phrase in sorted(phrases, key=len, reverse=True):
        escaped = re.escape(phrase.strip())
        # Allow flexible whitespace inside multi-word phrases
        escaped = escaped.replace(r"\ ", r"\s+")
        if phrase[0].isalnum():
            escaped = r"\b" + escaped
        else:
            escaped = r"(?<!\S)" + escaped
        if plural and phrase[-1].isalpha():
            escaped = escaped + r"(?=s?\b)"
        elif phrase[-1].isalnum():
            escaped = escaped + r"\b"
        else:
            escaped = escaped + r"(?!\S)"
        parts.append(escaped)
    return re.compile("|".join(parts), re.IGNORECASE)


def _count_matches(pattern: re.Pattern, text: str) -> int:
    return sum(1 for _ in pattern.finditer(text))


_HIRING_SIGNAL_RE = _phrase_pattern(config.HIRING_SIGNALS)
_NON_HIRING_SIGNAL_RE = _phrase_pattern(config.NON_HIRING_SIGNALS)
_ABSOLUTE_REJECT_RE = _phrase_pattern(config.ABSOLUTE_REJECT_PHRASES)
_STRONG_HIRING_RE = _phrase_pattern(
    ["hiring", "#hiring", "we're hiring", "we are hiring", "apply now", "apply here",
     "send your resume", "send your cv", "drop your resume", "immediate joiners"]
)
_SENIOR_TITLE_RE = _phrase_pattern(config.SENIOR_TITLE_KEYWORDS)


# --------------------------------------------------------------------------
# Role title patterns
# --------------------------------------------------------------------------

_TITLE_SUFFIX = (
    r"(?:Engineer|Developer|Scientist|Architect|Specialist|Consultant|Researcher|"
    r"Analyst|Manager|Designer|Administrator|Programmer|Technician|Director|"
    r"Executive|Associate|Intern|Lead)"
)
_TITLE_PREFIX = r"(?:Senior |Sr\.? |Jr\.? |Junior |Lead |Staff |Principal |Chief |Head of |Associate )?"

# Title words never contain '.', so a title can't run across a sentence end.
_TITLE_WORD = r"[A-Za-z0-9/&+#-]+"

# Bare title anywhere in the text: "PowerBI Developer", "Data Analyst".
ROLE_PATTERN = re.compile(
    r"\b(" + _TITLE_PREFIX + r"(?:" + _TITLE_WORD + r"\s+){1,3}" + _TITLE_SUFFIX + r")s?\b",
    re.IGNORECASE,
)

# Title immediately after a hiring anchor: "Hiring: AI Engineer", "Role - LLM Developer".
# Each anchor ends in \b so "hiring a" can't eat the "A" of "Hiring AI Engineer".
_ANCHOR_ALTERNATION = "|".join(
    re.escape(a).replace(r"\ ", r"\s+") + r"\b"
    for a in sorted(config.HIRING_ANCHORS, key=len, reverse=True)
)
# Lazy {0,4}? → the *shortest* title after the anchor ("AI Developer", not
# "AI Developer interns"). The plural 's' sits outside the capture group.
ANCHORED_ROLE_PATTERN = re.compile(
    r"(?:" + _ANCHOR_ALTERNATION + r")\s*[:\-–—#!|]?\s*(?:for\s+|a\s+|an\s+|the\s+)?"
    r"(" + _TITLE_PREFIX + r"(?:" + _TITLE_WORD + r"\s+){0,4}?" + _TITLE_SUFFIX + r")s?\b",
    re.IGNORECASE,
)

# How far after an anchor we still trust a canonical AI keyword match.
_ANCHOR_WINDOW_CHARS = 160

_AI_ROLE_KEYWORDS_RE = _phrase_pattern(config.AI_ROLE_KEYWORDS, plural=True)
_AI_ROLE_CANONICAL = {kw.lower(): kw for kw in config.AI_ROLE_KEYWORDS}


_SENTENCE_END_RE = re.compile(r"[.!?]\s|\n")


def _clip_to_sentence(window: str) -> str:
    """Cut an anchor window at the first sentence or line break."""
    m = _SENTENCE_END_RE.search(window)
    return window[: m.start()] if m else window


_LEVEL_PREFIX_RE = re.compile(
    r"(?:senior|sr\.?|jr\.?|junior|lead|staff|principal|associate)\s+$", re.IGNORECASE
)


def _canonical_ai_role(matched: str, preceding: str = "") -> str:
    """Map a keyword hit to its config spelling, keeping a level prefix if present.

    "Senior LLM Engineer" must stay senior — the seniority penalty and the
    dashboard both read it off the extracted title.
    """
    role = _AI_ROLE_CANONICAL.get(re.sub(r"\s+", " ", matched.lower()), matched)
    m = _LEVEL_PREFIX_RE.search(preceding)
    if m:
        prefix = m.group(0).strip()
        role = f"{prefix[0].upper()}{prefix[1:]} {role}"
    return role


def extract_role(text: str, author_headline: str = "") -> Optional[str]:
    """Extract the job role/title from post text.

    Priority:
      1. The title directly after a hiring anchor ("Hiring: X", "Role - X").
         If it contains a canonical AI keyword, the canonical spelling is used.
      2. A canonical AI role keyword within the same sentence as an anchor.
      3. A canonical AI role keyword anywhere.
      4. Any title pattern anywhere.
    Titles that merely repeat the author's own headline are skipped.
    """
    headline_lower = author_headline.lower().strip()

    def _skip(role: str) -> bool:
        return bool(headline_lower) and role.lower() in headline_lower

    # 1. Title right after an anchor
    for m in ANCHORED_ROLE_PATTERN.finditer(text):
        role = re.sub(r"\s+", " ", m.group(1).strip())
        kw = _AI_ROLE_KEYWORDS_RE.search(role)
        if kw:
            role = _canonical_ai_role(kw.group(0), role[: kw.start()])
        if not _skip(role):
            return role

    # 2. Canonical AI keyword in the same sentence as an anchor
    for m in re.finditer(r"(?:" + _ANCHOR_ALTERNATION + r")", text, re.IGNORECASE):
        window = _clip_to_sentence(text[m.end(): m.end() + _ANCHOR_WINDOW_CHARS])
        kw = _AI_ROLE_KEYWORDS_RE.search(window)
        if kw:
            role = _canonical_ai_role(kw.group(0), window[: kw.start()])
            if not _skip(role):
                return role

    # 3. Canonical AI keyword anywhere
    m = _AI_ROLE_KEYWORDS_RE.search(text)
    if m:
        role = _canonical_ai_role(m.group(0), text[max(0, m.start() - 12): m.start()])
        if not _skip(role):
            return role

    # 4. Any title anywhere
    for m in ROLE_PATTERN.finditer(text):
        role = re.sub(r"\s+", " ", m.group(1).strip())
        if not _skip(role):
            return role

    return None


# --------------------------------------------------------------------------
# Experience patterns
# --------------------------------------------------------------------------

_NUM = r"(\d{1,2}(?:\.\d+)?)"
_YEARS = r"(?:years?|yrs?|y)\b"

EXPERIENCE_PATTERNS = [
    # "2-4 years" / "2 to 4 years" / "2 - 4 yrs" / "0.5 - 2 years"
    re.compile(_NUM + r"\s*(?:-|–|to)\s*" + _NUM + r"\s*(?:\+\s*)?" + _YEARS, re.IGNORECASE),
    # "2+ years" / "3+ yrs" / "1.5+ years"
    re.compile(_NUM + r"\s*\+\s*" + _YEARS, re.IGNORECASE),
    # "minimum 2 years" / "at least 3 years"
    re.compile(r"(?:minimum|min\.?|at\s+least|atleast|more\s+than|over)\s+(?:of\s+)?" + _NUM + r"\s*" + _YEARS, re.IGNORECASE),
    # "2 years of experience" / "3 years experience"
    re.compile(_NUM + r"\s*" + _YEARS + r"\s+(?:of\s+)?(?:relevant\s+|hands-on\s+|industry\s+)?(?:experience|exp)\b", re.IGNORECASE),
    # "experience: 2-4" / "exp - 3 to 5"
    re.compile(r"(?:experience|exp)\s*[:\-–]\s*" + _NUM + r"\s*(?:-|–|to)\s*" + _NUM, re.IGNORECASE),
]

# Fresher / entry-level (experience = 0-1), unless negated.
FRESHER_PATTERN = re.compile(
    r"\b(?:freshers?|entry[\s-]level|no\s+experience\s+required|"
    r"fresh\s+graduates?|recent\s+graduates?|new\s+grads?|campus\s+hire)\b",
    re.IGNORECASE,
)
_FRESHER_NEGATION = re.compile(
    r"\b(?:not?|no|non|isn'?t|aren'?t|don'?t|without|except|excluding|"
    r"please\s+(?:do\s+)?not|kindly\s+(?:do\s+)?not)\b[^.\n]{0,25}$",
    re.IGNORECASE,
)


def _fresher_mentioned(text: str) -> bool:
    """True if 'fresher' appears without a negation right before it."""
    for m in FRESHER_PATTERN.finditer(text):
        before = text[max(0, m.start() - 40): m.start()]
        if not _FRESHER_NEGATION.search(before):
            return True
    return False


def extract_experience(text: str, role: Optional[str] = None) -> tuple[Optional[int], Optional[int]]:
    """Extract the experience requirement as (min_years, max_years).

    When a post lists several requirements ("5+ years Python, 2-3 years with
    LLMs") the *strictest* (highest) minimum wins — that is what actually
    disqualifies a candidate. The max is taken from the same match.
    A genuine fresher mention wins only when no explicit range is given.
    ``role`` is accepted for backwards compatibility and ignored.
    """
    candidates: list[tuple[int, Optional[int]]] = []
    taken: list[tuple[int, int]] = []  # spans already claimed by a more specific pattern
    for pattern in EXPERIENCE_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < e and span[1] > b for b, e in taken):
                continue
            taken.append(span)
            groups = [g for g in match.groups() if g is not None]
            try:
                lo = int(float(groups[0]))
                hi = int(float(groups[1])) if len(groups) > 1 else None
            except (ValueError, IndexError):
                continue
            if hi is not None and hi < lo:
                lo, hi = hi, lo
            if lo > 40:  # "2024 years" style false positives
                continue
            candidates.append((lo, hi))

    if candidates:
        candidates.sort(key=lambda c: (c[0], -(c[1] if c[1] is not None else -1)))
        return candidates[-1]

    if _fresher_mentioned(text):
        return (0, 1)

    return (None, None)


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

def _location_regex(name: str) -> re.Pattern:
    """Short all-caps names (US, UK, EU) are only matched in upper case —
    'us' and 'uk' are ordinary words otherwise."""
    flags = 0 if (len(name) <= 3 and name.isupper()) else re.IGNORECASE
    return re.compile(r"\b" + re.escape(name) + r"\b", flags)


# Target locations plus the non-target ones we recognise (so "based in
# Berlin" becomes a location *mismatch*, not "no location mentioned").
_LOCATION_TARGETS: list[tuple[str, re.Pattern]] = [
    (loc, _location_regex(loc))
    for loc in list(config.TARGET_LOCATIONS) + list(getattr(config, "OTHER_LOCATIONS", []))
] + [
    (canonical, re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE))
    for alias, canonical in getattr(config, "LOCATION_ALIASES", {}).items()
]

# A city name that is really part of an institution / team / person name.
# "Delhi Public School", "IIT Bombay", "Mumbai Indians", "University of Pune".
_NOT_A_PLACE_AFTER = re.compile(
    r"^\s*(?:" + "|".join(
        re.escape(w).replace(r"\ ", r"\s+")
        for w in sorted(config.LOCATION_NEGATIVE_AFTER, key=len, reverse=True)
    ) + r")\b",
    re.IGNORECASE,
)
_NOT_A_PLACE_BEFORE = re.compile(
    r"(?:" + "|".join(
        re.escape(w).replace(r"\ ", r"\s+")
        for w in sorted(config.LOCATION_NEGATIVE_BEFORE, key=len, reverse=True)
    ) + r")\s+$",
    re.IGNORECASE,
)


def _is_place_mention(text: str, start: int, end: int) -> bool:
    """False when the surrounding words say this isn't a job location."""
    after = text[end: end + 30]
    before = text[max(0, start - 20): start]
    return not (_NOT_A_PLACE_AFTER.match(after) or _NOT_A_PLACE_BEFORE.search(before))


def extract_locations(text: str) -> list[str]:
    """Extract locations mentioned as places (config canonical spelling).

    Any known city/country counts unless the words around it show it's an
    institution, team or person name (config.LOCATION_NEGATIVE_*).
    """
    found: list[str] = []
    for canonical, pattern in _LOCATION_TARGETS:
        if canonical in found:
            continue
        for m in pattern.finditer(text):
            if _is_place_mention(text, m.start(), m.end()):
                found.append(canonical)
                break
    return found


# --------------------------------------------------------------------------
# Skills / emails / URLs
# --------------------------------------------------------------------------

_SKILL_PATTERNS = [
    (skill, re.compile(r"(?<![\w+#])" + re.escape(skill) + r"(?![\w+#])", re.IGNORECASE))
    for skill in config.KNOWN_SKILLS
]


def extract_skills(text: str) -> list[str]:
    """Extract known skills mentioned in the post (canonical config spelling)."""
    found: list[str] = []
    for skill, pattern in _SKILL_PATTERNS:
        if skill not in found and pattern.search(text):
            found.append(skill)
    return found


_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def extract_emails(text: str) -> list[str]:
    """Extract email addresses from the post."""
    found: list[str] = []
    for match in _EMAIL_RE.finditer(text):
        email = match.group().lower().rstrip(".")
        if email not in found:
            found.append(email)
    return found


_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+', re.IGNORECASE)


def _domain_of(url: str) -> str:
    try:
        domain = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return domain[4:] if domain.startswith("www.") else domain


def _is_excluded_domain(domain: str) -> bool:
    return any(domain == ex or domain.endswith("." + ex) for ex in config.EXCLUDE_URL_DOMAINS)


def extract_all_urls(text: str) -> list[str]:
    """Extract all URLs from the post text, ignoring social/generic domains."""
    found: list[str] = []
    for url in _URL_RE.findall(text):
        url = url.rstrip('.,;:!?)]\'"')
        domain = _domain_of(url)
        if domain and not _is_excluded_domain(domain) and url not in found:
            found.append(url)
    return found


_APPLY_URL_RE = re.compile(
    "|".join(re.escape(x) for x in config.ATS_DOMAINS + config.APPLY_URL_PATH_HINTS + ["lnkd.in"]),
    re.IGNORECASE,
)


def is_apply_link(url: str) -> bool:
    """Check if a URL matches a known ATS or an application-page path."""
    return bool(_APPLY_URL_RE.search(url))


def is_ats_url(url: str) -> bool:
    domain = _domain_of(url)
    return any(domain == ats or domain.endswith("." + ats) for ats in config.ATS_DOMAINS)


def determine_primary_url(content: str, urls: list[str], role: Optional[str] = None) -> Optional[str]:
    """Pick the most relevant URL: near the role, near an 'apply' phrase, an ATS, else first."""
    if not urls:
        return None

    content_lower = content.lower()

    # Priority 1: the URL closest after a role mention
    if role:
        role_indices = [m.start() for m in re.finditer(re.escape(role.lower()), content_lower)]
        if role_indices:
            best_url, min_dist = None, float("inf")
            for url in urls:
                url_idx = content_lower.find(url.lower())
                if url_idx == -1:
                    continue
                dists = [url_idx - r for r in role_indices if url_idx > r]
                if dists and min(dists) < min_dist:
                    min_dist, best_url = min(dists), url
            if best_url and min_dist < 200:
                return best_url

    # Priority 2: an apply phrase right before the URL
    anchor_phrases = ["view the jd", "more details", "job description", "apply here",
                      "apply link", "link below", "find out more", "apply:", "apply at"]
    for url in urls:
        url_idx = content_lower.find(url.lower())
        if url_idx != -1:
            pretext = content_lower[max(0, url_idx - 60): url_idx]
            if any(phrase in pretext for phrase in anchor_phrases):
                return url

    # Priority 3: a known ATS
    for url in urls:
        if is_ats_url(url):
            return url

    return urls[0]


# Process-wide cache so the same shortener is only fetched once per run (and
# across runs within the same process). Guarded by a lock because parsing is
# fanned out across worker threads from the async pipeline.
_URL_RESOLVE_CACHE: dict[str, str] = {}
_URL_RESOLVE_LOCK = threading.Lock()


def _is_shortener(domain: str) -> bool:
    return any(domain == sd or domain.endswith("." + sd) for sd in config.SHORTENED_URL_DOMAINS)


def resolve_shortened_url(url: str, timeout: int | None = None) -> str:
    """Follow redirects on shortened URLs and return the final destination.

    Only resolves URLs from known shortener domains (config.SHORTENED_URL_DOMAINS).
    Returns the original URL if resolution fails or the domain isn't a shortener.
    Results are memoized in a thread-safe process-wide cache. This is a blocking
    network call — the pipeline runs parse_post in worker threads.
    """
    if timeout is None:
        timeout = getattr(config, "URL_RESOLVE_TIMEOUT", 5)

    with _URL_RESOLVE_LOCK:
        cached = _URL_RESOLVE_CACHE.get(url)
    if cached is not None:
        return cached

    resolved = url
    if _is_shortener(_domain_of(url)):
        try:
            logger.debug("Resolving shortened URL: %s", url)
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.url and resp.url != url:
                    logger.debug("Resolved %s → %s", url[:50], resp.url[:80])
                    resolved = resp.url
        except Exception as e:  # network errors, HTTP errors, timeouts
            logger.debug("Failed to resolve %s: %s", url[:50], e)

    with _URL_RESOLVE_LOCK:
        _URL_RESOLVE_CACHE[url] = resolved
    return resolved


def extract_company_url(text: str) -> Optional[str]:
    """First non-social, non-shortener URL in the post — usually the company site."""
    for url in extract_all_urls(text):
        if not _is_shortener(_domain_of(url)):
            return url
    return None


# --------------------------------------------------------------------------
# Hiring signal / seniority
# --------------------------------------------------------------------------

def detect_hiring_signal(text: str) -> tuple[bool, float]:
    """Detect if the post is a hiring/job opportunity.

    Returns (is_hiring, confidence 0.0-1.0). All matching is word-bounded.
    """
    # 1. Absolute rejection: job seekers, engagement bait, spam groups
    if _ABSOLUTE_REJECT_RE.search(text):
        return (False, 0.0)

    # 2. Weighted signals
    hiring_hits = _count_matches(_HIRING_SIGNAL_RE, text)
    non_hiring_hits = _count_matches(_NON_HIRING_SIGNAL_RE, text)

    if hiring_hits == 0:
        return (False, 0.0)

    strong = bool(_STRONG_HIRING_RE.search(text))
    # More "event/news" words than hiring words → not a job post. On a tie,
    # only an explicit "hiring"/"apply now" style phrase rescues it.
    if non_hiring_hits > hiring_hits or (non_hiring_hits == hiring_hits and not strong):
        return (False, 0.2)

    confidence = min(1.0, hiring_hits * 0.25)
    if strong:
        confidence = min(1.0, confidence + 0.2)
    return (True, confidence)


def detect_senior_role(text: str, role: Optional[str] = None) -> bool:
    """True if the (extracted) title carries a senior-level keyword."""
    return bool(_SENIOR_TITLE_RE.search(role if role else text))


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------

_RELATIVE_TIME_RE = re.compile(
    r"(\d+)\s*(second|sec|minute|min|hour|hr|day|week|wk|month|mo|year|yr|[smhdwy])s?\b",
    re.IGNORECASE,
)
_UNIT_SECONDS = {
    "second": 1, "sec": 1, "s": 1,
    "minute": 60, "min": 60, "m": 60,
    "hour": 3600, "hr": 3600, "h": 3600,
    "day": 86400, "d": 86400,
    "week": 604800, "wk": 604800, "w": 604800,
    "month": 2_592_000, "mo": 2_592_000,
    "year": 31_536_000, "yr": 31_536_000, "y": 31_536_000,
}


def parse_relative_timestamp(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Convert LinkedIn's relative time ("2h", "3 days ago", "1w • Edited") to a datetime."""
    if not text:
        return None
    now = now or datetime.now()
    lowered = text.strip().lower()
    if lowered.startswith(("just now", "now")):
        return now
    m = _RELATIVE_TIME_RE.search(lowered)
    if not m:
        return None
    amount = int(m.group(1))
    seconds = _UNIT_SECONDS.get(m.group(2).lower())
    if seconds is None:
        return None
    return now - timedelta(seconds=amount * seconds)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def normalize_unicode(text: str) -> str:
    """Normalize fancy Unicode characters (like mathematical bold) to standard ASCII."""
    if not text:
        return text
    return unicodedata.normalize("NFKD", text)


def parse_post(raw: RawPost) -> ParsedPost:
    """Parse a raw post and extract all structured information."""
    content = normalize_unicode(raw.content)
    author_headline = normalize_unicode(raw.author_headline)

    role = extract_role(content, author_headline)
    exp_min, exp_max = extract_experience(content)
    locations = extract_locations(content)
    skills = extract_skills(content)
    emails = extract_emails(content)
    is_hiring, hiring_confidence = detect_hiring_signal(content)
    is_senior = detect_senior_role(content, role)

    if raw.posted_at is None and raw.timestamp_text:
        raw.posted_at = parse_relative_timestamp(raw.timestamp_text, raw.scraped_at)

    # Merge text URLs with scraped <a> links, drop social domains, resolve shorteners
    resolved_links: list[str] = []
    for link in dict.fromkeys(extract_all_urls(content) + raw.extracted_urls):
        domain = _domain_of(link)
        if not domain or _is_excluded_domain(domain):
            continue
        resolved = resolve_shortened_url(link)
        if resolved not in resolved_links:
            resolved_links.append(resolved)

    primary_url = determine_primary_url(content, resolved_links, role)
    if primary_url and primary_url in resolved_links:
        resolved_links.remove(primary_url)

    logger.debug("Post %s: primary=%s, %d secondary URLs", raw.post_urn, primary_url, len(resolved_links))

    parsed = ParsedPost(
        raw=raw,
        role=role,
        experience_min=exp_min,
        experience_max=exp_max,
        locations=locations,
        skills=skills,
        emails=emails,
        primary_url=primary_url,
        extracted_urls=resolved_links,
        company_url=extract_company_url(content),
        author_url=raw.author_url,
        is_hiring=is_hiring,
        hiring_confidence=hiring_confidence,
        is_senior_role=is_senior,
    )

    logger.debug(
        "Parsed post [%s]: role=%s, exp=%s-%s, locations=%s, skills=%d, hiring=%s (%.0f%%), senior=%s",
        raw.post_urn[:30] if raw.post_urn else "no-urn",
        role, exp_min, exp_max, locations, len(skills), is_hiring, hiring_confidence * 100, is_senior,
    )
    return parsed


# --------------------------------------------------------------------------
# Author name recovery
# --------------------------------------------------------------------------
# LinkedIn scrambles its CSS class names, so the selector list in
# `scraper/linkedin.py` goes stale every few months and `author_name` comes
# back empty — which is how a whole database of posts ends up attributed to
# "Unknown".  These two helpers recover the name from data that does not
# depend on class names: the structure of the post text, and the profile URL.

# Interface chrome that appears above/below the author in a scraped post.
_AUTHOR_CHROME = re.compile(
    r"^(?:feed post|suggested|promoted|reposted this|follow(?:ing)?|join|connect|"
    r"view job|see more|\+ follow|like|comment|repost|send)\b",
    re.I,
)
# "3h •", "• 3rd+", "with 2 others • 23h • Edited •"
_AUTHOR_TIMESTAMP = re.compile(r"^(?:•\s*)?(?:\d+\s*(?:s|m|h|d|w|mo|yr)\b|\d+(?:st|nd|rd|th)\+?)", re.I)
_CONNECTION_DEGREE = re.compile(r"\s*•\s*\d+(?:st|nd|rd|th)\+?.*$", re.I)
_EMOJI_START = re.compile(r"^[^\w\"'(]", re.UNICODE)


def _looks_like_name(line: str) -> bool:
    """Whether *line* reads like a person or company name rather than a headline."""
    if not (1 < len(line) <= 70):
        return False
    if _AUTHOR_CHROME.match(line) or _AUTHOR_TIMESTAMP.match(line):
        return False
    # Headlines are pipe-separated lists of skills; names are not.
    if line.count("|") >= 1 or line.count("#") >= 1:
        return False
    if _EMOJI_START.match(line):
        return False
    # Body text leaks in when a post was scraped without its actor block.
    # Names do not end in sentence punctuation ("Required Skills:",
    # "What you'll do?") — a trailing "." is fine, as in "James R.".
    return line[-1] not in ":?!"


def author_from_content(content: str) -> str:
    """Recover the author's display name from the leading lines of a post.

    LinkedIn renders the actor block first, so the name is the first line that
    is not interface chrome or a timestamp::

        Feed post / FireAI / 21h • / Follow / We're #hiring ...   -> "FireAI"
        Feed post / Emmanuel N / • 3rd+ / HR Specialist | ...     -> "Emmanuel N"
    """
    if not content:
        return ""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    for line in lines[:6]:
        # "Sri Sahasra M • 3rd+" -> "Sri Sahasra M"
        candidate = _CONNECTION_DEGREE.sub("", line).strip()
        if _AUTHOR_CHROME.match(candidate) or _AUTHOR_TIMESTAMP.match(candidate):
            continue
        if _looks_like_name(candidate):
            return candidate
        # The actor block is contiguous at the top of the post.  A line that
        # is neither chrome nor a name means this post was scraped without
        # one, so keep scanning and we would just pick up body copy.
        break
    return ""


def author_from_url(author_url: str) -> str:
    """Last-resort display name derived from a LinkedIn profile/company URL.

    ``/company/fireaiglobal/`` -> "Fireaiglobal";
    ``/in/shubham-mantri-iitr17/`` -> "Shubham Mantri Iitr17".
    """
    if not author_url:
        return ""
    try:
        parsed = urlparse(author_url)
    except ValueError:
        return ""
    # Only LinkedIn's own URLs carry the /in/ and /company/ convention; any
    # other host would have its path read as a name.
    host = parsed.netloc.lower().split(":")[0]
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return ""
    path = parsed.path.strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] not in ("in", "company", "school", "showcase"):
        return ""
    slug = parts[1].split("?")[0]
    # Drop LinkedIn's uniqueness suffix: "john-doe-8a3b21c4" -> "john-doe"
    slug = re.sub(r"-(?=[a-z0-9]*\d)[a-z0-9]{6,}$", "", slug)
    words = [w for w in re.split(r"[-_]+", slug) if w]
    return " ".join(w.capitalize() for w in words)[:70]


def resolve_author_name(author_name: str, content: str = "", author_url: str = "") -> str:
    """The best display name available: scraped, then structural, then URL."""
    for candidate in (author_name, author_from_content(content), author_from_url(author_url)):
        cleaned = (candidate or "").strip()
        if cleaned:
            return cleaned
    return ""


def headline_from_content(content: str, author: str = "") -> str:
    """Recover the author's headline (the "Founder | ex-X | ..." strap line).

    Only a pipe-separated descriptor sitting directly under the actor block
    counts, which keeps body copy such as "URGENT HIRING | HYDERABAD" out:
    that line starts with an emoji and is rejected by :func:`_looks_like_name`'s
    sibling check below.
    """
    if not content:
        return ""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    index = None
    for i, line in enumerate(lines[:8]):
        candidate = _CONNECTION_DEGREE.sub("", line).strip()
        if author:
            if candidate.lower() == author.strip().lower():
                index = i
                break
        elif _looks_like_name(candidate):
            index = i
            break
    if index is None:
        return ""

    for line in lines[index + 1:index + 4]:
        if _AUTHOR_CHROME.match(line) or _AUTHOR_TIMESTAMP.match(line):
            continue
        if "|" in line and 10 <= len(line) <= 300 and not _EMOJI_START.match(line):
            return line
        break
    return ""


def resolve_author_headline(author_headline: str, content: str = "", author: str = "") -> str:
    """The scraped headline, or one recovered from the post structure."""
    cleaned = (author_headline or "").strip()
    return cleaned or headline_from_content(content, author)
