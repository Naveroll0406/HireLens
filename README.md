# HireLens 🔍

Automated LinkedIn hiring-post monitor for AI / GenAI / LLM / RAG roles — **rule-based, no LLM required**.

Recruiters and founders often post openings to their feed before (or instead of) creating a job listing. HireLens scrapes LinkedIn *Posts* search for your keywords, extracts the role, experience, location, skills and apply links with regex, **scores** each post 0-100, deduplicates aggressively, and surfaces the good ones in a local dashboard (and optionally Telegram).

## 🚀 Key Features

- **Relevance score, not gates** — every post gets a 0-100 score from additive signals (AI title, hiring phrase, target city, experience fit, apply link, seniority…). Nothing is silently dropped: rejected posts are stored with their score and a breakdown you can read in the dashboard, so tuning is evidence-based.
- **Three-layer dedup** — LinkedIn URN → exact (author, content) hash → **SimHash** near-duplicate matching that catches the same JD cross-posted by several recruiters, with a semantic tie-break so "2-4 yrs" and "5-7 yrs" versions of one template stay separate.
- **Accurate extraction** — word-bounded keyword matching (no more `apply`⊂`applying`), the title is read *right after* "Hiring:/Role:/Looking for", the strictest experience minimum wins, fresher mentions respect negation, and city names inside "Delhi Public School" / "IIT Bombay" are ignored.
- **Account protection** — detects LinkedIn checkpoint / "unusual activity" pages, stops the run, marks it `blocked`, and the scheduler skips the next runs. Per-keyword retries with exponential backoff. A 24h search window on normal runs and a 7-day deep scan once a day.
- **Absolute post times** — "2h" becomes a real `posted_at`; the dashboard sorts by when it was posted, not when you found it.
- **Workflow dashboard** — Saved / Applied / Hidden / Not-relevant per post, full-text search with FTS5 (`python rag -senior`), group by recruiter, score threshold slider, CSV/JSON export.
- **Feedback loop** — marking a post "Not relevant" with a reason feeds a phrase report (`python main.py --feedback` or the Feedback tab). Promote recurring phrases to `config.py` and the rules get better every week.
- **Telegram notifications** (optional) — the best posts of each run pushed to your phone, stdlib only.
- **Golden test corpus** — `tests/fixtures/posts.jsonl` holds real-shaped posts with expected extraction and accept/reject; every rule change is checked against it.

## 🛠️ Tech Stack

Python 3.10+ · Playwright (persistent, logged-in Chromium profile) · SQLite (WAL, FTS5) · Streamlit · pandas. Dev: pytest, ruff.

## ⚙️ How It Works

```
Scrape → Deduplicate → Parse → Score → Store → Notify → Log
```

1. **Scrape** — for each active keyword, open LinkedIn Posts search (sorted by date, 24h or 7d window), scroll like a human, expand "…more", extract post containers by structure (resilient to LinkedIn's class-name scrambling).
2. **Deduplicate** — URN, content hash, SimHash (see `processing/dedup.py`).
3. **Parse** — `processing/parser.py` pulls role, experience range, locations, skills, emails, URLs (shorteners resolved), hiring signal, seniority, posted-at.
4. **Score** — `processing/scoring.py` applies `config.SCORE_WEIGHTS`; posts at/above `RELEVANCE_THRESHOLD` (default 50, adjustable in the dashboard) are shown as hiring posts.
5. **Store** — everything, including rejects, goes to SQLite with the score and breakdown.
6. **Notify** — posts ≥ `NOTIFY_MIN_SCORE` go to Telegram if configured.
7. **Log** — exactly one `run_log` row per run with counts, status (`ok` / `error` / `blocked`) and whether it was a deep scan.

## 💻 Getting Started

### Prerequisites
- Python 3.10+
- A LinkedIn account (a secondary one is safer — automation is against LinkedIn's ToS and accounts do get restricted)

### Installation
```bash
git clone https://github.com/Naveroll0406/HireLens.git
cd HireLens
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # optional: add Telegram token + chat id
```

### Usage

**Dashboard** (view results, run the scraper, manage keywords/settings):
```bash
streamlit run dashboard.py
```

The dashboard is split into four pieces:

| File | Responsibility |
|---|---|
| `dashboard.py` | Streamlit wiring, database reads, filter state |
| `ui/theme.py` | the whole stylesheet — design tokens, surfaces, animations |
| `ui/components.py` | pure data → HTML helpers (cards, tiles, chips); unit-tested |
| `ui/runner.py` | the background scraper thread and its state |

Styling is centralised: `dashboard.py` only emits semantic class names
(`hl-card`, `hl-chip`…), never colours. Native Streamlit widgets are themed
through `.streamlit/config.toml` so they match the custom surfaces.
Animations follow spring curves and are disabled under
`prefers-reduced-motion`.

**One-off run / CLI:**
```bash
python main.py                 # run once with the active keywords
python main.py --deep          # force the 7-day window
python main.py --dry-run       # scrape, parse & score but write nothing
python main.py --feedback      # recurring phrases from "not relevant" feedback
python main.py --stats         # database statistics
python main.py --add-keyword "Agentic AI Engineer"
```

**Autopilot scheduler** (separate terminal):
```bash
python scheduler.py --run-now  # every 60 min by default; change it in the dashboard
```
The first run opens a browser window — log in once; the session is kept in `data/browser_profile/`.

### Tests & lint
```bash
pytest          # unit tests + golden corpus (+ dashboard/pipeline tests when streamlit/playwright are installed)
ruff check .
```

## 🎛️ Tuning without AI

Everything lives in `config.py`:

| What | Where |
|---|---|
| Search keywords (defaults) | `DEFAULT_KEYWORDS` (editable in the dashboard too) |
| Target cities / Remote | `TARGET_LOCATIONS`, `LOCATION_ALIASES`; non-target cities in `OTHER_LOCATIONS` |
| Your experience band | `EXPERIENCE_MIN`, `EXPERIENCE_MAX` (or the dashboard slider) |
| Score weights & threshold | `SCORE_WEIGHTS`, `RELEVANCE_THRESHOLD` |
| Hiring / non-hiring phrases | `HIRING_SIGNALS`, `NON_HIRING_SIGNALS`, `ABSOLUTE_REJECT_PHRASES` |
| Title anchors, AI titles, non-AI titles | `HIRING_ANCHORS`, `AI_ROLE_KEYWORDS`, `NON_AI_ROLE_TITLES` |
| Scrape windows, retries, block markers | `SEARCH_WINDOW_*`, `SEARCH_MAX_RETRIES`, `BLOCK_*` |

The loop: mark misfires **Not relevant** with a reason → `python main.py --feedback` → add the recurring phrase to the right list → add the post to `tests/fixtures/posts.jsonl` with the expected result → `pytest` stays green.

---

*Built to uncover the hidden AI job market — with regexes, not tokens.*
