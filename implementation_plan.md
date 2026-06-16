# LinkedIn AI Job Post Monitor — Implementation Plan

## Problem Summary

Many recruiters post hiring opportunities on **LinkedIn Posts** before creating formal job listings. This system automatically monitors LinkedIn's Posts search, detects AI/GenAI/LLM-related hiring posts, filters by experience and location, deduplicates, and sends **Telegram notifications** for new opportunities only.

---

## User Review Required

> [!IMPORTANT]
> **LinkedIn Authentication**: Playwright will need a logged-in LinkedIn session to search posts. The plan uses a **persistent browser profile** approach — you log in manually once, and the system reuses that session. This avoids storing credentials in code. Is this acceptable, or do you prefer cookie-based auth?

> [!WARNING]
> **Anti-Detection Risk**: LinkedIn actively detects and bans automated access. This plan includes stealth measures (randomized delays, `playwright-stealth`, human-like behavior). However, **using a secondary/disposable LinkedIn account** is strongly recommended. Are you okay with this risk?

> [!IMPORTANT]
> **Telegram Bot Setup**: You'll need to create a Telegram bot via [@BotFather](https://t.me/BotFather) and get your `chat_id`. Do you already have these, or do you need setup instructions included?

---

## Open Questions

1. **LLM Provider**: For V2 LLM features (extraction, scoring, classification), which provider should we use?
   - OpenRouter (you already have a key in `.env`)
   - OpenAI
   - Local model (Ollama)
   - *Recommendation*: OpenRouter since you already have a key configured

2. **Scheduling Method**: The plan defaults to APScheduler (runs as a persistent Python process). Alternatives:
   - Windows Task Scheduler (cron-like, runs script on schedule)
   - GitHub Actions (free, but requires pushing code to GitHub)
   - *Recommendation*: APScheduler for simplicity; can switch later

3. **Search Scope**: Should the system search for **all keywords in a single run** (slower, more thorough) or **rotate through keywords across runs** (faster per run, spreads load)?
   - *Recommendation*: All keywords per run, with randomized delays between searches

4. **Date Range Filter**: Should we only look at posts from the **past 24 hours** (`f_TPR=r86400`) on each run, or past week? Past 24h is safer for dedup and faster. Past week catches more but has more overlap.
   - *Recommendation*: Past 24 hours

---

## Project Structure

```
c:\Users\naver\Music\LangChain\linkedin_monitor\
├── config.py              # All configuration (keywords, locations, thresholds)
├── main.py                # Entry point — orchestrates the pipeline
├── scheduler.py           # APScheduler-based hourly execution
├── scraper/
│   ├── __init__.py
│   ├── linkedin.py        # Playwright-based LinkedIn Posts scraper
│   └── stealth.py         # Anti-detection utilities
├── processing/
│   ├── __init__.py
│   ├── parser.py          # Regex-based extraction (V1) — role, exp, location, skills
│   ├── filters.py         # Experience range + location filtering
│   └── dedup.py           # Post ID + content hash deduplication
├── notifications/
│   ├── __init__.py
│   └── telegram.py        # Telegram Bot notification sender
├── storage/
│   ├── __init__.py
│   ├── database.py        # SQLite connection + operations
│   └── models.py          # Data classes for Post, Notification, etc.
├── llm/                   # V2 — LLM-powered features (future)
│   ├── __init__.py
│   ├── extractor.py       # Structured info extraction
│   ├── classifier.py      # Hiring post classification
│   ├── scorer.py          # Relevance scoring
│   └── summarizer.py      # Post summarization
├── .env                   # Secrets (Telegram token, LLM keys)
├── requirements.txt       # Dependencies
└── README.md              # Setup & usage instructions
```

---

## Proposed Changes

### Config Module

#### [NEW] [config.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/config.py)

Central configuration file containing:
- **Default keywords** list (AI Engineer, GenAI Engineer, LLM Engineer, etc.)
- **Default locations** list (Hyderabad, Bangalore, Pune, etc.)
- **Experience range** (`min_experience: 0`, `max_experience: 3`)
- **User profile skills** for relevance matching
- **LinkedIn search URL template** (`https://www.linkedin.com/search/results/content/?keywords={keyword}&sortBy=date_posted&f_TPR=r86400`)
- **Timing configs** (delay ranges, scroll counts, run interval)
- **Telegram config** (loaded from `.env`)
- **SQLite database path**

All values editable. Uses `dataclass` or plain constants for simplicity.

---

### Scraper Module

#### [NEW] [scraper/linkedin.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/scraper/linkedin.py)

The core scraping engine using **Playwright (async)**:

1. **Launch browser** with persistent profile (reuses logged-in session)
2. For each keyword in config:
   - Navigate to `linkedin.com/search/results/content/?keywords={keyword}&sortBy=date_posted&f_TPR=r86400`
   - Wait for posts to load (wait for `.feed-shared-update-v2` or similar selectors)
   - **Scroll down** 3-5 times with random delays (2-5s) to load more posts
   - Extract from each post card:
     - **Post URN/ID** (from `data-urn` attribute)
     - **Author name** (from author section)
     - **Author headline** (recruiter identification)
     - **Post content text** (full text)
     - **Post URL** (constructed from URN or permalink)
     - **Timestamp** (relative time like "2h ago")
   - Random delay (10-30s) between keyword searches
3. Return list of raw post data dictionaries

#### [NEW] [scraper/stealth.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/scraper/stealth.py)

Anti-detection utilities:
- `playwright-stealth` integration for fingerprint masking
- `--disable-blink-features=AutomationControlled` launch flag
- Randomized viewport sizes, user agents, and timezone/locale
- Human-like scroll behavior (variable speed, occasional pauses)
- Random mouse movements before clicks
- Configurable delay ranges between actions

---

### Processing Module

#### [NEW] [processing/parser.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/processing/parser.py)

**V1: Pure regex/keyword-based extraction** (no LLM):

- **Role Detection**: Pattern matching for titles like "GenAI Engineer", "LLM Engineer", "AI Developer", etc.
- **Experience Extraction**: Regex patterns for:
  - `(\d+)\s*[-–to]\s*(\d+)\s*(?:years?|yrs?)`
  - `(\d+)\+?\s*(?:years?|yrs?)`
  - Keywords: "fresher", "entry-level", "junior", "senior", "principal"
- **Location Extraction**: Match against configured location list (case-insensitive)
- **Skills Extraction**: Match against known AI/ML skill keywords (LangChain, RAG, Python, PyTorch, etc.)
- **Hiring Signal Detection**: Keywords like "hiring", "looking for", "opening", "we're seeking", "join our team", "apply", "DM me"

Returns a structured `ParsedPost` dataclass.

#### [NEW] [processing/filters.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/processing/filters.py)

Post filtering logic:
- **Experience Filter**: Accept if extracted experience overlaps with user's configured range. If no experience found in post, **accept by default** (don't miss opportunities)
- **Location Filter**: Accept if any extracted location matches config, OR if post mentions "remote". If no location found, accept by default
- **Hiring Post Filter**: Reject posts that are clearly NOT hiring (e.g., articles, news, conference announcements) based on keyword scoring
- **Seniority Filter**: Reject if post mentions "Senior", "Staff", "Principal", "Architect", "Director", "VP" in the title context AND experience ≥ 5 years

#### [NEW] [processing/dedup.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/processing/dedup.py)

Deduplication engine:
1. **Primary**: Check post URN/ID against database
2. **Secondary**: Compute SHA-256 hash of normalized post content (lowercase, stripped whitespace) and check against database
3. Returns only posts that pass both checks (truly new)

---

### Storage Module

#### [NEW] [storage/database.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/storage/database.py)

SQLite operations:
- `init_db()` — Create tables if not exist
- `insert_post(post)` — Store a seen post
- `is_duplicate(post_id, content_hash)` — Check existence
- `insert_notification(post_id, sent_at)` — Track sent notifications
- `get_stats()` — Return counts for reporting
- `get_keywords()` / `add_keyword()` / `remove_keyword()` — Keyword management
- `cleanup_old_posts(days=30)` — Purge posts older than 30 days

**SQLite Schema**:

```sql
CREATE TABLE posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_urn        TEXT UNIQUE,
    post_url        TEXT,
    author_name     TEXT,
    author_headline TEXT,
    content         TEXT,
    content_hash    TEXT,
    role            TEXT,
    experience_min  INTEGER,
    experience_max  INTEGER,
    locations       TEXT,       -- JSON array
    skills          TEXT,       -- JSON array
    is_hiring       BOOLEAN DEFAULT 1,
    relevance_score INTEGER,
    keyword_matched TEXT,
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER REFERENCES posts(id),
    channel     TEXT DEFAULT 'telegram',
    sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status      TEXT DEFAULT 'sent'
);

CREATE TABLE keywords (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT UNIQUE NOT NULL,
    active  BOOLEAN DEFAULT 1
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE run_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    keywords_searched INTEGER,
    posts_found     INTEGER,
    new_posts       INTEGER,
    notifications_sent INTEGER,
    errors          TEXT
);
```

#### [NEW] [storage/models.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/storage/models.py)

Python dataclasses:
- `RawPost` — Raw scraped data
- `ParsedPost` — After extraction (role, experience, location, skills)
- `FilteredPost` — After passing all filters
- `Notification` — Telegram message record

---

### Notifications Module

#### [NEW] [notifications/telegram.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/notifications/telegram.py)

Telegram notification sender:
- Uses `python-telegram-bot` library (async)
- Formats message using the specified template:
  ```
  🚨 New AI Opportunity
  
  📋 Role: {role}
  📍 Location: {location}
  🎯 Experience: {experience}
  🛠 Skills: {skills}
  👤 Author: {author}
  🔗 Link: {url}
  ```
- Sends with `parse_mode='HTML'` for formatting
- Handles rate limiting (Telegram allows ~30 msgs/second)
- Batches notifications if many posts found in one run
- Sends a summary at the end: "✅ Run complete: X new opportunities found"

---

### Main Pipeline

#### [NEW] [main.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/main.py)

Orchestrator that runs the full pipeline:

```
1. Initialize database
2. Load configuration
3. For each keyword:
   a. Scrape LinkedIn Posts search results
   b. Parse each post (extract role, exp, location, skills)
   c. Filter posts (experience, location, hiring signal)
   d. Deduplicate against database
   e. Store new posts in database
4. For all new posts:
   a. Format Telegram message
   b. Send notification
   c. Record notification in database
5. Log run statistics
6. Close browser
```

Supports CLI arguments:
- `--once` — Run once and exit
- `--dry-run` — Scrape and parse but don't send notifications
- `--keywords "keyword1,keyword2"` — Override keywords for this run

---

### Scheduler

#### [NEW] [scheduler.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/scheduler.py)

APScheduler-based runner:
- Runs `main.py` pipeline every hour
- Configurable interval
- Graceful shutdown on Ctrl+C
- Logs next scheduled run time
- Error recovery — if a run fails, log error and continue scheduling

---

### LLM Module (V2 — Future)

#### [NEW] [llm/extractor.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/llm/extractor.py)

Structured extraction using LLM:
- Input: Raw post text
- Output: `{role, experience_min, experience_max, locations[], skills[]}`
- Falls back to regex parser if LLM fails

#### [NEW] [llm/classifier.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/llm/classifier.py)

Post classification:
- Determines if post is: hiring, discussion, advertisement, conference
- Output: `{is_hiring: bool, confidence: float, category: str}`

#### [NEW] [llm/scorer.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/llm/scorer.py)

Relevance scoring:
- Compares post requirements against user profile
- Output: `{score: 0-100, reason: str}`
- Configurable minimum score threshold

#### [NEW] [llm/summarizer.py](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/llm/summarizer.py)

Post summarization for Telegram:
- Converts verbose recruiter posts into concise summaries
- Used in notification formatting when enabled

---

### Project Files

#### [NEW] [requirements.txt](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/requirements.txt)

```
playwright==1.52.0
playwright-stealth==1.0.6
python-telegram-bot==21.10
apscheduler==3.11.0
python-dotenv==1.1.0
aiohttp==3.11.18
pydantic==2.11.3
```

#### [NEW] [.env](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/.env)

```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
OPENROUTER_API_KEY=your_key_here  # V2 only
```

#### [NEW] [README.md](file:///c:/Users/naver/Music/LangChain/linkedin_monitor/README.md)

Setup and usage instructions covering:
- Prerequisites (Python 3.10+)
- Installation steps
- Telegram bot setup walkthrough
- LinkedIn login (first-time persistent profile setup)
- Configuration customization
- Running the monitor
- Troubleshooting

---

## Implementation Phases

### Phase 1 — Foundation (Build First)
1. Project structure + `config.py` + `requirements.txt` + `.env`
2. `storage/models.py` + `storage/database.py` (SQLite schema)
3. `notifications/telegram.py` (test with a simple message)

### Phase 2 — Scraper
4. `scraper/stealth.py` (anti-detection setup)
5. `scraper/linkedin.py` (core scraping logic)
6. Manual test: scrape posts for 1 keyword, print results

### Phase 3 — Processing
7. `processing/parser.py` (regex extraction)
8. `processing/filters.py` (experience + location filters)
9. `processing/dedup.py` (deduplication logic)

### Phase 4 — Pipeline Integration
10. `main.py` (wire everything together)
11. End-to-end test: scrape → parse → filter → dedup → notify

### Phase 5 — Scheduling + Polish
12. `scheduler.py` (hourly runs)
13. `README.md` (documentation)
14. Error handling, logging, edge cases

### Phase 6 — LLM Features (V2, Later)
15. `llm/` module (extraction, classification, scoring, summarization)

---

## Verification Plan

### Automated Tests
1. **Database tests**: Insert, dedup check, stats query
2. **Parser tests**: Test regex extraction against sample post texts
3. **Filter tests**: Experience/location filtering edge cases
4. **Telegram test**: Send a test notification to verify bot setup

### Manual Verification
1. **First run**: Execute `python main.py --once` and verify:
   - Browser launches and navigates correctly
   - Posts are scraped and printed to console
   - Telegram notifications arrive with correct formatting
   - Database contains the scraped posts
2. **Second run**: Execute again and verify:
   - Previously seen posts are NOT re-notified
   - Only new posts trigger notifications
3. **Dry run**: Execute `python main.py --once --dry-run` to verify parsing without sending
4. **Scheduler**: Run `python scheduler.py` and verify it triggers on schedule
