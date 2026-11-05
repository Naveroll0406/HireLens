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

from processing.simhash import NEAR_DUPLICATE_MAX_DISTANCE, hamming_distance
from storage.models import ParsedPost, RunStats

logger = logging.getLogger(__name__)

# Per-post workflow states the dashboard lets the user set.
POST_STATUSES = ("new", "saved", "applied", "hidden", "not_relevant")


def _to_signed64(value: int) -> int:
    """SQLite INTEGER is signed 64-bit; SimHash is unsigned. Map losslessly."""
    return value - (1 << 64) if value >= (1 << 63) else value


def _from_signed64(value: int) -> int:
    return value + (1 << 64) if value < 0 else value


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
            # No detect_types: timestamps are stored as ISO strings and read
            # back as strings (sqlite3's default converter chokes on the 'T').
            self._conn = sqlite3.connect(str(self.db_path))
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
            filter_reason   TEXT,
            simhash         INTEGER DEFAULT 0,
            posted_at       TIMESTAMP,
            status          TEXT DEFAULT 'new',
            status_updated_at TIMESTAMP,
            keyword_matched TEXT,
            run_id          INTEGER,
            first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_posts_urn ON posts(post_urn);
        CREATE INDEX IF NOT EXISTS idx_posts_hash ON posts(content_hash);
        CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);

        -- User feedback on individual posts ("not relevant" + why). Mined
        -- periodically to grow the reject lists in config.py.
        CREATE TABLE IF NOT EXISTS feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id     INTEGER NOT NULL,
            verdict     TEXT NOT NULL,
            reason      TEXT,
            role        TEXT,
            content     TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
        );

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
            notified            INTEGER DEFAULT 0,
            status              TEXT DEFAULT 'ok',
            deep_scan           BOOLEAN DEFAULT 0,
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
            "ALTER TABLE posts ADD COLUMN filter_reason TEXT;",
            "ALTER TABLE posts ADD COLUMN simhash INTEGER DEFAULT 0;",
            "ALTER TABLE posts ADD COLUMN posted_at TIMESTAMP;",
            "ALTER TABLE posts ADD COLUMN status TEXT DEFAULT 'new';",
            "ALTER TABLE posts ADD COLUMN status_updated_at TIMESTAMP;",
            "ALTER TABLE posts ADD COLUMN relevance_score INTEGER DEFAULT 0;",
            "ALTER TABLE posts ADD COLUMN rule_score INTEGER DEFAULT 0;",
            "ALTER TABLE posts ADD COLUMN scored_by TEXT DEFAULT 'rules';",
            "ALTER TABLE run_log ADD COLUMN duplicates_removed INTEGER DEFAULT 0;",
            "ALTER TABLE run_log ADD COLUMN filtered_out INTEGER DEFAULT 0;",
            "ALTER TABLE run_log ADD COLUMN notified INTEGER DEFAULT 0;",
            "ALTER TABLE run_log ADD COLUMN status TEXT DEFAULT 'ok';",
            "ALTER TABLE run_log ADD COLUMN deep_scan BOOLEAN DEFAULT 0;",
            "ALTER TABLE run_log ADD COLUMN scored_by TEXT DEFAULT 'rules';",
            "CREATE INDEX IF NOT EXISTS idx_posts_posted ON posts(posted_at);",
            "CREATE INDEX IF NOT EXISTS idx_posts_score ON posts(relevance_score);",
            "CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);",
        ]:
            try:
                self.conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass

        # Enforce (author, content) uniqueness at the DB level. Older databases
        # may already hold duplicates, in which case the index can't be built —
        # the Python-side dedup still protects us and we log it.
        try:
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_author_hash "
                "ON posts(author_name, content_hash)"
            )
        except sqlite3.IntegrityError:
            logger.warning(
                "posts has pre-existing (author, content_hash) duplicates; "
                "unique index not created."
            )

        self._init_fts()
        self.conn.commit()
        logger.info("Database schema initialized.")

    def _init_fts(self):
        """Create the FTS5 full-text index over posts, kept in sync by triggers.

        Falls back silently (LIKE search) if this SQLite build lacks FTS5.
        """
        try:
            self.conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
                content, role, author_name, skills,
                content='posts', content_rowid='id',
                tokenize='porter unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
                INSERT INTO posts_fts(rowid, content, role, author_name, skills)
                VALUES (new.id, new.content, new.role, new.author_name, new.skills);
            END;
            CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
                INSERT INTO posts_fts(posts_fts, rowid, content, role, author_name, skills)
                VALUES ('delete', old.id, old.content, old.role, old.author_name, old.skills);
            END;
            CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE OF content, role, author_name, skills ON posts BEGIN
                INSERT INTO posts_fts(posts_fts, rowid, content, role, author_name, skills)
                VALUES ('delete', old.id, old.content, old.role, old.author_name, old.skills);
                INSERT INTO posts_fts(rowid, content, role, author_name, skills)
                VALUES (new.id, new.content, new.role, new.author_name, new.skills);
            END;
            """)
            # Backfill rows inserted before the index existed (idempotent).
            self.conn.execute("INSERT INTO posts_fts(posts_fts) VALUES ('rebuild')")
            self._fts_available = True
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 unavailable (%s); dashboard search will use LIKE.", e)
            self._fts_available = False

    @property
    def fts_available(self) -> bool:
        return getattr(self, "_fts_available", False)

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def is_duplicate(self, post_urn: str, content_hash: str, author_name: str) -> bool:
        """Check if a post already exists by URN, or by exact same content from the same author.

        Two separate lookups so each one can use its own index (SQLite can't
        combine two indexes across an OR).
        """
        if post_urn:
            row = self.conn.execute(
                "SELECT 1 FROM posts WHERE post_urn = ? LIMIT 1", (post_urn,)
            ).fetchone()
            if row is not None:
                return True
        row = self.conn.execute(
            "SELECT 1 FROM posts WHERE content_hash = ? AND author_name = ? LIMIT 1",
            (content_hash, author_name),
        ).fetchone()
        return row is not None

    def find_near_duplicates(self, fingerprint: int, lookback_days: int = 21,
                             max_distance: int = NEAR_DUPLICATE_MAX_DISTANCE) -> list[dict]:
        """Recent posts whose SimHash is within max_distance bits of ``fingerprint``.

        Returns dicts with id / role / experience_min / experience_max so the
        caller can apply a semantic tie-break. Scans only recent, fingerprinted
        rows so the linear Hamming check stays cheap.
        """
        if not fingerprint:
            return []
        cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        cursor = self.conn.execute(
            "SELECT id, simhash, role, experience_min, experience_max FROM posts "
            "WHERE simhash != 0 AND created_at >= ?",
            (cutoff,),
        )
        matches = []
        for row in cursor:
            if hamming_distance(_from_signed64(int(row["simhash"])), fingerprint) <= max_distance:
                matches.append({
                    "id": row["id"], "role": row["role"],
                    "experience_min": row["experience_min"], "experience_max": row["experience_max"],
                })
        return matches

    def insert_post(self, parsed: ParsedPost, run_id: int | None = None) -> int:
        """Insert a new post into the database. Returns the row id."""
        raw = parsed.raw
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO posts
                (post_urn, post_url, author_name, author_headline,
                 content, content_hash, role, experience_min, experience_max,
                 locations, skills, emails, primary_url, extracted_urls, company_url, author_url,
                 is_hiring, relevance_score, filter_reason, simhash, posted_at,
                 keyword_matched, run_id, rule_score, scored_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                parsed.relevance_score,
                parsed.filter_reason,
                _to_signed64(raw.simhash),
                raw.posted_at.isoformat() if raw.posted_at else None,
                raw.keyword_matched,
                run_id,
                parsed.rule_score,
                parsed.scored_by,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def set_post_status(self, post_id: int, status: str):
        """Set the user's workflow status on a post (saved / applied / hidden ...)."""
        if status not in POST_STATUSES:
            raise ValueError(f"Unknown status {status!r}; expected one of {POST_STATUSES}")
        self.conn.execute(
            "UPDATE posts SET status = ?, status_updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(), post_id),
        )
        self.conn.commit()

    def add_feedback(self, post_id: int, verdict: str, reason: str = ""):
        """Record why the user marked a post as (not) relevant, with a content snapshot."""
        row = self.conn.execute(
            "SELECT role, content FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        self.conn.execute(
            "INSERT INTO feedback (post_id, verdict, reason, role, content) VALUES (?, ?, ?, ?, ?)",
            (post_id, verdict, reason.strip(), row["role"] if row else None, row["content"] if row else None),
        )
        self.conn.commit()

    def get_feedback(self, limit: int = 200) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT id, post_id, verdict, reason, role, created_at FROM feedback "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cursor.fetchall()]

    def feedback_phrase_counts(self, min_count: int = 2) -> list[tuple[str, int]]:
        """Most common words/bigrams in 'not relevant' feedback reasons.

        This is the manual tuning loop: review these and promote the
        recurring ones to NON_HIRING_SIGNALS / ABSOLUTE_REJECT_PHRASES.
        """
        import re
        from collections import Counter

        counts: Counter[str] = Counter()
        cursor = self.conn.execute(
            "SELECT reason FROM feedback WHERE verdict = 'not_relevant' AND reason != ''"
        )
        for row in cursor:
            words = re.findall(r"[a-z][a-z'-]+", row["reason"].lower())
            counts.update(words)
            counts.update(f"{a} {b}" for a, b in zip(words, words[1:]))
        return [(p, c) for p, c in counts.most_common(50) if c >= min_count]

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

    def log_run(self, stats: RunStats) -> int:
        """Insert a run_log row and return its id. Call update_run() to finalise it."""
        cursor = self.conn.execute(
            """
            INSERT INTO run_log
                (started_at, completed_at, keywords_searched,
                 posts_found, duplicates_removed, filtered_out, new_posts,
                 notified, status, deep_scan, errors, scored_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._run_row(stats),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_run(self, run_id: int, stats: RunStats):
        """Overwrite a run_log row with the final stats."""
        self.conn.execute(
            """
            UPDATE run_log SET
                started_at = ?, completed_at = ?, keywords_searched = ?,
                posts_found = ?, duplicates_removed = ?, filtered_out = ?, new_posts = ?,
                notified = ?, status = ?, deep_scan = ?, errors = ?, scored_by = ?
            WHERE id = ?
            """,
            (*self._run_row(stats), run_id),
        )
        self.conn.commit()

    @staticmethod
    def _run_row(stats: RunStats) -> tuple:
        return (
            stats.started_at.isoformat(),
            stats.completed_at.isoformat() if stats.completed_at else None,
            stats.keywords_searched,
            stats.posts_found,
            stats.duplicates_removed,
            stats.filtered_out,
            stats.new_posts,
            stats.notified,
            stats.status,
            int(stats.deep_scan),
            json.dumps(stats.errors) if stats.errors else None,
            stats.scored_by,
        )

    def last_run_status(self) -> Optional[str]:
        row = self.conn.execute(
            "SELECT status FROM run_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["status"] if row else None

    def last_deep_scan_at(self) -> Optional[datetime]:
        row = self.conn.execute(
            "SELECT started_at FROM run_log WHERE deep_scan = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row or not row["started_at"]:
            return None
        try:
            return datetime.fromisoformat(row["started_at"])
        except ValueError:
            return None

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
