"""
Regex-based information extraction from LinkedIn post content.

V1 implementation — no LLM required.
Extracts: role title, experience range, locations, skills, and hiring signals.
"""

from __future__ import annotations

import logging
import re
import urllib.request
import urllib.error
from typing import Optional
from urllib.parse import urlparse

import config
from storage.models import ParsedPost, RawPost

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Role title patterns
# --------------------------------------------------------------------------
# Matches standard job titles across various domains
ROLE_PATTERNS = [
    # General scalable pattern for almost any job role. 
    # e.g. "Software Engineer", "PowerBI Developer", "Data Analyst", "Product Manager"
    re.compile(
        r"\b((?:Senior |Sr\.? |Jr\.? |Junior |Lead |Staff |Principal |Chief |Head of )?"
        r"(?:[a-zA-Z0-9-]+\s+){1,3}"
        r"(?:Engineer|Developer|Scientist|Architect|Specialist|Consultant|Researcher|Analyst|Manager|Designer|Administrator|Programmer|Technician|Director|Executive|Associate))"
        r"\b",
        re.IGNORECASE
    ),
]

# --------------------------------------------------------------------------
# Experience patterns
# --------------------------------------------------------------------------
EXPERIENCE_PATTERNS = [
    # "2-4 years" / "2 to 4 years" / "2 - 4 yrs" / "0.5 - 2 years"
    re.compile(
        r"(\d{1,2}(?:\.\d+)?)\s*[-–to]+\s*(\d{1,2}(?:\.\d+)?)\s*(?:\+\s*)?(?:years?|yrs?|y)\b",
        re.IGNORECASE,
    ),
    # "2+ years" / "3+ yrs" / "1.5+ years"
    re.compile(
        r"(\d{1,2}(?:\.\d+)?)\+\s*(?:years?|yrs?|y)\b",
        re.IGNORECASE,
    ),
    # "minimum 2 years" / "at least 3 years"
    re.compile(
        r"(?:minimum|min|at\s+least)\s+(\d{1,2}(?:\.\d+)?)\s*(?:years?|yrs?|y)\b",
        re.IGNORECASE,
    ),
    # "2 years of experience" / "3 years experience"
    re.compile(
        r"(\d{1,2}(?:\.\d+)?)\s*(?:years?|yrs?|y)\s+(?:of\s+)?(?:experience|exp)\b",
        re.IGNORECASE,
    ),
    # "experience: 2-4 years"
    re.compile(
        r"experience\s*[:]\s*(\d{1,2}(?:\.\d+)?)\s*[-–to]+\s*(\d{1,2}(?:\.\d+)?)",
        re.IGNORECASE,
    ),
]

# Fresher / entry-level patterns (experience = 0)
FRESHER_PATTERNS = re.compile(
    r"\b(?:fresher|freshers|entry[\s-]level|no\s+experience\s+required|"
    r"0\s*[-–]\s*\d+\s*(?:years?|yrs?)|"
    r"fresh\s+graduate|recent\s+graduate|beginner)\b",
    re.IGNORECASE,
)


def extract_role(text: str, author_headline: str = "") -> Optional[str]:
    """Extract the job role/title from post text."""
    text_lower = text.lower()
    headline_lower = author_headline.lower().strip()
    
    # First, try to exactly match one of our specified AI roles
    for keyword in config.AI_ROLE_KEYWORDS:
        if keyword.lower() in text_lower:
            return keyword  # Return the canonical specified role
            
    # Next, try patterns specifically indicating hiring
    hiring_patterns = [
        re.compile(
            r"(?:hiring|looking for|role|position|title)\s*[:\-]?\s*"
            r"((?:Senior |Sr\.? |Jr\.? |Junior |Lead |Staff |Principal |Chief |Head of )?"
            r"(?:[a-zA-Z0-9-]+\s+){1,4}"
            r"(?:Engineer|Developer|Scientist|Architect|Specialist|Consultant|Researcher|Analyst|Manager|Designer|Administrator|Programmer|Technician|Director|Executive|Associate))\b",
            re.IGNORECASE
        )
    ]
    for pattern in hiring_patterns:
        match = pattern.search(text)
        if match:
            role = match.group(1).strip()
            role = re.sub(r"\s+", " ", role)
            if headline_lower and role.lower() in headline_lower:
                continue
            return role

    # Fallback to generic regex patterns
    for pattern in ROLE_PATTERNS:
        for match in pattern.finditer(text):
            role = match.group(1).strip()
            # Clean up extra spaces
            role = re.sub(r"\s+", " ", role)
            # Skip if this extracted role is just the poster's headline!
            if headline_lower and role.lower() in headline_lower:
                continue
            return role
    return None


def extract_experience(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract experience range from post text.

    Returns (min_years, max_years). Either or both can be None.
    """
    # Check for fresher/entry-level first
    if FRESHER_PATTERNS.search(text):
        return (0, 1)

    for pattern in EXPERIENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                try:
                    return (int(float(groups[0])), int(float(groups[1])))
                except (ValueError, TypeError):
                    pass
            elif len(groups) == 1:
                try:
                    min_exp = int(float(groups[0]))
                    return (min_exp, None)
                except (ValueError, TypeError):
                    pass

    return (None, None)


def extract_locations(text: str) -> list[str]:
    """Extract locations mentioned in the post from the configured list."""
    found: list[str] = []
    text_lower = text.lower()

    for location in config.TARGET_LOCATIONS:
        # Word boundary check to avoid partial matches
        pattern = re.compile(r"\b" + re.escape(location) + r"\b", re.IGNORECASE)
        if pattern.search(text):
            # Use the canonical form from config
            if location not in found:
                found.append(location)

    return found


def extract_skills(text: str) -> list[str]:
    """Extract known skills mentioned in the post."""
    found: list[str] = []
    text_lower = text.lower()

    for skill in config.KNOWN_SKILLS:
        # Use word boundary matching for accuracy
        # Handle multi-word skills and abbreviations
        escaped = re.escape(skill)
        pattern = re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)
        if pattern.search(text):
            # Normalize the skill name (use config canonical form)
            if skill not in found:
                found.append(skill)

    return found


def extract_emails(text: str) -> list[str]:
    """Extract email addresses from the post."""
    # Standard regex for email addresses
    pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    found = []
    for match in pattern.finditer(text):
        email = match.group().lower()
        if email not in found:
            found.append(email)
    return found


def extract_all_urls(text: str) -> list[str]:
    """Extract all URLs from the post text, ignoring generic social links."""
    url_pattern = re.compile(
        r'https?://[^\s<>"\')\]]+',
        re.IGNORECASE,
    )
    all_urls = url_pattern.findall(text)

    exclude_domains = [
        'linkedin.com', 'twitter.com', 'x.com', 'facebook.com',
        'instagram.com', 'youtube.com', 'medium.com', 'github.com',
    ]

    found: list[str] = []
    for url in all_urls:
        url = url.rstrip('.,;:!?)]\'"')
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            if domain and not any(ex == domain for ex in exclude_domains):
                if url not in found:
                    found.append(url)
        except Exception:
            pass

    return found


def is_apply_link(url: str) -> bool:
    """Check if a URL matches common ATS or application patterns."""
    apply_patterns = [
        r'greenhouse\.io', r'lever\.co', r'workday\.com',
        r'ashbyhq\.com', r'smartrecruiters\.com', r'icims\.com',
        r'taleo\.net', r'myworkday\.com', r'breezy\.hr',
        r'recruitee\.com', r'bamboohr\.com', r'jazz\.co',
        r'/apply', r'/careers', r'/jobs', r'/job/',
        r'/openings', r'/vacancies', r'/positions',
        r'lnkd\.in', r'forms\.gle', r'docs\.google\.com/forms',
        r'typeform\.com', r'notion\.so', r'aplitrak\.com'
    ]
    combined = re.compile('|'.join(apply_patterns), re.IGNORECASE)
    return bool(combined.search(url))


def determine_primary_url(content: str, urls: list[str]) -> Optional[str]:
    """Determine the most relevant primary URL based on context."""
    if not urls:
        return None
        
    content_lower = content.lower()
    # Search for strong signals near the URL
    anchor_phrases = ["view the jd", "more details", "job description", "apply here", "apply link", "link below", "find out more"]
    
    for url in urls:
        url_idx = content_lower.find(url.lower())
        if url_idx != -1:
            pretext = content_lower[max(0, url_idx - 60):url_idx]
            if any(phrase in pretext for phrase in anchor_phrases):
                return url
                
    # Fallback 1: Is there a known ATS?
    ats_patterns = [
        'greenhouse.io', 'lever.co', 'workday.com', 'ashbyhq.com',
        'smartrecruiters.com', 'icims.com', 'taleo.net',
        'myworkday.com', 'breezy.hr', 'recruitee.com',
        'aplitrak.com', 'bamboohr.com'
    ]
    for url in urls:
        url_lower = url.lower()
        if any(ats in url_lower for ats in ats_patterns):
            return url
            
    # Fallback 2: Just return the first one
    return urls[0]

def resolve_shortened_url(url: str, timeout: int = 5) -> str:
    """Follow redirects on shortened URLs and return the final destination.

    Only resolves URLs from known shortener domains (config.SHORTENED_URL_DOMAINS).
    Returns the original URL if resolution fails or the domain isn't a shortener.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Strip www. prefix for matching
        if domain.startswith("www."):
            domain = domain[4:]

        # Only resolve known shortener domains
        if not any(domain == sd or domain.endswith("." + sd) for sd in config.SHORTENED_URL_DOMAINS):
            return url

        logger.debug("Resolving shortened URL: %s", url)
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.url
            if final_url and final_url != url:
                logger.debug("Resolved %s → %s", url[:50], final_url[:80])
                return final_url
    except Exception as e:
        logger.debug("Failed to resolve %s: %s", url[:50], e)

    return url


def extract_company_url(text: str) -> Optional[str]:
    """Extract a company website URL from post text.

    Looks for non-LinkedIn, non-shortener URLs that likely point to
    a company website (e.g., careers pages, corporate sites).
    """
    url_pattern = re.compile(
        r'https?://[^\s<>"\')\]]+',
        re.IGNORECASE,
    )
    all_urls = url_pattern.findall(text)

    # Domains to exclude (social media, shorteners, LinkedIn itself)
    exclude_domains = [
        'linkedin.com', 'twitter.com', 'x.com', 'facebook.com',
        'instagram.com', 'youtube.com', 'medium.com', 'github.com',
    ]
    exclude_domains.extend(config.SHORTENED_URL_DOMAINS)

    for url in all_urls:
        url = url.rstrip('.,;:!?)\'"')
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            if not any(ex in domain for ex in exclude_domains):
                return url
        except Exception:
            continue

    return None


def detect_hiring_signal(text: str) -> tuple[bool, float]:
    """Detect if the post is a hiring/job opportunity.

    Returns (is_hiring, confidence) where confidence is 0.0 to 1.0.
    """
    text_lower = text.lower()
    
    # 1. ABSOLUTE REJECTION (Kill List)
    # If any of these are present, immediately reject the post.
    absolute_rejects = [
        # Spam & Job Seekers
        "cfbr", "commenting for better reach", "whatsapp community", "join our whatsapp", 
        "join my whatsapp", "daily fresher job", "telegram channel", "telegram group",
        "seeking a new role", "looking for a job", "open to work", "i am open to work",
        "hire me", "my resume", "laid off", "layoff", "seeking a job",
        "seeking new opportunities", "looking for new opportunities",
        "please find my resume", "i am looking for", "i'm looking for",
        "i am actively looking", "i'm actively looking", "kindly review my profile",
        "can you solve these", "mcq", "test your fundamentals", "spammers stay away",
        
        # Non-AI / Standard Web & Enterprise Roles (false positives)
        "java full stack", "java developer", "sap abap", "sap hana", "react developer",
        "frontend developer", "front-end developer", "angular developer", ".net developer",
        "dotnet developer", "php developer", "laravel developer", "wordpress developer"
    ]
    for reject in absolute_rejects:
        if reject in text_lower:
            return (False, 0.0)

    # 2. Weighted Signals
    hiring_hits = 0
    non_hiring_hits = 0

    for signal in config.HIRING_SIGNALS:
        if signal.lower() in text_lower:
            hiring_hits += 1

    for signal in config.NON_HIRING_SIGNALS:
        if signal.lower() in text_lower:
            non_hiring_hits += 1

    if hiring_hits == 0:
        return (False, 0.0)

    if non_hiring_hits > hiring_hits:
        return (False, 0.2)

    confidence = min(1.0, hiring_hits * 0.25)

    strong_signals = ["hiring", "#hiring", "apply", "looking for", "we're hiring"]
    for strong in strong_signals:
        if strong in text_lower:
            confidence = min(1.0, confidence + 0.2)
            break

    return (True, confidence)


def detect_senior_role(text: str, role: Optional[str] = None) -> bool:
    """Check if the post is for a senior-level position.

    Uses title keywords from config to identify senior roles.
    """
    check_text = text
    if role:
        check_text = role  # Focus on the extracted role title

    for keyword in config.SENIOR_TITLE_KEYWORDS:
        pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        if pattern.search(check_text):
            return True

    return False


def parse_post(raw: RawPost) -> ParsedPost:
    """Parse a raw post and extract all structured information.

    This is the main entry point for V1 (regex-based) parsing.
    """
    content = raw.content

    # Extract all fields
    role = extract_role(content, raw.author_headline)
    exp_min, exp_max = extract_experience(content)
    locations = extract_locations(content)
    skills = extract_skills(content)
    emails = extract_emails(content)
    is_hiring, hiring_confidence = detect_hiring_signal(content)
    is_senior = detect_senior_role(content, role)

    # Extract all links from text and merge with scraped <a> tag links
    text_urls = extract_all_urls(content)
    raw_merged = list(dict.fromkeys(text_urls + raw.extracted_urls))
    
    exclude_domains = [
        'linkedin.com', 'twitter.com', 'x.com', 'facebook.com',
        'instagram.com', 'youtube.com', 'medium.com', 'github.com',
    ]

    # Resolve shortened URLs and filter out excluded domains
    resolved_links = []
    for link in raw_merged:
        try:
            parsed = urlparse(link)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
                
            if domain and not any(ex == domain for ex in exclude_domains):
                resolved = resolve_shortened_url(link)
                if resolved not in resolved_links:
                    resolved_links.append(resolved)
        except Exception:
            pass

    # Determine primary URL
    primary_url = determine_primary_url(content, resolved_links)
    if primary_url and primary_url in resolved_links:
        resolved_links.remove(primary_url)
        
    # Keep all resolved non-social URLs as secondary links
    # (previously filtered to only apply links, but that discarded useful embedded links)
    final_extracted_urls = resolved_links
        
    logger.info("Found %d secondary apply URLs for post %s, Primary: %s", len(final_extracted_urls), raw.post_urn, primary_url)

    # Extract company website from post text
    company_url = extract_company_url(content)

    parsed = ParsedPost(
        raw=raw,
        role=role,
        experience_min=exp_min,
        experience_max=exp_max,
        locations=locations,
        skills=skills,
        emails=emails,
        primary_url=primary_url,
        extracted_urls=final_extracted_urls,
        company_url=company_url,
        author_url=raw.author_url,
        is_hiring=is_hiring,
        hiring_confidence=hiring_confidence,
        is_senior_role=is_senior,
    )

    logger.debug(
        "Parsed post [%s]: role=%s, exp=%s-%s, locations=%s, "
        "skills=%d, hiring=%s (%.0f%%), senior=%s",
        raw.post_urn[:30] if raw.post_urn else "no-urn",
        role,
        exp_min, exp_max,
        locations,
        len(skills),
        is_hiring, hiring_confidence * 100,
        is_senior,
    )

    return parsed
