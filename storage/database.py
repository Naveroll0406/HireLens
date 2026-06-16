"""
SQLite database operations for the LinkedIn Job Post Monitor.

Handles all persistence: posts, notifications, keywords, settings, and run logs.
Uses Python's built-in sqlite3 module — no ORM overhead.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from storage.models import ParsedPost, RunStats

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for the LinkedIn monitor."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """Open a connection (or return the existing one)."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            logger.info("Connected to database: %s", self.db_path)
        return self._conn

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Database connection closed.")

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def init_db(self):
        """Create all tables if they don't exist."""
        schema = """
        CREATE TABLE IF NOT EXISTS posts (
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
            locations       TEXT,
            skills          TEXT,
            emails          TEXT,
            primary_url     TEXT,
            extracted_urls  TEXT,
            company_url     TEXT,
            author_url      TEXT,
            is_hiring       BOOLEAN DEFAULT 1,
            relevance_score INTEGER DEFAULT 0,
            keyword_matched TEXT,
            run_id          INTEGER,
            first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_posts_urn ON posts(post_urn);
        CREATE INDEX IF NOT EXISTS idx_posts_hash ON posts(content_hash);
        CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);



        CREATE TABLE IF NOT EXISTS keywords (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT UNIQUE NOT NULL,
            active  BOOLEAN DEFAULT 1,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS run_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at          TIMESTAMP,
            completed_at        TIMESTAMP,
            keywords_searched   INTEGER DEFAULT 0,
            posts_found         INTEGER DEFAULT 0,
            new_posts           INTEGER DEFAULT 0,
            errors              TEXT
        );
        """
        self.conn.executescript(schema)
        
        # Safe migrations: add new columns if they don't exist from earlier versions
        for col_sql in [
            "ALTER TABLE posts ADD COLUMN emails TEXT;",
            "ALTER TABLE posts ADD COLUMN primary_url TEXT;",
            "ALTER TABLE posts ADD COLUMN extracted_urls TEXT;",
            "ALTER TABLE posts ADD COLUMN run_id INTEGER;",
            "ALTER TABLE posts ADD COLUMN company_url TEXT;",
            "ALTER TABLE posts ADD COLUMN author_url TEXT;",
        ]:
            try:
                self.conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass
            
        self.conn.commit()
        logger.info("Database schema initialized.")

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def is_duplicate(self, post_urn: str, content_hash: str) -> bool:
        """Check if a post already exists by URN or content hash."""
        if post_urn:
            cursor = self.conn.execute(
                "SELECT 1 FROM posts WHERE post_urn = ? OR content_hash = ? LIMIT 1",
                (post_urn, content_hash),
            )
        else:
            cursor = self.conn.execute(
                "SELECT 1 FROM posts WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            )
        return cursor.fetchone() is not None

    def insert_post(self, parsed: ParsedPost, run_id: int | None = None) -> int:
        """Insert a new post into the database. Returns the row id."""
        raw = parsed.raw
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO posts
                (post_urn, post_url, author_name, author_headline,
                 content, content_hash, role, experience_min, experience_max,
                 locations, skills, emails, primary_url, extracted_urls, company_url, author_url,
                 is_hiring, keyword_matched, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw.post_urn or None,
                raw.post_url,
                raw.author_name,
                raw.author_headline,
                raw.content,
                raw.content_hash,
                parsed.role,
                parsed.experience_min,
                parsed.experience_max,
                json.dumps(parsed.locations),
                json.dumps(parsed.skills),
                json.dumps(parsed.emails),
                parsed.primary_url,
                json.dumps(parsed.extracted_urls),
                parsed.company_url or "",
                parsed.author_url or "",
                parsed.is_hiring,
                raw.keyword_matched,
                run_id,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_post_id_by_urn(self, post_urn: str) -> Optional[int]:
        """Get the internal post ID by LinkedIn URN."""
        cursor = self.conn.execute(
            "SELECT id FROM posts WHERE post_urn = ?", (post_urn,)
        )
        row = cursor.fetchone()
        return row["id"] if row else None



    # ------------------------------------------------------------------
    # Keywords
    # ------------------------------------------------------------------

    def get_active_keywords(self) -> list[str]:
        """Return all active keywords."""
        cursor = self.conn.execute(
            "SELECT keyword FROM keywords WHERE active = 1 ORDER BY keyword"
        )
        return [row["keyword"] for row in cursor.fetchall()]

    def add_keyword(self, keyword: str):
        """Add a new keyword (or reactivate if it existed)."""
        self.conn.execute(
            """
            INSERT INTO keywords (keyword, active) VALUES (?, 1)
            ON CONFLICT(keyword) DO UPDATE SET active = 1
            """,
            (keyword,),
        )
        self.conn.commit()
        logger.info("Keyword added/reactivated: %s", keyword)

    def remove_keyword(self, keyword: str):
        """Deactivate a keyword (soft delete)."""
        self.conn.execute(
            "UPDATE keywords SET active = 0 WHERE keyword = ?", (keyword,)
        )
        self.conn.commit()
        logger.info("Keyword deactivated: %s", keyword)

    def seed_default_keywords(self, defaults: list[str]):
        """Insert default keywords if the keywords table is empty."""
        cursor = self.conn.execute("SELECT COUNT(*) as cnt FROM keywords")
        if cursor.fetchone()["cnt"] == 0:
            for kw in defaults:
                self.conn.execute(
                    "INSERT OR IGNORE INTO keywords (keyword) VALUES (?)", (kw,)
                )
            self.conn.commit()
            logger.info("Seeded %d default keywords.", len(defaults))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        """Get a setting value by key."""
        cursor = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        """Set a setting value by key."""
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Run log
    # ------------------------------------------------------------------

    def log_run(self, stats: RunStats):
        """Record the results of a monitor run."""
        self.conn.execute(
            """
            INSERT INTO run_log
                (started_at, completed_at, keywords_searched,
                 posts_found, new_posts, errors)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                stats.started_at.isoformat(),
                stats.completed_at.isoformat() if stats.completed_at else None,
                stats.keywords_searched,
                stats.posts_found,
                stats.new_posts,
                json.dumps(stats.errors) if stats.errors else None,
            ),
        )
        self.conn.commit()
        # Return the run_log id so callers can associate posts with this run
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return overall statistics."""
        stats = {}
        cursor = self.conn.execute("SELECT COUNT(*) as cnt FROM posts")
        stats["total_posts"] = cursor.fetchone()["cnt"]

        cursor = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM posts WHERE is_hiring = 1"
        )
        stats["hiring_posts"] = cursor.fetchone()["cnt"]



        cursor = self.conn.execute("SELECT COUNT(*) as cnt FROM run_log")
        stats["total_runs"] = cursor.fetchone()["cnt"]

        return stats

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_old_posts(self, retention_days: int = 90):
        """Remove posts older than the retention period."""
        cutoff = datetime.now() - timedelta(days=retention_days)
        cursor = self.conn.execute(
            "DELETE FROM posts WHERE created_at < ?", (cutoff.isoformat(),)
        )
        self.conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("Cleaned up %d posts older than %d days.", deleted, retention_days)
