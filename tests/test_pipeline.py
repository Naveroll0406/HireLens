"""End-to-end pipeline tests with a fake scraper (no browser, no network).

Checks the things that were wrong before: exactly one run_log row per run,
dry-run writing nothing, blocked runs recorded as such, and the rejected
posts being stored with their score for later tuning.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("playwright")  # main imports the Playwright scraper

import config  # noqa: E402
import main  # noqa: E402
from notifications import telegram  # noqa: E402
from storage.database import Database
from storage.models import RawPost

JD = (
    "We are hiring an AI Engineer for our Bangalore office. 2-4 years of Python, LangChain, "
    "RAG and vector databases. Apply at https://acme.com/careers/ai or DM me. #hiring"
)
WEBINAR = "Join us for a webinar on machine learning trends. Register at https://ev.example"


class FakeScraper:
    """Stands in for LinkedInScraper; returns canned posts or raises."""

    def __init__(self, posts=None, raise_exc=None):
        self._posts = posts or []
        self._raise = raise_exc
        self.started = self.stopped = False
        self.window_seconds = None

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def ensure_logged_in(self):
        return True

    async def search_all_keywords(self, keywords, window_seconds=None):
        self.window_seconds = window_seconds
        if self._raise:
            raise self._raise
        return list(self._posts)

    async def search_direct_url(self, url):
        return list(self._posts)


def _raw(urn: str, content: str, author: str = "Jane Recruiter") -> RawPost:
    return RawPost(
        post_urn=urn, author_name=author, author_headline="Talent @ Acme", content=content,
        post_url=f"https://www.linkedin.com/feed/update/{urn}/", author_url="https://www.linkedin.com/in/jane/",
        timestamp_text="2h", keyword_matched="AI Engineer",
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "pipe.db")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    # never resolve shorteners over the network
    monkeypatch.setattr("processing.parser.resolve_shortened_url", lambda url, timeout=None: url)
    return tmp_path


def _use_scraper(monkeypatch, scraper: FakeScraper):
    monkeypatch.setattr(main, "LinkedInScraper", lambda: scraper)


def _open(env) -> Database:
    db = Database(config.DATABASE_PATH)
    db.init_db()
    return db


def test_single_run_log_row_and_scores_persisted(env, monkeypatch):
    scraper = FakeScraper([_raw("urn:1", JD), _raw("urn:2", WEBINAR, author="Bob")])
    _use_scraper(monkeypatch, scraper)

    stats = asyncio.run(main.run_pipeline())

    assert stats.posts_found == 2 and stats.new_posts == 1 and stats.filtered_out == 1
    assert stats.status == "ok" and scraper.stopped

    db = _open(env)
    assert db.conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 1
    run = db.conn.execute("SELECT * FROM run_log").fetchone()
    assert run["new_posts"] == 1 and run["posts_found"] == 2 and run["status"] == "ok"
    assert run["completed_at"] is not None

    rows = {r["post_urn"]: r for r in db.conn.execute("SELECT * FROM posts")}
    assert rows["urn:1"]["is_hiring"] == 1 and rows["urn:1"]["relevance_score"] >= 50
    # the rejected post is stored too, with its score and reason, for tuning
    assert rows["urn:2"]["is_hiring"] == 0 and rows["urn:2"]["relevance_score"] < 50
    assert "no_hiring_signal" in rows["urn:2"]["filter_reason"]
    assert rows["urn:1"]["posted_at"] is not None
    assert rows["urn:1"]["run_id"] == run["id"]
    db.close()


def test_dry_run_writes_nothing(env, monkeypatch):
    _use_scraper(monkeypatch, FakeScraper([_raw("urn:1", JD)]))
    stats = asyncio.run(main.run_pipeline(dry_run=True))
    assert stats.new_posts == 1  # still scored
    db = _open(env)
    assert db.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 0
    db.close()


def test_blocked_run_is_recorded(env, monkeypatch):
    from scraper.linkedin import BlockedError
    scraper = FakeScraper(raise_exc=BlockedError("LinkedIn challenge page ('unusual activity')"))
    _use_scraper(monkeypatch, scraper)

    stats = asyncio.run(main.run_pipeline())

    assert stats.blocked and stats.status == "blocked" and scraper.stopped
    db = _open(env)
    assert db.last_run_status() == "blocked"
    assert db.conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 1
    db.close()


def test_second_run_dedups_and_deep_scan_rotates(env, monkeypatch):
    scraper = FakeScraper([_raw("urn:1", JD)])
    _use_scraper(monkeypatch, scraper)

    first = asyncio.run(main.run_pipeline())
    assert first.deep_scan is True  # never deep-scanned before
    assert scraper.window_seconds == config.SEARCH_WINDOW_DEEP_SECONDS

    second = asyncio.run(main.run_pipeline())
    assert second.deep_scan is False
    assert scraper.window_seconds == config.SEARCH_WINDOW_SECONDS
    assert second.duplicates_removed == 1 and second.new_posts == 0

    db = _open(env)
    assert db.conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 2
    assert db.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
    db.close()


def test_threshold_setting_from_dashboard_is_used(env, monkeypatch):
    db = _open(env)
    db.set_setting("relevance_threshold", "101")
    db.close()
    _use_scraper(monkeypatch, FakeScraper([_raw("urn:1", JD)]))
    stats = asyncio.run(main.run_pipeline())
    # nothing can reach 101, so the dashboard's threshold must have been honoured
    assert stats.new_posts == 0 and stats.filtered_out == 1


def test_notifications_sent_for_accepted_posts(env, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "c")
    sent: list[str] = []
    monkeypatch.setattr(telegram, "send_message", lambda text: sent.append(text) or True)
    _use_scraper(monkeypatch, FakeScraper([_raw("urn:1", JD)]))

    stats = asyncio.run(main.run_pipeline())
    assert stats.notified == 1 and len(sent) == 1 and "AI Engineer" in sent[0]
    db = _open(env)
    assert db.conn.execute("SELECT notified FROM run_log").fetchone()[0] == 1
    db.close()
