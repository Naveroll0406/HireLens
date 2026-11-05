"""
HireLens — Streamlit dashboard.

Visualises scraped hiring posts, runs the scraper against a pasted LinkedIn
search URL, and exposes the keyword / filter / scheduler settings.

Layout lives in :mod:`ui.components`, styling in :mod:`ui.theme`, and the
background scraper in :mod:`ui.runner`; this module is the wiring plus the
database reads.

Usage:
  streamlit run dashboard.py
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure the project root is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from processing import llm_scoring
from processing.parser import resolve_author_headline, resolve_author_name
from storage.database import POST_STATUSES, Database
from ui import components as C
from ui import runner, theme

STATUS_LABELS = {
    "new": "🆕 New",
    "saved": "⭐ Saved",
    "applied": "✅ Applied",
    "hidden": "🙈 Hidden",
    "not_relevant": "🚫 Not relevant",
}

# ---------------------------------------------------------------------------
# Page configuration + theme
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="HireLens — AI hiring radar",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject()


@dataclass
class Filters:
    """Everything the sidebar controls, passed down to the queries."""
    search_text: str = ""
    hiring_only: bool = True
    location: str = "All"
    max_results: int = 50
    exp_range: tuple[int, int] = (0, 15)
    min_score: int = 0
    statuses: list[str] = field(default_factory=list)
    group_by_author: bool = False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection | None:
    """Open a read connection, or None when the database does not exist yet."""
    db_path = config.DATABASE_PATH
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_resource
def ensure_db() -> bool:
    """Initialise the schema once per server process, not once per rerun."""
    with closing(Database(config.DATABASE_PATH)) as db:
        db.init_db()
        db.seed_default_keywords(config.DEFAULT_KEYWORDS)
    return True


def invalidate_caches() -> None:
    """Drop cached aggregates after anything writes to the database."""
    for fn in (get_stats, get_found_locations, get_top_skills, get_keywords,
               get_location_counts):
        fn.clear()


@st.cache_data(ttl=300, show_spinner=False)
def gemini_status() -> tuple[bool, str]:
    """Is the Gemini key usable?  Cached - it is a real network round trip."""
    return llm_scoring.check_key()


@st.cache_data(ttl=60, show_spinner=False)
def fts_available() -> bool:
    """Whether the posts_fts virtual table exists (SQLite built with FTS5)."""
    conn = get_db_connection()
    if conn is None:
        return False
    with closing(conn):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='posts_fts'"
        ).fetchone()
    return row is not None


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Words are AND-ed; a leading '-' negates ("python rag -senior").
    Everything is quoted so user input cannot break the query grammar.
    """
    terms = []
    for tok in text.split():
        neg = tok.startswith("-") and len(tok) > 1
        word = (tok[1:] if neg else tok).replace('"', "")
        if not word:
            continue
        terms.append(('NOT "' if neg else '"') + word + '"*')
    # A query that is only negations is invalid FTS5; anchor it with a wildcard.
    if terms and all(t.startswith("NOT") for t in terms):
        terms.insert(0, '"*"')
    return " ".join(terms)


def _post_filters_sql(f: Filters) -> tuple[str, list]:
    """Shared WHERE clause for the post views."""
    where = " WHERE 1=1"
    params: list = []

    if f.hiring_only:
        where += " AND is_hiring = 1"
    if f.min_score > 0:
        where += " AND COALESCE(relevance_score, 0) >= ?"
        params.append(f.min_score)
    if f.statuses:
        placeholders = ",".join("?" * len(f.statuses))
        where += f" AND COALESCE(status, 'new') IN ({placeholders})"
        params.extend(f.statuses)

    if f.search_text.strip():
        if fts_available():
            where += " AND id IN (SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?)"
            params.append(_fts_query(f.search_text))
        else:
            where += " AND (content LIKE ? OR role LIKE ? OR author_name LIKE ?)"
            like = f"%{f.search_text}%"
            params.extend([like, like, like])

    if f.location and f.location != "All":
        where += " AND locations LIKE ?"
        params.append(f'%"{f.location}"%')

    # Posts with no stated experience are always shown.
    where += " AND (experience_min IS NULL OR experience_min <= ?)"
    params.append(f.exp_range[1])
    where += " AND (experience_max IS NULL OR experience_max >= ?)"
    params.append(f.exp_range[0])
    return where, params


# Newest *posted* first; fall back to when we found it for older rows.
_ORDER_BY = " ORDER BY COALESCE(posted_at, created_at) DESC, id DESC"


def load_posts(f: Filters) -> pd.DataFrame:
    """Load posts matching the sidebar filters."""
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    where, params = _post_filters_sql(f)
    with closing(conn):
        return pd.read_sql_query(
            "SELECT * FROM posts" + where + _ORDER_BY + " LIMIT ?",
            conn, params=params + [f.max_results],
        )


def load_new_posts(f: Filters, since_run_id: int | None = None) -> pd.DataFrame:
    """Posts from the latest run, or everything after *since_run_id*."""
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    where, params = _post_filters_sql(f)
    if since_run_id is not None:
        where += " AND run_id > ?"
        params.append(since_run_id)
    else:
        where += " AND run_id = (SELECT MAX(run_id) FROM posts)"
    with closing(conn):
        return pd.read_sql_query("SELECT * FROM posts" + where + _ORDER_BY, conn, params=params)


def set_post_status(post_id: int, status: str, feedback_reason: str = "") -> None:
    """Persist a status change (and feedback when marking not relevant)."""
    with closing(Database(config.DATABASE_PATH)) as db:
        db.init_db()
        db.set_post_status(int(post_id), status)
        if status == "not_relevant":
            db.add_feedback(int(post_id), "not_relevant", feedback_reason)
        elif status in ("saved", "applied"):
            db.add_feedback(int(post_id), "relevant", "")
    invalidate_caches()


def load_feedback(limit: int = 100) -> pd.DataFrame:
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    with closing(conn):
        try:
            return pd.read_sql_query(
                "SELECT f.created_at, f.verdict, f.reason, f.role, f.post_id "
                "FROM feedback f ORDER BY f.created_at DESC LIMIT ?",
                conn, params=[limit],
            )
        except (pd.errors.DatabaseError, sqlite3.DatabaseError):
            return pd.DataFrame()


def feedback_phrases() -> list[tuple[str, int]]:
    with closing(Database(config.DATABASE_PATH)) as db:
        db.init_db()
        return db.feedback_phrase_counts(min_count=2)


def get_setting(key: str, default: str) -> str:
    with closing(Database(config.DATABASE_PATH)) as db:
        db.init_db()
        return db.get_setting(key, default)


def set_setting(key: str, value) -> None:
    with closing(Database(config.DATABASE_PATH)) as db:
        db.init_db()
        db.set_setting(key, str(value))


def export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Flat, human-readable columns for CSV/JSON export."""
    cols = [
        "id", "relevance_score", "status", "role", "author_name", "author_headline",
        "locations", "experience_min", "experience_max", "skills", "emails",
        "primary_url", "extracted_urls", "company_url", "author_url", "post_url",
        "posted_at", "created_at", "keyword_matched", "filter_reason", "content",
    ]
    out = df[[c for c in cols if c in df.columns]].copy()
    for col in ("locations", "skills", "emails", "extracted_urls"):
        if col in out.columns:
            out[col] = out[col].apply(lambda v: ", ".join(C.parse_json_list(v)))
    return out


def load_run_logs(limit: int = 20) -> pd.DataFrame:
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    with closing(conn):
        return pd.read_sql_query(
            "SELECT * FROM run_log ORDER BY started_at DESC LIMIT ?", conn, params=[limit]
        )


def rows_needing_llm_score(limit: int = 200) -> list[tuple[int, str, str]]:
    """(id, author, content) for posts the LLM has not judged yet."""
    conn = get_db_connection()
    if conn is None:
        return []
    with closing(conn):
        rows = conn.execute(
            "SELECT id, COALESCE(author_name,''), COALESCE(content,'') FROM posts "
            "WHERE COALESCE(scored_by,'rules') != 'gemini' "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [(int(r[0]), r[1], r[2]) for r in rows]


def save_llm_verdict(post_id: int, verdict, threshold: int) -> None:
    """Persist one Gemini verdict, keeping the original rule score."""
    score = min(verdict.score, 20) if not verdict.is_hiring else verdict.score
    with closing(Database(config.DATABASE_PATH)) as db:
        db.init_db()
        db.conn.execute(
            "UPDATE posts SET rule_score = COALESCE(NULLIF(rule_score,0), relevance_score), "
            "relevance_score = ?, scored_by = 'gemini', filter_reason = ?, "
            "is_hiring = ?, role = COALESCE(NULLIF(?,''), role) WHERE id = ?",
            (score, f"gemini: {verdict.reason}", int(score >= threshold),
             verdict.role, post_id),
        )
        db.conn.commit()


def latest_run_id() -> int:
    """Highest run_log id, used to isolate the posts a new run produces."""
    conn = get_db_connection()
    if conn is None:
        return 0
    with closing(conn):
        row = conn.execute("SELECT MAX(id) FROM run_log").fetchone()
    return int(row[0] or 0)


@st.cache_data(ttl=30, show_spinner=False)
def get_stats() -> dict:
    """Headline counters for the stat row."""
    empty = {"total_posts": 0, "hiring_posts": 0, "total_runs": 0,
             "unique_locations": 0, "saved": 0, "applied": 0}
    conn = get_db_connection()
    if conn is None:
        return empty
    with closing(conn):
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM posts")
        total_posts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM posts WHERE is_hiring = 1")
        hiring_posts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM run_log")
        total_runs = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(status,'new'), COUNT(*) FROM posts GROUP BY 1")
        by_status = dict(cur.fetchall())
        cur.execute("SELECT locations FROM posts WHERE locations IS NOT NULL AND locations != '[]'")
        found = set()
        for row in cur.fetchall():
            found.update(C.parse_json_list(row[0]))
    return {
        "total_posts": total_posts,
        "hiring_posts": hiring_posts,
        "total_runs": total_runs,
        "unique_locations": len(found),
        "saved": int(by_status.get("saved", 0)),
        "applied": int(by_status.get("applied", 0)),
    }


@st.cache_data(ttl=30, show_spinner=False)
def get_found_locations() -> list[str]:
    counts = get_location_counts()
    return sorted(counts)


@st.cache_data(ttl=30, show_spinner=False)
def get_location_counts() -> dict[str, int]:
    conn = get_db_connection()
    if conn is None:
        return {}
    counts: dict[str, int] = {}
    with closing(conn):
        rows = conn.execute(
            "SELECT locations FROM posts WHERE locations IS NOT NULL AND locations != '[]'"
        ).fetchall()
    for row in rows:
        for loc in C.parse_json_list(row[0]):
            counts[loc] = counts.get(loc, 0) + 1
    return counts


@st.cache_data(ttl=30, show_spinner=False)
def get_top_skills(limit: int = 15) -> list[tuple[str, int]]:
    conn = get_db_connection()
    if conn is None:
        return []
    counts: dict[str, int] = {}
    with closing(conn):
        rows = conn.execute(
            "SELECT skills FROM posts WHERE skills IS NOT NULL AND skills != '[]'"
        ).fetchall()
    for row in rows:
        for skill in C.parse_json_list(row[0]):
            counts[skill] = counts.get(skill, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]


@st.cache_data(ttl=30, show_spinner=False)
def get_keywords() -> list[dict]:
    conn = get_db_connection()
    if conn is None:
        return []
    with closing(conn):
        rows = conn.execute("SELECT keyword, active FROM keywords ORDER BY keyword").fetchall()
    return [{"keyword": r[0], "active": bool(r[1])} for r in rows]


# ---------------------------------------------------------------------------
# Location catalogue (base list + anything the user adds at runtime)
# ---------------------------------------------------------------------------

BASE_LOCATIONS = list(dict.fromkeys(
    list(config.TARGET_LOCATIONS) + ["India"] + list(getattr(config, "OTHER_LOCATIONS", []))[:12]
))


def all_locations() -> list[str]:
    """Base catalogue plus custom locations, which persist across reruns.

    The previous version appended to a module-level list, which Streamlit
    rebuilt on every rerun - so a custom location vanished immediately.
    """
    custom = st.session_state.setdefault("custom_locations", [])
    return list(dict.fromkeys(BASE_LOCATIONS + custom))


def selected_locations() -> list[str]:
    """Locations currently ticked in the sidebar editor."""
    return [loc for loc in all_locations() if st.session_state.get(f"loc_{loc}", True)]


# ---------------------------------------------------------------------------
# Card data extraction
# ---------------------------------------------------------------------------

def _detect_platform(url: str) -> str:
    if not url:
        return ""
    lowered = url.lower()
    for domain, name in config.ATS_PLATFORMS.items():
        if domain in lowered:
            return name
    return ""


def _clean(value, fallback=""):
    """Row value with pandas NaN collapsed to *fallback*."""
    try:
        if value is None or pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    return value if value not in ("", None) else fallback


def card_data(row) -> dict:
    """Flatten one posts row into the plain dict `ui.components.job_card` wants."""
    role = _clean(row.get("role")) or _clean(row.get("keyword_matched")) or "Job opportunity"

    locations = C.parse_json_list(row.get("locations"))
    primary_url = _clean(row.get("primary_url"))
    extra_urls = C.parse_json_list(row.get("extracted_urls"))

    # Older rows predate primary_url/extracted_urls and only have apply_links.
    if not primary_url and not extra_urls:
        legacy = C.parse_json_list(row.get("apply_links"))
        if legacy:
            primary_url, extra_urls = legacy[0], legacy[1:]

    posted_at = _clean(row.get("posted_at"))
    created_at = _clean(row.get("created_at"))
    stamp = posted_at or created_at
    when = C.relative_time(stamp)
    if posted_at:
        when = when or C.format_timestamp(posted_at)
    elif when:
        when = f"found {when}"

    content = _clean(row.get("content"))
    author_url = _clean(row.get("author_url"))
    # Rows scraped while the author selectors were stale have an empty
    # author_name; recover it from the post structure instead of showing
    # every card as "Unknown".
    author = resolve_author_name(str(_clean(row.get("author_name"))),
                                 str(content), str(author_url))
    headline = resolve_author_headline(str(_clean(row.get("author_headline"))),
                                       str(content), author)

    platform = _detect_platform(str(primary_url))
    return {
        "id": int(_clean(row.get("id"), 0) or 0),
        "role": role,
        "author": author or "Unknown",
        "headline": headline,
        "author_url": author_url,
        "post_url": _clean(row.get("post_url")),
        "location": ", ".join(locations[:3]) if locations else "",
        "experience": C.format_experience(row.get("experience_min"), row.get("experience_max")),
        "when": when,
        "when_exact": C.format_timestamp(stamp),
        "platform": f"LinkedIn + {platform}" if platform else "LinkedIn",
        "skills": C.parse_json_list(row.get("skills")),
        "emails": C.parse_json_list(row.get("emails")),
        "primary_url": primary_url,
        "extra_urls": extra_urls,
        "content": content,
        "score": int(_clean(row.get("relevance_score"), 0) or 0),
        "status": _clean(row.get("status")) or "new",
        "scored_by": _clean(row.get("scored_by")) or "rules",
        "rule_score": int(_clean(row.get("rule_score"), 0) or 0),
        "filter_reason": _clean(row.get("filter_reason")),
    }


# ---------------------------------------------------------------------------
# UI — masthead and run console
# ---------------------------------------------------------------------------

def render_masthead() -> None:
    stats = get_stats()
    running = runner.is_running()
    subtitle = "Automated discovery of AI, GenAI, LLM & RAG hiring posts on LinkedIn"
    pill = f"{stats['hiring_posts']} live roles" if stats["hiring_posts"] else ""
    st.markdown(C.masthead(running, subtitle, pill), unsafe_allow_html=True)


@st.fragment(run_every=1.5)
def _live_progress() -> None:
    """Poll the runner while a scrape is in flight.

    Replaces the old `<meta http-equiv="refresh">`, which reloaded the whole
    page and destroyed the session (and with it the run state).
    """
    if not runner.is_running():
        st.rerun()  # full-app rerun so the finished results render
        return
    elapsed = runner.elapsed_seconds()
    st.markdown(
        f'<div class="hl-chip hl-chip-accent">⏳ Scraping LinkedIn — '
        f'{int(elapsed)}s elapsed</div><div class="hl-progress"></div>',
        unsafe_allow_html=True,
    )


def render_run_console(f: Filters) -> None:
    """URL box, run button, and the outcome of the last run."""
    running = runner.is_running()

    col_url, col_btn = st.columns([4, 1], vertical_alignment="bottom")
    with col_url:
        url = st.text_input(
            "LinkedIn search URL",
            placeholder="https://www.linkedin.com/search/results/content/?keywords=...",
            help="LinkedIn → search your keywords → open the **Posts** tab → copy the URL.",
            key="linkedin_url_input",
        )
    with col_btn:
        clicked = st.button(
            "⏳ Running…" if running else "🚀 Run scraper",
            disabled=running, width="stretch", type="primary",
            key="run_scraper_btn",
        )

    if clicked:
        cleaned = (url or "").strip()
        if not cleaned:
            st.warning("Paste a LinkedIn **Posts** search URL first.")
        elif not C.is_linkedin_search_url(cleaned):
            # Previously any string was handed straight to Playwright.
            st.error("That does not look like a LinkedIn URL. It should start with "
                     "`https://www.linkedin.com/`.")
        else:
            started = runner.start(
                url=cleaned,
                since_run_id=latest_run_id(),
                filter_locations=selected_locations(),
                filter_experience=f.exp_range,
            )
            if started:
                st.rerun()
            else:
                st.info("A scrape is already running.")

    if running:
        _live_progress()
        st.info("A browser window is open and scrolling LinkedIn. "
                "This panel updates on its own — leave the tab open.")
        return

    snap = runner.snapshot()
    if snap["error"]:
        st.error(f"The run failed — {snap['error']}")
        return

    stats = snap["stats"]
    if not stats:
        return

    cols = st.columns(5)
    tiles = [
        ("📄", stats.get("posts_found", 0), "Scraped", "rgba(109,140,255,.35)"),
        ("♻️", stats.get("duplicates_removed", 0), "Duplicates", "rgba(160,107,255,.3)"),
        ("🚫", stats.get("filtered_out", 0), "Filtered out", "rgba(255,182,72,.3)"),
        ("🆕", stats.get("new_posts", 0), "New posts", "rgba(56,211,159,.35)"),
        ("⏱", f"{stats.get('duration', 0):.0f}s", "Duration", "rgba(61,219,217,.3)"),
    ]
    peak = max([t[1] for t in tiles[:4] if isinstance(t[1], int)] + [1])
    for col, (icon, value, label, tint) in zip(cols, tiles):
        fill = int(value / peak * 100) if isinstance(value, int) else 60
        with col:
            st.markdown(C.stat_tile(icon, value, label, 0, fill, tint), unsafe_allow_html=True)

    if stats.get("blocked"):
        st.error("🚫 LinkedIn challenged this run. Open the browser profile, clear the "
                 "security check, and wait a while before running again.")
    for err in (stats.get("errors") or [])[:3]:
        st.warning(f"⚠️ {str(err)[:200]}")
    if stats.get("notified"):
        st.caption(f"📨 {stats['notified']} post(s) sent to Telegram.")


def render_stat_row() -> None:
    stats = get_stats()
    total = max(stats["total_posts"], 1)
    tiles = [
        ("📄", stats["total_posts"], "Posts captured", 100, "rgba(109,140,255,.35)", ""),
        ("🎯", stats["hiring_posts"], "Hiring posts",
         int(stats["hiring_posts"] / total * 100), "rgba(160,107,255,.32)",
         f"{int(stats['hiring_posts'] / total * 100)}% of total"),
        ("⭐", stats["saved"] + stats["applied"], "Saved / applied",
         int((stats["saved"] + stats["applied"]) / total * 100), "rgba(56,211,159,.32)",
         f"{stats['applied']} applied"),
        ("📍", stats["unique_locations"], "Locations seen", 70, "rgba(61,219,217,.3)",
         f"{stats['total_runs']} runs"),
    ]
    for i, (col, (icon, value, label, fill, tint, delta)) in enumerate(zip(st.columns(4), tiles)):
        with col:
            st.markdown(C.stat_tile(icon, value, label, i, fill, tint, delta),
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# UI — job cards
# ---------------------------------------------------------------------------

def render_job_card(row, key_suffix: str = "all", index: int = 0) -> None:
    """One post card plus its workflow controls."""
    data = card_data(row)
    st.markdown(C.job_card(data, index), unsafe_allow_html=True)

    post_id = data["id"]
    if not post_id:
        return

    status = data["status"]
    with st.expander("Score breakdown · full post · mark this post", expanded=False):
        if data["filter_reason"]:
            st.caption("Why this score: " + str(data["filter_reason"]).replace(", ", "  ·  "))
        if data["content"] and len(str(data["content"])) > 320:
            st.text_area("Full post", value=str(data["content"]), height=220,
                         disabled=True, key=f"full_{key_suffix}_{post_id}",
                         label_visibility="collapsed")
        post_url = C.safe_url(data["post_url"])
        if post_url:
            st.markdown(f"[Open the original post on LinkedIn ↗]({post_url})")

        c1, c2, c3, c4 = st.columns(4)
        if c1.button("⭐ Save", key=f"save_{key_suffix}_{post_id}",
                     width="stretch", disabled=(status == "saved")):
            set_post_status(post_id, "saved")
            st.rerun()
        if c2.button("✅ Applied", key=f"applied_{key_suffix}_{post_id}",
                     width="stretch", disabled=(status == "applied")):
            set_post_status(post_id, "applied")
            st.rerun()
        if c3.button("🙈 Hide", key=f"hide_{key_suffix}_{post_id}",
                     width="stretch", disabled=(status == "hidden")):
            set_post_status(post_id, "hidden")
            st.rerun()
        if c4.button("↩ Reset", key=f"reset_{key_suffix}_{post_id}",
                     width="stretch", disabled=(status == "new")):
            set_post_status(post_id, "new")
            st.rerun()

        reason = st.text_input(
            "Not relevant — why? (tunes the rules)",
            key=f"nr_reason_{key_suffix}_{post_id}",
            placeholder="e.g. webinar promo / recruiter spam / actually a Java role",
        )
        if st.button("🚫 Mark not relevant", key=f"nr_{key_suffix}_{post_id}",
                     disabled=(status == "not_relevant")):
            set_post_status(post_id, "not_relevant", reason)
            st.rerun()


# ---------------------------------------------------------------------------
# UI — sidebar
# ---------------------------------------------------------------------------

def _side_title(icon: str, text: str) -> None:
    st.markdown(f'<div class="hl-side-title">{icon} {C.esc(text)}</div>',
                unsafe_allow_html=True)


def render_sidebar() -> Filters:
    """Draw the sidebar and return the active filter set."""
    with st.sidebar:
        st.markdown(
            '<div class="hl-brand" style="margin-bottom:.9rem;">'
            '<div class="hl-logo" style="width:34px;height:34px;flex:0 0 34px;font-size:1rem;">🔍</div>'
            '<div><div class="hl-wordmark" style="font-size:1.1rem;">HireLens</div></div></div>',
            unsafe_allow_html=True,
        )

        _side_title("🔎", "Search & filters")
        search_text = st.text_input(
            "Search posts",
            placeholder="python rag -senior" if fts_available() else "role, skill or author…",
            help="Full-text search. Words are AND-ed; prefix with - to exclude."
                 if fts_available() else None,
            key="search_filter",
        )

        hiring_only = st.checkbox("Only posts above the threshold", value=True,
                                  key="hiring_only")

        saved_threshold = int(get_setting("relevance_threshold", str(config.RELEVANCE_THRESHOLD)))
        min_score = st.slider(
            "Minimum relevance score", 0, 100, saved_threshold, 5,
            help="Filters this view, and is reused as the pass/fail threshold on the next scrape.",
            key="min_score",
        )
        if min_score != saved_threshold:
            set_setting("relevance_threshold", min_score)

        status_filter = st.multiselect(
            "Status", options=list(POST_STATUSES), default=["new", "saved", "applied"],
            format_func=lambda v: STATUS_LABELS.get(v, v),
            help="Hidden and not-relevant posts are tucked away by default.",
            key="status_filter",
        )

        exp_range = st.slider("Experience (years)", 0, 15, (0, 15), key="exp_range",
                              help="Posts that do not state experience are always shown.")

        loc_options = ["All"] + get_found_locations()
        location_filter = st.selectbox("Location", loc_options, key="loc_filter")

        max_results = st.slider("Max results", 10, 200, 50, 10, key="max_results")
        group_by_author = st.checkbox(
            "Group by company / recruiter", value=False, key="group_by_author",
            help="Collapse cross-posts of one role by the same recruiter.",
        )

        st.markdown("---")

        # --- Scoring engine --------------------------------------------------
        _side_title("🧠", "Scoring engine")
        configured = llm_scoring.is_configured()
        use_llm = st.checkbox(
            "Use Gemini to score posts", value=(get_setting("use_llm_scoring", "1") == "1"),
            disabled=not configured, key="use_llm_scoring",
            help="When on, Gemini judges each new post and its score replaces the "
                 "rule engine's. The rule score is always kept alongside.",
        )
        set_setting("use_llm_scoring", "1" if use_llm else "0")

        if configured and use_llm:
            with st.expander("What am I looking for?", expanded=False):
                st.caption(
                    "Gemini scores every post against this. The more specific "
                    "you are - your skills, the seniority you want, the roles "
                    "you would turn down - the sharper the filtering."
                )
                profile = st.text_area(
                    "Your profile", height=140, key="candidate_profile_input",
                    value=get_setting("candidate_profile", llm_scoring.DEFAULT_PROFILE),
                    label_visibility="collapsed",
                    placeholder="e.g. 3 years Python, LangChain and RAG. Want "
                                "mid-level GenAI engineering roles in Hyderabad. "
                                "Not interested in pure data-analyst, QA or Java roles.",
                )
                c_save, c_reset = st.columns(2)
                if c_save.button("Save", width="stretch", key="save_profile"):
                    set_setting("candidate_profile", profile.strip()
                                or llm_scoring.DEFAULT_PROFILE)
                    st.success("Saved - it applies to the next scrape or re-score.")
                if c_reset.button("Reset", width="stretch", key="reset_profile"):
                    set_setting("candidate_profile", llm_scoring.DEFAULT_PROFILE)
                    st.rerun()

        if not configured:
            st.caption("No GEMINI_API_KEY found - using the rule engine.")
        elif use_llm:
            ok, detail = gemini_status()
            if ok:
                st.caption(f"✔ Gemini reachable - {detail}")
            else:
                st.caption(f"⚠ {detail} - falling back to rules.")
        else:
            st.caption("Rule engine only.")

        st.markdown("---")

        # --- Target locations ------------------------------------------------
        _side_title("📍", "Target locations")
        catalogue = all_locations()
        with st.expander(f"{len(selected_locations())} of {len(catalogue)} active", expanded=False):
            col_all, col_none = st.columns(2)
            # Writing the widget keys directly is the only thing that works:
            # once a checkbox has a key, Streamlit ignores its `value=`, which
            # is why the old Select-All / Clear-All buttons did nothing.
            if col_all.button("Select all", width="stretch", key="sel_all"):
                for loc in catalogue:
                    st.session_state[f"loc_{loc}"] = True
                st.rerun()
            if col_none.button("Clear all", width="stretch", key="clr_all"):
                for loc in catalogue:
                    st.session_state[f"loc_{loc}"] = False
                st.rerun()

            for loc in catalogue:
                st.checkbox(loc, value=st.session_state.get(f"loc_{loc}", True), key=f"loc_{loc}")

            custom_loc = st.text_input("Add a location", placeholder="e.g. Vizag", key="custom_loc")
            if st.button("➕ Add", key="add_loc_btn", width="stretch") and custom_loc.strip():
                name = custom_loc.strip()
                customs = st.session_state.setdefault("custom_locations", [])
                if name not in BASE_LOCATIONS and name not in customs:
                    customs.append(name)
                st.session_state[f"loc_{name}"] = True
                st.rerun()

        st.markdown("---")

        # --- Keywords --------------------------------------------------------
        keywords = get_keywords()
        active = [k for k in keywords if k["active"]]
        _side_title("🔑", f"Keywords · {len(active)} active")
        with st.expander("Manage keywords", expanded=False):
            for kw in keywords:
                col_kw, col_del = st.columns([4, 1])
                col_kw.markdown(
                    f'<span class="hl-chip {"hl-chip-mint" if kw["active"] else ""}">'
                    f'{C.esc(kw["keyword"])}</span>', unsafe_allow_html=True)
                if kw["active"] and col_del.button("🗑", key=f"del_{kw['keyword']}"):
                    with closing(Database(config.DATABASE_PATH)) as db:
                        db.init_db()
                        db.remove_keyword(kw["keyword"])
                    invalidate_caches()
                    st.rerun()

            new_kw = st.text_input("Add keyword", placeholder="e.g. MLOps Engineer", key="new_kw")
            if st.button("➕ Add keyword", width="stretch", key="add_kw_btn") and new_kw.strip():
                with closing(Database(config.DATABASE_PATH)) as db:
                    db.init_db()
                    db.add_keyword(new_kw.strip())
                invalidate_caches()
                st.rerun()

        st.markdown("---")

        # --- Settings --------------------------------------------------------
        _side_title("⚙️", "Settings")
        with closing(Database(config.DATABASE_PATH)) as db:
            db.init_db()
            current_interval = int(db.get_setting("run_interval_minutes",
                                                  str(config.RUN_INTERVAL_MINUTES)))
            new_interval = st.number_input(
                "Scheduler interval (minutes)", 1, 1440, current_interval,
                help="How often the background scheduler runs.", key="run_interval",
            )
            if new_interval != current_interval:
                db.set_setting("run_interval_minutes", str(new_interval))

            current_wait = int(db.get_setting("scroll_duration_seconds", "300"))
            new_wait = st.number_input(
                "Scroll duration (seconds)", 30, 600, current_wait,
                help="How long the browser scrolls to load posts.", key="scroll_duration",
            )
            if new_wait != current_wait:
                db.set_setting("scroll_duration_seconds", str(new_wait))

        db_path = config.DATABASE_PATH
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            st.caption(f"💾 {db_path.name} · {size_mb:.2f} MB")
        else:
            st.caption("No database yet — run the scraper first.")

        if st.checkbox("🔄 Auto-refresh (30s)", value=False, key="auto_refresh"):
            _auto_refresh()

    return Filters(
        search_text=search_text,
        hiring_only=hiring_only,
        location=location_filter,
        max_results=max_results,
        exp_range=exp_range,
        min_score=min_score,
        statuses=status_filter,
        group_by_author=group_by_author,
    )


@st.fragment(run_every=30)
def _auto_refresh() -> None:
    """Periodic full rerun, without reloading the page (and losing state)."""
    st.rerun()


# ---------------------------------------------------------------------------
# UI — analytics and history
# ---------------------------------------------------------------------------

def render_skills_chart() -> None:
    top_skills = get_top_skills(12)
    if not top_skills:
        st.info("No skills data yet — run the scraper first.")
        return
    df = pd.DataFrame(top_skills, columns=["Skill", "Count"])
    st.bar_chart(df.set_index("Skill"), horizontal=True, color=theme.ACCENT)


def render_locations_chart() -> None:
    counts = get_location_counts()
    if not counts:
        st.info("No location data yet.")
        return
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    df = pd.DataFrame(top, columns=["Location", "Count"])
    st.bar_chart(df.set_index("Location"), horizontal=True, color=theme.VIOLET)


def render_score_chart() -> None:
    """Distribution of relevance scores — shows whether the threshold is sane."""
    conn = get_db_connection()
    if conn is None:
        st.info("No score data yet.")
        return
    with closing(conn):
        df = pd.read_sql_query(
            "SELECT COALESCE(relevance_score,0) AS score FROM posts", conn)
    if df.empty:
        st.info("No score data yet.")
        return
    buckets = pd.cut(df["score"], bins=[-1, 19, 39, 59, 79, 100],
                     labels=["0-19", "20-39", "40-59", "60-79", "80-100"])
    counts = buckets.value_counts().sort_index()
    st.bar_chart(counts, color=theme.CYAN)


def render_rescore_panel(f: Filters) -> None:
    """Re-judge already-stored posts with Gemini, with live progress."""
    if not llm_scoring.is_configured():
        st.info("No GEMINI_API_KEY found, so stored posts keep their rule scores. "
                "Add the key to your .env and reload to enable this.")
        return

    pending = rows_needing_llm_score(limit=500)
    if not pending:
        if get_stats()["total_posts"] == 0:
            st.info("No posts stored yet. New posts are scored by Gemini "
                    "automatically as they are scraped.")
        else:
            st.success("Every stored post has already been scored by Gemini.")
        return

    st.caption(f"{len(pending)} post(s) still carry a rule-engine score. "
               "Re-scoring sends their text to Gemini - roughly one request "
               f"per {llm_scoring.BATCH_SIZE} posts.")
    how_many = st.slider("How many to re-score now", 5,
                         min(len(pending), 200), min(len(pending), 50), 5,
                         key="rescore_count")
    if not st.button(f"Re-score {how_many} posts", type="primary", key="rescore_btn"):
        return

    threshold = int(get_setting("relevance_threshold", str(config.RELEVANCE_THRESHOLD)))
    batch = pending[:how_many]
    done = 0
    bar = st.progress(0.0, text="Asking Gemini ...")
    for post_id, verdict in llm_scoring.rescore_rows(
            batch, target_locations=selected_locations(), experience_range=f.exp_range,
            profile=get_setting("candidate_profile", llm_scoring.DEFAULT_PROFILE)):
        save_llm_verdict(post_id, verdict, threshold)
        done += 1
        bar.progress(min(done / len(batch), 1.0), text=f"Re-scored {done}/{len(batch)}")
    bar.empty()

    invalidate_caches()
    if done:
        st.success(f"Re-scored {done} post(s) with Gemini.")
    else:
        st.warning("Gemini returned no verdicts - the posts keep their rule scores. "
                   "Check the key and your connection.")
    st.rerun()


def render_run_history() -> None:
    df = load_run_logs(10)
    if df.empty:
        st.markdown(
            C.empty_state("No runs yet", "Run history appears here after your first scrape.",
                          icon="&#128338;"),
            unsafe_allow_html=True)
        return

    def _num(row, col) -> int:
        val = row.get(col, 0)
        try:
            if pd.isna(val):
                return 0
        except (TypeError, ValueError):
            pass
        return int(val or 0)

    for i, (_, row) in enumerate(df.iterrows()):
        errors = row.get("errors", "")
        badge = ""
        if row.get("status") == "blocked":
            badge = "blocked"
        elif errors and str(errors) not in ("null", "[]", "None", "nan", ""):
            badge = "errors"
        st.markdown(
            C.run_row(i, row.get("started_at"), _num(row, "posts_found"),
                      _num(row, "duplicates_removed"), _num(row, "filtered_out"),
                      _num(row, "new_posts"), badge),
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# UI — post views
# ---------------------------------------------------------------------------

def _render_export_buttons(df: pd.DataFrame, key_suffix: str) -> None:
    export_df = export_frame(df)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ CSV", data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"hirelens_{key_suffix}_{stamp}.csv", mime="text/csv",
        width="stretch", key=f"csv_{key_suffix}",
    )
    c2.download_button(
        "⬇️ JSON",
        data=export_df.to_json(orient="records", indent=2, force_ascii=False).encode("utf-8"),
        file_name=f"hirelens_{key_suffix}_{stamp}.json", mime="application/json",
        width="stretch", key=f"json_{key_suffix}",
    )


def _render_cards(df: pd.DataFrame, key_suffix: str, group_by_author: bool) -> None:
    if not group_by_author:
        for i, (_, row) in enumerate(df.iterrows()):
            render_job_card(row, key_suffix, i)
        return

    index = 0
    for author, group in df.groupby(df["author_name"].fillna("Unknown"), sort=False):
        group = group.sort_values("relevance_score", ascending=False)
        if len(group) == 1:
            render_job_card(group.iloc[0], key_suffix, index)
            index += 1
            continue
        st.markdown(C.group_heading(str(author), len(group)), unsafe_allow_html=True)
        render_job_card(group.iloc[0], key_suffix, index)
        index += 1
        with st.expander(f"{len(group) - 1} more from {author}"):
            for _, row in group.iloc[1:].iterrows():
                render_job_card(row, key_suffix, 0)


_TABLE_COLUMNS = {
    "relevance_score": st.column_config.NumberColumn("Score", width="small"),
    "status": st.column_config.TextColumn("Status", width="small"),
    "primary_url": st.column_config.LinkColumn("Apply", display_text="Apply"),
    "posted_at": st.column_config.TextColumn("Posted"),
    "post_url": st.column_config.LinkColumn("Link", display_text="Open"),
    "role": st.column_config.TextColumn("Role", width="medium"),
    "author_name": st.column_config.TextColumn("Author", width="medium"),
    "locations": st.column_config.TextColumn("Locations", width="medium"),
    "skills": st.column_config.TextColumn("Skills", width="large"),
    "emails": st.column_config.TextColumn("Emails", width="medium"),
    "experience_min": st.column_config.NumberColumn("Exp min"),
    "experience_max": st.column_config.NumberColumn("Exp max"),
    "created_at": st.column_config.TextColumn("Found at"),
}


def render_posts_view(df: pd.DataFrame, key_suffix: str, f: Filters,
                      empty_title: str, empty_body: str,
                      steps: list[str] | None = None) -> None:
    if df.empty:
        st.markdown(C.empty_state(empty_title, empty_body, steps), unsafe_allow_html=True)
        return

    head, mode, export = st.columns([2, 1, 1], vertical_alignment="center")
    with head:
        top = int(df["relevance_score"].max()) if "relevance_score" in df else 0
        st.markdown(C.section_heading(f"{len(df)} opportunities",
                                      f"best match scores {top}"), unsafe_allow_html=True)
    with mode:
        view_mode = st.radio("View", ["Cards", "Table"], horizontal=True,
                             label_visibility="collapsed", key=f"view_mode_{key_suffix}")
    with export:
        _render_export_buttons(df, key_suffix)

    if view_mode == "Cards":
        _render_cards(df, key_suffix, f.group_by_author)
    else:
        display = [c for c in _TABLE_COLUMNS if c in df.columns]
        st.dataframe(df[display], width="stretch", hide_index=True,
                     column_config=_TABLE_COLUMNS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ensure_db()

    # The sidebar is drawn first so the run console sees the current filters;
    # previously the console ran first and handed the scraper stale (on the
    # first load, empty) location and experience filters.
    filters = render_sidebar()

    render_masthead()
    render_run_console(filters)
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
    render_stat_row()
    st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)

    tab_new, tab_all, tab_insights, tab_runs, tab_feedback = st.tabs([
        "🆕 Latest run", "📋 All posts", "📊 Insights", "🕐 Runs", "🧭 Feedback",
    ])

    with tab_new:
        new_df = load_new_posts(filters, since_run_id=runner.snapshot()["since_run_id"])
        render_posts_view(
            new_df, "new", filters,
            "Nothing new yet",
            "Paste a LinkedIn Posts search URL above and run the scraper — "
            "whatever it finds lands here first.",
            ["Search your keywords on LinkedIn",
             "Switch to the Posts tab",
             "Copy the URL and paste it above"],
        )

    with tab_all:
        df = load_posts(filters)
        render_posts_view(
            df, "all", filters,
            "No posts match these filters",
            "Try lowering the minimum score, widening the experience range, "
            "or clearing the search box.",
        )

    with tab_insights:
        left, right = st.columns(2)
        with left:
            st.markdown(C.section_heading("Top skills requested",
                                          "across every captured post"), unsafe_allow_html=True)
            render_skills_chart()
        with right:
            st.markdown(C.section_heading("Top locations", "by mention count"),
                        unsafe_allow_html=True)
            render_locations_chart()
        st.markdown(C.section_heading("Score distribution",
                                      "where your threshold cuts"), unsafe_allow_html=True)
        render_score_chart()

        st.markdown(C.section_heading("Re-score with Gemini",
                                      "judge stored posts with the LLM"), unsafe_allow_html=True)
        render_rescore_panel(filters)

    with tab_runs:
        st.markdown(C.section_heading("Run history", "every scrape is logged locally"),
                    unsafe_allow_html=True)
        render_run_history()

        run_df = load_run_logs(50)
        if not run_df.empty:
            st.markdown(C.section_heading("Detailed log"), unsafe_allow_html=True)
            log_cols = [
                "started_at", "completed_at", "status", "deep_scan", "keywords_searched",
                "posts_found", "duplicates_removed", "filtered_out", "new_posts",
                "notified", "errors",
            ]
            available = [c for c in log_cols if c in run_df.columns]
            st.dataframe(
                run_df[available], width="stretch", hide_index=True,
                column_config={
                    "started_at": st.column_config.TextColumn("Started"),
                    "completed_at": st.column_config.TextColumn("Completed"),
                    "keywords_searched": st.column_config.NumberColumn("Keywords"),
                    "posts_found": st.column_config.NumberColumn("Scraped"),
                    "duplicates_removed": st.column_config.NumberColumn("Duplicates"),
                    "filtered_out": st.column_config.NumberColumn("Filtered out"),
                    "new_posts": st.column_config.NumberColumn("New"),
                    "notified": st.column_config.NumberColumn("Notified"),
                    "status": st.column_config.TextColumn("Status", width="small"),
                    "deep_scan": st.column_config.CheckboxColumn("Deep"),
                    "errors": st.column_config.TextColumn("Errors", width="medium"),
                },
            )

    with tab_feedback:
        st.markdown(C.section_heading("Tuning feedback",
                                      "turn rejections into better rules"), unsafe_allow_html=True)
        st.caption(
            "Marking a post **Not relevant** with a reason lands it here. Recurring phrases "
            "are candidates for `NON_HIRING_SIGNALS` / `ABSOLUTE_REJECT_PHRASES` in "
            "`config.py` — that is how the rule engine improves without any AI."
        )
        phrases = feedback_phrases()
        if phrases:
            st.dataframe(pd.DataFrame(phrases, columns=["Phrase", "Count"]),
                         width="stretch", hide_index=True)
        else:
            st.info("No recurring phrases yet. Mark a few posts as not relevant (with a reason).")

        fb_df = load_feedback(100)
        if not fb_df.empty:
            st.markdown(C.section_heading("Recent feedback"), unsafe_allow_html=True)
            st.dataframe(fb_df, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
