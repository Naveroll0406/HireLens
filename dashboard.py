"""
LinkedIn AI Job Post Monitor — Streamlit Dashboard

A real-time dashboard to visualize scraped job opportunities,
run the scraper with a custom URL, and manage settings.

Usage:
  conda activate linkedin
  streamlit run dashboard.py
"""

from __future__ import annotations
import re
import json
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import pandas as pd

# Ensure the project root is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

# ---------------------------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="LinkedIn AI Job Monitor",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — Premium dark theme with always-visible sidebar
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* Root variables */
    :root {
        --bg-primary: #0a0a1a;
        --bg-card: rgba(20, 20, 45, 0.7);
        --bg-glass: rgba(255, 255, 255, 0.04);
        --border-glass: rgba(255, 255, 255, 0.08);
        --accent-blue: #4f8cff;
        --accent-purple: #a855f7;
        --accent-green: #22c55e;
        --accent-orange: #f59e0b;
        --accent-red: #ef4444;
        --accent-cyan: #06b6d4;
        --text-primary: #f1f5f9;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;
    }

    /* Global */
    .stApp {
        font-family: 'Inter', sans-serif !important;
    }

    /* ===== FORCE SIDEBAR ALWAYS VISIBLE ===== */
    /* Prevent sidebar from collapsing */
    section[data-testid="stSidebar"] {
        min-width: 340px !important;
        max-width: 400px !important;
        background: rgba(10, 10, 26, 0.95) !important;
        border-right: 1px solid var(--border-glass) !important;
    }

    /* Hide the sidebar collapse button */
    button[data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    button[kind="headerNoPadding"] {
        display: none !important;
        visibility: hidden !important;
    }

    /* Prevent sidebar from being hidden */
    section[data-testid="stSidebar"][aria-expanded="false"] {
        display: block !important;
        min-width: 340px !important;
        transform: none !important;
        margin-left: 0 !important;
    }

    /* Main header */
    .main-header {
        background: linear-gradient(135deg, rgba(79, 140, 255, 0.15) 0%, rgba(168, 85, 247, 0.15) 50%, rgba(6, 182, 212, 0.15) 100%);
        border: 1px solid var(--border-glass);
        border-radius: 20px;
        padding: 1.5rem 2rem;
        margin-bottom: 1.5rem;
        backdrop-filter: blur(20px);
        position: relative;
        overflow: hidden;
    }

    .main-header::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple), var(--accent-cyan));
    }

    .main-header h1 {
        font-size: 1.8rem;
        font-weight: 800;
        background: linear-gradient(135deg, #4f8cff, #a855f7, #06b6d4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0 0 0.3rem 0;
        letter-spacing: -0.02em;
    }

    .main-header p {
        color: var(--text-secondary);
        font-size: 0.95rem;
        margin: 0;
        font-weight: 400;
    }

    /* URL input box styling */
    .url-input-section {
        background: linear-gradient(135deg, rgba(79, 140, 255, 0.08) 0%, rgba(168, 85, 247, 0.08) 100%);
        border: 1px solid rgba(79, 140, 255, 0.2);
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
    }

    .url-input-section h3 {
        margin: 0 0 0.5rem 0;
        font-size: 1.1rem;
        font-weight: 700;
    }

    .url-input-section p {
        color: var(--text-secondary);
        font-size: 0.85rem;
        margin: 0 0 0.75rem 0;
    }

    /* Metric cards */
    .metric-card {
        background: var(--bg-glass);
        border: 1px solid var(--border-glass);
        border-radius: 16px;
        padding: 1.25rem;
        text-align: center;
        backdrop-filter: blur(12px);
        transition: all 0.3s ease;
    }

    .metric-card:hover {
        border-color: rgba(79, 140, 255, 0.3);
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(79, 140, 255, 0.1);
    }

    .metric-value {
        font-size: 2.2rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        line-height: 1;
        margin-bottom: 0.4rem;
    }

    .metric-label {
        font-size: 0.8rem;
        color: var(--text-secondary);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .blue { color: var(--accent-blue); }
    .purple { color: var(--accent-purple); }
    .green { color: var(--accent-green); }
    .orange { color: var(--accent-orange); }
    .cyan { color: var(--accent-cyan); }

    /* Job card */
    .job-card {
        background: var(--bg-glass);
        border: 1px solid var(--border-glass);
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        backdrop-filter: blur(12px);
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }

    .job-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 4px;
        height: 100%;
        background: linear-gradient(180deg, var(--accent-blue), var(--accent-purple));
        border-radius: 4px 0 0 4px;
    }

    .job-card:hover {
        border-color: rgba(79, 140, 255, 0.25);
        box-shadow: 0 4px 24px rgba(79, 140, 255, 0.08);
    }

    .job-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--text-primary);
        margin-bottom: 0.6rem;
    }

    .job-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 0.8rem;
        margin-bottom: 0.6rem;
    }

    .job-meta-item {
        display: flex;
        align-items: center;
        gap: 0.3rem;
        font-size: 0.85rem;
        color: var(--text-secondary);
    }

    .job-skills {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        margin-top: 0.6rem;
    }

    .skill-tag {
        background: rgba(79, 140, 255, 0.12);
        color: var(--accent-blue);
        border: 1px solid rgba(79, 140, 255, 0.2);
        border-radius: 8px;
        padding: 0.2rem 0.6rem;
        font-size: 0.78rem;
        font-weight: 500;
    }

    .job-content-preview {
        color: var(--text-muted);
        font-size: 0.85rem;
        line-height: 1.6;
        margin-top: 0.6rem;
        padding: 0.8rem;
        background: rgba(0,0,0,0.2);
        border-radius: 8px;
        max-height: 400px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-word;
    }

    .job-link {
        display: inline-block;
        margin-top: 0.6rem;
        color: var(--accent-cyan);
        text-decoration: none;
        font-weight: 600;
        font-size: 0.88rem;
        transition: color 0.2s;
    }

    .job-link:hover {
        color: var(--accent-blue);
    }

    .apply-section {
        background: linear-gradient(135deg, rgba(34, 197, 94, 0.08) 0%, rgba(34, 197, 94, 0.15) 100%);
        border: 1px solid rgba(34, 197, 94, 0.25);
        border-radius: 12px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.8rem;
    }

    .apply-section-label {
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--accent-green);
        margin-bottom: 0.4rem;
    }

    .apply-link {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.45rem 1rem;
        background: rgba(34, 197, 94, 0.18);
        color: var(--accent-green);
        border: 1px solid rgba(34, 197, 94, 0.35);
        border-radius: 10px;
        text-decoration: none;
        font-weight: 700;
        font-size: 0.85rem;
        transition: all 0.25s ease;
        margin-right: 0.5rem;
        margin-bottom: 0.3rem;
    }

    .apply-link:hover {
        background: rgba(34, 197, 94, 0.3);
        transform: translateY(-2px);
        box-shadow: 0 4px 16px rgba(34, 197, 94, 0.15);
    }

    .company-link {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.4rem 0.9rem;
        background: rgba(79, 140, 255, 0.1);
        color: var(--accent-blue);
        border: 1px solid rgba(79, 140, 255, 0.25);
        border-radius: 10px;
        text-decoration: none;
        font-weight: 600;
        font-size: 0.82rem;
        transition: all 0.25s ease;
    }

    .company-link:hover {
        background: rgba(79, 140, 255, 0.2);
        transform: translateY(-1px);
    }

    .no-link-message {
        color: var(--text-muted);
        font-size: 0.8rem;
        font-style: italic;
        padding: 0.3rem 0;
    }

    .platform-badge {
        display: inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: 6px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.03em;
        background: rgba(168, 85, 247, 0.12);
        color: var(--accent-purple);
        border: 1px solid rgba(168, 85, 247, 0.2);
    }

    .apply-url-text {
        font-size: 0.75rem;
        color: var(--text-muted);
        word-break: break-all;
        margin-top: 0.2rem;
    }

    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.03em;
    }

    .status-running {
        background: rgba(34, 197, 94, 0.15);
        color: var(--accent-green);
        border: 1px solid rgba(34, 197, 94, 0.3);
        animation: pulse 2s ease-in-out infinite;
    }

    .status-idle {
        background: rgba(100, 116, 139, 0.15);
        color: var(--text-secondary);
        border: 1px solid rgba(100, 116, 139, 0.3);
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }

    /* Run log entry */
    .run-log-entry {
        background: var(--bg-glass);
        border: 1px solid var(--border-glass);
        border-radius: 10px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.5rem;
        font-size: 0.85rem;
    }

    /* Streamlit element overrides */
    .stButton > button {
        border-radius: 12px !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
        transition: all 0.3s ease !important;
    }

    .stButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 16px rgba(79, 140, 255, 0.2) !important;
    }

    div[data-testid="stExpander"] {
        border: 1px solid var(--border-glass) !important;
        border-radius: 12px !important;
        background: var(--bg-glass) !important;
    }

    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# All available locations for the editable checklist
# ---------------------------------------------------------------------------

ALL_LOCATIONS = [
    "Hyderabad",
    "Bangalore",
    "Bengaluru",
    "Pune",
    "Chennai",
    "Mumbai",
    "Gurgaon",
    "Gurugram",
    "Noida",
    "Delhi",
    "Kolkata",
    "Ahmedabad",
    "Jaipur",
    "Kochi",
    "Thiruvananthapuram",
    "Indore",
    "Chandigarh",
    "Coimbatore",
    "Lucknow",
    "Nagpur",
    "Remote",
    "Work From Home",
    "India",
    "USA",
    "Singapore",
    "Dubai",
    "London",
    "Canada",
    "Germany",
    "Australia",
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Get a read-only SQLite connection."""
    db_path = config.DATABASE_PATH
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db():
    """Ensure the database exists and is initialized."""
    from storage.database import Database
    db = Database(config.DATABASE_PATH)
    db.init_db()
    db.seed_default_keywords(config.DEFAULT_KEYWORDS)
    db.close()


def load_posts(limit: int = 100, hiring_only: bool = True,
               search_text: str = "", location_filter: str = "All",
               exp_range: tuple[int, int] = (0, 15)) -> pd.DataFrame:
    """Load posts from the database as a DataFrame."""
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()

    query = "SELECT * FROM posts WHERE 1=1"
    params = []

    if hiring_only:
        query += " AND is_hiring = 1"

    if search_text:
        query += " AND (content LIKE ? OR role LIKE ? OR author_name LIKE ?)"
        like = f"%{search_text}%"
        params.extend([like, like, like])

    if location_filter and location_filter != "All":
        query += " AND locations LIKE ?"
        params.append(f"%{location_filter}%")
        
    # Simple experience filtering: if the post has exp min/max, check if it overlaps with selected range
    # Or if experience is null, we usually still include it unless strictly requested otherwise
    query += " AND (experience_min IS NULL OR experience_min <= ?)"
    params.append(exp_range[1])
    query += " AND (experience_max IS NULL OR experience_max >= ?)"
    params.append(exp_range[0])

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def load_new_posts(since_run_id: int | None = None, hiring_only: bool = True,
                   search_text: str = "", location_filter: str = "All",
                   exp_range: tuple[int, int] = (0, 15)) -> pd.DataFrame:
    """Load new posts. If since_run_id is None, loads the very latest run's posts."""
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()

    query = "SELECT * FROM posts WHERE "
    params: list = []
    
    if since_run_id is not None:
        query += "run_id > ?"
        params.append(since_run_id)
    else:
        query += "1=1"

    if hiring_only:
        query += " AND is_hiring = 1"

    if search_text:
        query += " AND (content LIKE ? OR role LIKE ? OR author_name LIKE ?)"
        like = f"%{search_text}%"
        params.extend([like, like, like])

    if location_filter and location_filter != "All":
        query += " AND locations LIKE ?"
        params.append(f"%{location_filter}%")

    query += " AND (experience_min IS NULL OR experience_min <= ?)"
    params.append(exp_range[1])
    query += " AND (experience_max IS NULL OR experience_max >= ?)"
    params.append(exp_range[0])

    query += " ORDER BY created_at DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    
    if since_run_id is None and not df.empty and 'run_id' in df.columns:
        df = df[df['run_id'] == df['run_id'].max()]
        
    return df


def load_run_logs(limit: int = 20) -> pd.DataFrame:
    """Load recent run logs."""
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()

    df = pd.read_sql_query(
        "SELECT * FROM run_log ORDER BY started_at DESC LIMIT ?",
        conn, params=[limit]
    )
    conn.close()
    return df


def get_stats() -> dict:
    """Get dashboard statistics."""
    conn = get_db_connection()
    if conn is None:
        return {"total_posts": 0, "hiring_posts": 0, "total_notifications": 0,
                "total_runs": 0, "unique_locations": 0}

    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM posts")
    total_posts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM posts WHERE is_hiring = 1")
    hiring_posts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM run_log")
    total_runs = cursor.fetchone()[0]

    cursor.execute("SELECT locations FROM posts WHERE locations IS NOT NULL AND locations != '[]'")
    all_locations = set()
    for row in cursor.fetchall():
        try:
            locs = json.loads(row[0])
            all_locations.update(locs)
        except (json.JSONDecodeError, TypeError):
            pass

    conn.close()

    return {
        "total_posts": total_posts,
        "hiring_posts": hiring_posts,
        "total_runs": total_runs,
        "unique_locations": len(all_locations),
    }


def get_found_locations() -> list[str]:
    """Get unique locations that have been found in posts."""
    conn = get_db_connection()
    if conn is None:
        return []

    cursor = conn.cursor()
    cursor.execute("SELECT locations FROM posts WHERE locations IS NOT NULL AND locations != '[]'")
    all_locations = set()
    for row in cursor.fetchall():
        try:
            locs = json.loads(row[0])
            all_locations.update(locs)
        except (json.JSONDecodeError, TypeError):
            pass
    conn.close()
    return sorted(all_locations)


def get_top_skills(limit: int = 15) -> list[tuple[str, int]]:
    """Get the most frequently mentioned skills."""
    conn = get_db_connection()
    if conn is None:
        return []

    cursor = conn.cursor()
    cursor.execute("SELECT skills FROM posts WHERE skills IS NOT NULL AND skills != '[]'")
    skill_counts: dict[str, int] = {}
    for row in cursor.fetchall():
        try:
            skills = json.loads(row[0])
            for s in skills:
                skill_counts[s] = skill_counts.get(s, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass
    conn.close()

    sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_skills[:limit]


def get_keywords() -> list[dict]:
    """Get all keywords with their status."""
    conn = get_db_connection()
    if conn is None:
        return []

    cursor = conn.cursor()
    cursor.execute("SELECT keyword, active FROM keywords ORDER BY keyword")
    keywords = [{"keyword": row[0], "active": bool(row[1])} for row in cursor.fetchall()]
    conn.close()
    return keywords


# ---------------------------------------------------------------------------
# Scraper runner (background thread)
# ---------------------------------------------------------------------------

def run_scraper_in_background(url: str = "",
                              filter_locations: list[str] | None = None,
                              filter_experience: tuple[int, int] | None = None):
    """Run the scraper pipeline in a background thread."""
    if st.session_state.get("scraper_running", False):
        return

    st.session_state["scraper_running"] = True
    st.session_state["scraper_log"] = []
    st.session_state["scraper_start_time"] = datetime.now()

    # Record the max run_id before we start, so we can isolate new posts
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MAX(id) FROM run_log")
            max_id = cursor.fetchone()[0] or 0
        except Exception:
            max_id = 0
        conn.close()
    else:
        max_id = 0
    st.session_state["last_run_id"] = max_id

    def _run():
        try:
            import asyncio
            import sys
            from main import run_pipeline, setup_logging
            setup_logging()

            # On Windows, the default SelectorEventLoop in a thread doesn't
            # support subprocesses (required by Playwright).  Force Proactor.
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            stats = loop.run_until_complete(run_pipeline(
                dry_run=False,
                url=url,
                filter_locations=filter_locations,
                filter_experience=filter_experience,
            ))
            loop.close()

            st.session_state["scraper_last_stats"] = {
                "posts_found": stats.posts_found,
                "new_posts": stats.new_posts,
                "notifications_sent": stats.notifications_sent,
                "duration": stats.duration_seconds,
                "errors": stats.errors,
                "url_used": url,
            }
        except Exception as e:
            st.session_state["scraper_last_stats"] = {
                "posts_found": 0,
                "new_posts": 0,
                "notifications_sent": 0,
                "duration": 0,
                "errors": [str(e)],
                "url_used": url,
            }
        finally:
            st.session_state["scraper_running"] = False

    thread = threading.Thread(target=_run, daemon=True)
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx
        add_script_run_ctx(thread)
    except ImportError:
        pass
    thread.start()


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------

def render_header():
    """Render the main dashboard header."""
    st.markdown("""
    <div class="main-header">
        <h1>🔍 LinkedIn AI Job Monitor</h1>
        <p>Automated discovery of AI, GenAI, LLM & RAG hiring opportunities from LinkedIn Posts</p>
    </div>
    """, unsafe_allow_html=True)


def render_url_input():
    """Render the LinkedIn URL input section in the main area."""

    is_running = st.session_state.get("scraper_running", False)

    col_url, col_btn = st.columns([4, 1])

    with col_url:
        url = st.text_input(
            "🔗 Paste LinkedIn Search URL",
            value=st.session_state.get("last_url", ""),
            placeholder="Enter the URL here...",
            help="Go to LinkedIn → Search → Posts tab → Copy the URL from your browser and paste it here",
            label_visibility="visible",
            key="linkedin_url_input",
        )

    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)  # Align button with input
        run_clicked = st.button(
            "🚀 Run Scraper" if not is_running else "⏳ Running...",
            disabled=is_running,
            use_container_width=True,
            type="primary",
            key="run_scraper_btn",
        )

    if run_clicked and url.strip():
        st.session_state["last_url"] = url.strip()
        # Pass sidebar filter selections to the scraper pipeline
        sel_locs = st.session_state.get("selected_locations")
        sel_exp = st.session_state.get("filter_experience_range")
        run_scraper_in_background(
            url=url.strip(),
            filter_locations=sel_locs,
            filter_experience=sel_exp,
        )
        st.rerun()
    elif run_clicked and not url.strip():
        st.warning("⚠️ Please paste a LinkedIn search URL first.")

    # Show running status
    if is_running:
        st.info("⏳ **Scraper is running...** A browser window is open scraping LinkedIn. This page will update with results when it finishes.")
        st.markdown('<meta http-equiv="refresh" content="5">', unsafe_allow_html=True)

    # Last run results
    last_stats = st.session_state.get("scraper_last_stats")
    if last_stats and not is_running:
        cols = st.columns(3)
        with cols[0]:
            st.metric("📄 Posts Found", last_stats["posts_found"])
        with cols[1]:
            st.metric("🆕 New Posts", last_stats["new_posts"])
        with cols[2]:
            st.metric("⏱ Duration", f"{last_stats['duration']:.0f}s")
        if last_stats.get("errors"):
            for err in last_stats["errors"][:3]:
                st.error(f"❌ {err[:150]}")

    return url


def render_metrics():
    """Render the top-level metric cards."""
    stats = get_stats()

    cols = st.columns(4)
    metrics = [
        ("📄", str(stats["total_posts"]), "Total Posts", "blue"),
        ("🎯", str(stats["hiring_posts"]), "Hiring Posts", "purple"),
        ("🔄", str(stats["total_runs"]), "Total Runs", "orange"),
        ("📍", str(stats["unique_locations"]), "Locations", "cyan"),
    ]

    for col, (icon, value, label, color) in zip(cols, metrics):
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div style="font-size: 1.3rem; margin-bottom: 0.4rem;">{icon}</div>
                <div class="metric-value {color}">{value}</div>
                <div class="metric-label">{label}</div>
            </div>
            """, unsafe_allow_html=True)


def render_job_card(row):
    """Render a single job posting card with the new layout order:
    1. Apply Link  2. Company Website  3. Job Title  4. Company Name
    5. Location  6. Date Posted  7. Source Platform  8. View Source Post
    """
    # --- Extract data from row ---
    role = row.get("role", "")
    if pd.isna(role) or not role:
        kw = row.get("keyword_matched", "")
        role = kw if kw and not pd.isna(kw) else "Job Opportunity"
        
    author = row.get("author_name", "")
    if pd.isna(author) or not author:
        author = "Unknown"
        
    content = row.get("content", "")
    if pd.isna(content):
        content = ""
        
    post_url = row.get("post_url", "")
    if pd.isna(post_url):
        post_url = ""

    company_url = row.get("company_url", "")
    if pd.isna(company_url):
        company_url = ""

    created_at = row.get("created_at", "")

    # --- NO fake URL reconstruction --- just use what's stored

    # --- Parse locations ---
    locations_str = "Not Specified"
    try:
        locs = json.loads(row.get("locations", "[]") or "[]")
        if locs:
            locations_str = ", ".join(locs)
    except (json.JSONDecodeError, TypeError):
        pass

    # --- Parse skills ---
    skills_html = ""
    try:
        skills = json.loads(row.get("skills", "[]") or "[]")
        if skills:
            tags = "".join(f'<span class="skill-tag">{s}</span>' for s in skills[:10])
            skills_html = f'<div class="job-skills">{tags}</div>'
    except (json.JSONDecodeError, TypeError):
        pass

    # --- Parse emails ---
    emails_html = ""
    try:
        emails = json.loads(row.get("emails", "[]") or "[]")
        if emails:
            tags = "".join(
                f'<span style="display:inline-block;margin-right:0.4rem;margin-top:0.3rem;'
                f'padding:0.2rem 0.6rem;background:rgba(245,158,11,0.1);color:var(--accent-orange);'
                f'border:1px solid rgba(245,158,11,0.3);border-radius:8px;font-size:0.78rem;'
                f'font-weight:500;">{e}</span>'
                for e in emails
            )
            emails_html = f'<div style="margin-top:0.4rem;">{tags}</div>'
    except (json.JSONDecodeError, TypeError, KeyError):
        pass

    # --- Parse URLs ---
    primary_url = row.get("primary_url")
    if pd.isna(primary_url):
        primary_url = None
        
    extracted_urls = []
    try:
        urls_val = row.get("extracted_urls", "[]")
        if pd.notna(urls_val):
            extracted_urls = json.loads(urls_val or "[]")
    except (json.JSONDecodeError, TypeError, KeyError):
        pass

    # Fallback to apply_links column for old DB records
    if not primary_url and not extracted_urls:
        try:
            old_apply = json.loads(row.get("apply_links", "[]") or "[]")
            if old_apply:
                primary_url = old_apply[0]
                extracted_urls = old_apply[1:]
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    # --- Detect platform from primary url ---
    def _detect_platform(url: str) -> str:
        if not url: return ""
        url_lower = url.lower()
        platform_map = {
            'greenhouse.io': 'Greenhouse',
            'lever.co': 'Lever',
            'workday.com': 'Workday',
            'myworkday.com': 'Workday',
            'ashbyhq.com': 'Ashby',
            'smartrecruiters.com': 'SmartRecruiters',
            'icims.com': 'iCIMS',
            'taleo.net': 'Taleo',
            'breezy.hr': 'Breezy',
            'recruitee.com': 'Recruitee',
            'bamboohr.com': 'BambooHR',
            'jazz.co': 'JazzHR',
            'jobs.lever.co': 'Lever',
            'indeed.com': 'Indeed',
            'naukri.com': 'Naukri'
        }
        for domain, name in platform_map.items():
            if domain in url_lower:
                return name
        return ""

    detected_platform = _detect_platform(primary_url) if primary_url else ""

    # --- Build Apply Section HTML (top of card) ---
    apply_section_html = ""
    if primary_url or extracted_urls:
        links_html = '<div class="apply-section"><div class="apply-section-label">🚀 Action Required</div><div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem;">'
        if primary_url:
            primary_domain = urlparse(primary_url).netloc.replace("www.", "")
            links_html += f'<a href="{primary_url}" target="_blank" class="apply-link" style="display:inline-block;">✨ Primary Link → <span style="font-size:0.75rem;opacity:0.8;margin-left:0.3rem;">{primary_domain[:25]}</span></a>'
        if extracted_urls:
            # Always show first link directly
            first_link = extracted_urls[0]
            first_domain = urlparse(first_link).netloc.replace("www.", "")
            links_html += f'<div style="display:flex; flex-wrap:wrap; gap:0.4rem; align-items:center;">'
            links_html += f'<a href="{first_link}" target="_blank" style="font-size:0.8rem; background:rgba(79,140,255,0.1); border:1px solid rgba(79,140,255,0.2); padding:0.25rem 0.6rem; border-radius:6px; color:var(--accent-blue); text-decoration:none; font-weight:500;">📎 {first_domain[:20]}</a>'
            if len(extracted_urls) > 1:
                links_html += f'<span style="font-size:0.75rem;color:var(--text-muted);cursor:pointer;" title="{len(extracted_urls)-1} more links below">+{len(extracted_urls)-1} more</span>'
            links_html += '</div>'
            # Show remaining links in a collapsible area
            if len(extracted_urls) > 1:
                links_html += '<div style="margin-top:0.4rem; padding:0.5rem; background:rgba(0,0,0,0.15); border-radius:6px; display:flex; flex-wrap:wrap; gap:0.3rem;">'
                for link in extracted_urls[1:8]:
                    domain = urlparse(link).netloc.replace("www.", "")
                    links_html += f'<a href="{link}" target="_blank" style="font-size:0.75rem; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); padding:0.2rem 0.5rem; border-radius:4px; color:var(--text-secondary); text-decoration:none;">🔗 {domain[:18]}</a>'
                links_html += '</div>'
        links_html += '</div></div>'
        apply_section_html = links_html
    else:
        apply_section_html = f'''<div class="apply-section" style="background: rgba(245,158,11,0.05); border-color: rgba(245,158,11,0.2);">
<div class="apply-section-label" style="color: var(--accent-orange);">⚠️ No Apply Link Found</div>
<div class="no-link-message" style="margin-top: 0.3rem;">Please check for email IDs in the post content below for manual application.</div>
</div>'''

    # --- Experience ---
    exp_min = row.get("experience_min")
    exp_max = row.get("experience_max")
    if pd.isna(exp_min): exp_min = None
    if pd.isna(exp_max): exp_max = None
    if exp_min is not None and exp_max is not None:
        exp_str = f"{int(exp_min)}-{int(exp_max)} Years"
    elif exp_min is not None:
        exp_str = f"{int(exp_min)}+ Years"
    elif exp_max is not None:
        exp_str = f"0-{int(exp_max)} Years"
    else:
        exp_str = "Not Specified"

    # --- Content preview ---
    safe_content = content.strip().replace("<", "&lt;").replace(">", "&gt;").replace("`", "'").replace("\n", "<br>")
    content_html = f'<div class="job-content-preview">{safe_content}</div>'

    # --- Format timestamp ---
    time_display = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(str(created_at))
            time_display = dt.strftime("%b %d, %Y  %I:%M:%S %p")
        except (ValueError, TypeError):
            time_display = str(created_at)[:19]

    # --- Author headline ---
    author_headline = row.get("author_headline", "")
    if pd.isna(author_headline):
        author_headline = ""

    # --- Platform badge ---
    source_platform = "LinkedIn"
    if detected_platform:
        source_platform = f"LinkedIn + {detected_platform}"
    platform_html = f'<span class="platform-badge">📡 {source_platform}</span>'

    # --- Source post link & Admin profile link ---
    author_url = row.get("author_url", "")
    if pd.isna(author_url):
        author_url = ""
        
    post_urn = row.get("post_urn", "")
    if pd.isna(post_urn):
        post_urn = ""
        
    if post_url and "/company/" in post_url and post_urn:
        # Fix old records that incorrectly used company_url as post_url
        post_url = f"https://www.linkedin.com/feed/update/{post_urn}"
        
    if not post_url and post_urn:
        post_url = f"https://www.linkedin.com/feed/update/{post_urn}"

    # Build source section with admin profile link prominently displayed
    source_parts = []

    # Admin/Author profile link — shown first and prominently for verification
    if author_url:
        if "/company/" in author_url:
            profile_label = "🏢 Company Page"
            profile_type = "Company"
        else:
            profile_label = "👤 Admin Profile"
            profile_type = "Profile"
        source_parts.append(f'''
        <div style="background:rgba(168,85,247,0.08); border:1px solid rgba(168,85,247,0.2); border-radius:10px; padding:0.6rem 0.8rem; margin-bottom:0.5rem;">
            <div style="font-size:0.72rem; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; color:var(--accent-purple); margin-bottom:0.3rem;">🔍 Verify Source — {profile_type}</div>
            <a href="{author_url}" target="_blank" style="display:inline-flex; align-items:center; gap:0.4rem; padding:0.35rem 0.8rem; background:rgba(168,85,247,0.15); color:var(--accent-purple); border:1px solid rgba(168,85,247,0.3); border-radius:8px; text-decoration:none; font-weight:600; font-size:0.82rem; transition:all 0.25s ease;">{profile_label} →</a>
            <div style="font-size:0.72rem; color:var(--text-muted); margin-top:0.3rem; word-break:break-all;">{author_url}</div>
        </div>''')

    # Post source link
    if post_url:
        source_parts.append(f'<div style="margin-bottom:0.5rem;"><a href="{post_url}" target="_blank" class="job-link" style="margin-right: 1rem;">🔗 View Source Post on LinkedIn</a></div>')
        source_parts.append(f'<div style="font-size:0.75rem;color:var(--text-muted);word-break:break-all;margin-bottom:0.3rem;"><strong>Post URL:</strong> <a href="{post_url}" target="_blank" style="color:var(--accent-blue);text-decoration:none;">{post_url}</a></div>')

    source_link_html = "<div style='margin-top: 0.6rem; padding-top:0.5rem; border-top:1px solid rgba(255,255,255,0.06);'>" + "".join(source_parts) + "</div>" if source_parts else ""

    # --- Render the card ---
    st.markdown(f"""<div class="job-card">
{apply_section_html}
<div class="job-title">📋 {role}</div>
<div class="job-meta">
<span class="job-meta-item">🏢 {author}</span>
<span class="job-meta-item">📍 {locations_str}</span>
<span class="job-meta-item">🕐 {time_display}</span>
<span class="job-meta-item">🎯 {exp_str}</span>
</div>
<div style="margin-top:0.4rem;">{platform_html}</div>
{skills_html}{emails_html}
{content_html}
{source_link_html}
</div>""", unsafe_allow_html=True)


def render_sidebar():
    """Render the sidebar with filters, locations, and keywords."""
    with st.sidebar:
        # --- Status ---
        is_running = st.session_state.get("scraper_running", False)
        if is_running:
            st.markdown('<div style="text-align:center;"><span class="status-badge status-running">● SCRAPER RUNNING</span></div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div style="text-align:center;"><span class="status-badge status-idle">○ IDLE</span></div>',
                        unsafe_allow_html=True)

        st.markdown("---")

        # --- Search & Filters ---
        st.markdown("### 🔍 Filters")

        search_text = st.text_input(
            "Search posts",
            placeholder="Search by role, skill, author...",
            key="search_filter",
        )

        hiring_only = st.checkbox("Only show confident hiring posts", value=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        exp_range = st.slider(
            "Experience Range (Years)",
            min_value=0, max_value=15, value=(0, 15),
            help="Filter jobs based on required experience. Jobs without specified experience are always shown."
        )
        # Store for use by the scraper pipeline
        st.session_state["filter_experience_range"] = exp_range

        st.markdown("---")

        # Location filter from found data
        found_locs = get_found_locations()
        loc_options = ["All"] + found_locs
        location_filter = st.selectbox("📍 Filter by Location", loc_options, key="loc_filter")

        max_results = st.slider("Max results", 10, 200, 50, 10, key="max_results")

        st.markdown("---")

        # --- Editable Locations ---
        st.markdown("### 📍 Target Locations")
        st.caption("Select which locations to accept in filtering")

        # Initialize selected locations in session state
        if "selected_locations" not in st.session_state:
            st.session_state["selected_locations"] = list(config.TARGET_LOCATIONS)

        # Show locations as checkboxes in a compact expander
        with st.expander("Edit Locations", expanded=False):
            # Select/Deselect all
            col_all, col_none = st.columns(2)
            with col_all:
                if st.button("✅ Select All", use_container_width=True, key="sel_all"):
                    st.session_state["selected_locations"] = list(ALL_LOCATIONS)
                    st.rerun()
            with col_none:
                if st.button("❌ Clear All", use_container_width=True, key="clr_all"):
                    st.session_state["selected_locations"] = []
                    st.rerun()

            selected = []
            for loc in ALL_LOCATIONS:
                checked = st.checkbox(
                    loc,
                    value=loc in st.session_state["selected_locations"],
                    key=f"loc_{loc}",
                )
                if checked:
                    selected.append(loc)

            # Add custom location
            custom_loc = st.text_input("Add custom location", placeholder="e.g., Vizag", key="custom_loc")
            if st.button("➕ Add Location", key="add_loc_btn") and custom_loc.strip():
                if custom_loc.strip() not in ALL_LOCATIONS:
                    ALL_LOCATIONS.append(custom_loc.strip())
                if custom_loc.strip() not in selected:
                    selected.append(custom_loc.strip())

            st.session_state["selected_locations"] = selected

        # Show active count
        st.caption(f"✅ {len(st.session_state['selected_locations'])} locations active")

        st.markdown("---")

        # --- Keywords ---
        st.markdown("### 🔑 Keywords")
        keywords = get_keywords()
        active_kws = [k["keyword"] for k in keywords if k["active"]]
        st.caption(f"{len(active_kws)} active keywords")

        with st.expander("View/Edit Keywords", expanded=False):
            for kw in keywords:
                col_kw, col_del = st.columns([4, 1])
                with col_kw:
                    status = "✅" if kw["active"] else "❌"
                    st.text(f"{status} {kw['keyword']}")
                with col_del:
                    if kw["active"] and st.button("🗑", key=f"del_{kw['keyword']}"):
                        from storage.database import Database
                        db = Database(config.DATABASE_PATH)
                        db.init_db()
                        db.remove_keyword(kw["keyword"])
                        db.close()
                        st.rerun()

            new_kw = st.text_input("Add keyword", placeholder="e.g., MLOps Engineer", key="new_kw")
            if st.button("➕ Add Keyword", use_container_width=True, key="add_kw_btn") and new_kw.strip():
                from storage.database import Database
                db = Database(config.DATABASE_PATH)
                db.init_db()
                db.add_keyword(new_kw.strip())
                db.close()
                st.success(f"Added: {new_kw.strip()}")
                st.rerun()

        st.markdown("---")

        # --- Settings ---
        st.markdown("### ⚙️ Settings")
        
        from storage.database import Database
        db = Database(config.DATABASE_PATH)
        db.init_db()
        
        current_interval = int(db.get_setting("run_interval_minutes", str(config.RUN_INTERVAL_MINUTES)))
        new_interval = st.number_input("Scheduler Timer (minutes)", min_value=1, max_value=1440, value=current_interval, help="How often the background scheduler should run")
        if new_interval != current_interval:
            db.set_setting("run_interval_minutes", str(new_interval))
            
        current_wait = int(db.get_setting("scroll_duration_seconds", "300"))
        new_wait = st.number_input("Scroll Duration (seconds)", min_value=30, max_value=600, value=current_wait, help="How long the browser scrolls to load posts during scraping")
        if new_wait != current_wait:
            db.set_setting("scroll_duration_seconds", str(new_wait))
            
        db.close()

        st.markdown("---")

        # --- Database Info ---
        st.markdown("### 💾 Database")
        db_path = config.DATABASE_PATH
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            st.caption(f"📁 {db_path.name}")
            st.caption(f"💾 Size: {size_mb:.2f} MB")
        else:
            st.caption("No database yet — run the scraper first.")

        # --- Auto-refresh ---
        st.markdown("---")
        auto_refresh = st.checkbox("🔄 Auto-refresh (30s)", value=False, key="auto_refresh")
        if auto_refresh:
            st.markdown('<meta http-equiv="refresh" content="30">', unsafe_allow_html=True)

    return search_text, hiring_only, location_filter, max_results, exp_range


def render_skills_chart():
    """Render a bar chart of top skills."""
    top_skills = get_top_skills(12)
    if not top_skills:
        st.info("No skills data yet. Run the scraper first!")
        return

    skills_df = pd.DataFrame(top_skills, columns=["Skill", "Count"])
    st.bar_chart(skills_df.set_index("Skill"), horizontal=True)


def render_run_history():
    """Render recent run history."""
    df = load_run_logs(10)
    if df.empty:
        st.info("No run history yet. Run the scraper to see history here.")
        return

    for _, row in df.iterrows():
        started = row.get("started_at", "N/A")
        posts = row.get("posts_found", 0)
        new = row.get("new_posts", 0)
        errors = row.get("errors", "")

        error_badge = ""
        if errors and errors not in ("null", "[]", None, ""):
            error_badge = " ⚠️"

        st.markdown(f"""
        <div class="run-log-entry">
            <span>🕐 {started}</span>
            <span>📄 {posts} found</span>
            <span>🆕 {new} new</span>
            <span>{error_badge}</span>
        </div>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

def main():
    """Main Streamlit application."""
    # Initialize database on first load
    ensure_db()

    # Initialize session state
    if "scraper_running" not in st.session_state:
        st.session_state["scraper_running"] = False

    # Header
    render_header()

    # --- URL Input (prominent, at the top of main area) ---
    render_url_input()

    # Sidebar (returns filter values)
    search_text, hiring_only, location_filter, max_results, exp_range = render_sidebar()

    # Metrics row
    render_metrics()

    st.markdown("<br>", unsafe_allow_html=True)

    # Main content tabs
    tab_new, tab_all, tab_analytics, tab_history = st.tabs([
        "🆕 New (This Run)", "📋 All Posts", "📊 Analytics", "🕐 Run History"
    ])

    # Helper to render a dataframe as cards or table
    def _render_posts_view(df: pd.DataFrame, key_suffix: str):
        if df.empty:
            st.markdown("""
            <div style="text-align: center; padding: 3rem 2rem;">
                <div style="font-size: 3.5rem; margin-bottom: 1rem;">🔍</div>
                <h3 style="color: var(--text-secondary); margin-bottom: 0.5rem;">No posts to show</h3>
                <p style="color: var(--text-muted); max-width: 500px; margin: 0 auto;">
                    <b>Step 1:</b> Go to LinkedIn → Search for "AI Engineer Hyderabad" → Click the <b>Posts</b> tab<br>
                    <b>Step 2:</b> Copy the URL from your browser<br>
                    <b>Step 3:</b> Paste it above and click <b>🚀 Run Scraper</b>
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### Showing {len(df)} opportunities")
            with col2:
                view_mode = st.radio("View", ["Cards", "Table"], horizontal=True,
                                     label_visibility="collapsed", key=f"view_mode_{key_suffix}")

            if view_mode == "Cards":
                for _, row in df.iterrows():
                    render_job_card(row)
            else:
                display_cols = [
                    "post_urn", "role", "author_name", "locations", "experience_min",
                    "experience_max", "skills", "emails", "apply_links",
                    "created_at", "post_url"
                ]
                available_cols = [c for c in display_cols if c in df.columns]
                st.dataframe(
                    df[available_cols],
                    use_container_width=True,
                    column_config={
                        "post_urn": st.column_config.TextColumn("Post ID", width="small"),
                        "post_url": st.column_config.LinkColumn("Link", display_text="Open"),
                        "role": st.column_config.TextColumn("Role", width="medium"),
                        "author_name": st.column_config.TextColumn("Author", width="medium"),
                        "locations": st.column_config.TextColumn("Locations", width="medium"),
                        "skills": st.column_config.TextColumn("Skills", width="large"),
                        "emails": st.column_config.TextColumn("Emails", width="medium"),
                        "apply_links": st.column_config.TextColumn("Apply Links", width="medium"),
                        "experience_min": st.column_config.NumberColumn("Exp Min"),
                        "experience_max": st.column_config.NumberColumn("Exp Max"),
                        "created_at": st.column_config.TextColumn("Found At"),
                    },
                    hide_index=True,
                )

    # --- Tab 1: New Posts (This Run) ---
    with tab_new:
        last_run_id = st.session_state.get("last_run_id")
        
        # If we have a last_run_id, we show what's new since that run.
        # If we don't, we just show the very latest run's posts.
        st.caption("Showing the most recently discovered opportunities.")
        new_df = load_new_posts(
            since_run_id=last_run_id,
            hiring_only=hiring_only,
            search_text=search_text,
            location_filter=location_filter,
            exp_range=exp_range,
        )
        if not new_df.empty:
            _render_posts_view(new_df, "new")
        else:
            st.info("🚀 Run the scraper to see new posts here. After each run, this tab will show only the freshly discovered posts.")

    # --- Tab 2: All Posts ---
    with tab_all:
        df = load_posts(
            limit=max_results,
            hiring_only=hiring_only,
            search_text=search_text,
            location_filter=location_filter,
            exp_range=exp_range,
        )
        _render_posts_view(df, "all")

    # --- Tab 2: Analytics ---
    with tab_analytics:
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("### 🛠 Top Skills Requested")
            render_skills_chart()

        with col_right:
            st.markdown("### 📍 Top Locations")
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT locations FROM posts WHERE locations IS NOT NULL AND locations != '[]'")
                loc_counts: dict[str, int] = {}
                for row in cursor.fetchall():
                    try:
                        locs = json.loads(row[0])
                        for loc in locs:
                            loc_counts[loc] = loc_counts.get(loc, 0) + 1
                    except (json.JSONDecodeError, TypeError):
                        pass
                conn.close()

                if loc_counts:
                    loc_df = pd.DataFrame(
                        sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:10],
                        columns=["Location", "Count"]
                    )
                    st.bar_chart(loc_df.set_index("Location"), horizontal=True)
                else:
                    st.info("No location data yet.")
            else:
                st.info("No data yet.")

        # Posts Over Time graph removed as requested

    # --- Tab 3: Run History ---
    with tab_history:
        st.markdown("### 📜 Run History")
        st.caption("All scraper runs are logged here. Data is saved to your local SQLite database.")
        render_run_history()

        run_df = load_run_logs(50)
        if not run_df.empty:
            st.markdown("### 📊 Detailed Log")
            st.dataframe(run_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
