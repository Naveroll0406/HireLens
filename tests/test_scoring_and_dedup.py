"""Unit tests for scoring, SimHash near-duplicates, timestamps and Telegram formatting."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import config
from notifications import telegram
from processing.dedup import Deduplicator
from processing.filters import apply_all_filters
from processing.parser import parse_post, parse_relative_timestamp
from processing.scoring import format_breakdown, score_post
from processing.simhash import hamming_distance, is_near_duplicate, simhash
from storage.database import Database
from storage.models import FilteredPost

JD = (
    "We are hiring an AI Engineer for our Bangalore office. Requirements: 2-4 years of "
    "hands-on Python, LangChain, RAG pipelines, vector databases such as Pinecone or Chroma, "
    "and FastAPI. You will design and ship agentic workflows on top of LLMs, work closely "
    "with product, and own evaluation. Hybrid, 3 days a week. Apply at careers.acme.com or "
    "DM me with your resume. Immediate joiners preferred."
)


# ---------------------------------------------------------------------------
# SimHash
# ---------------------------------------------------------------------------

class TestSimHash:
    def test_same_jd_different_intro_is_near(self):
        a = simhash("Excited to share! " + JD)
        b = simhash(JD + " #hiring #genai #bangalore")
        assert is_near_duplicate(a, b), hamming_distance(a, b)

    def test_changed_experience_is_a_candidate_only(self):
        # The fingerprint alone cannot tell a changed experience range apart —
        # that is the Deduplicator's semantic tie-break's job (tested below).
        a = simhash(JD)
        b = simhash(JD.replace("2-4 years", "5-7 years"))
        assert is_near_duplicate(a, b), hamming_distance(a, b)

    def test_unrelated_far_apart(self):
        other = (
            "Join us for a webinar on machine learning trends in India this year. We cover "
            "insights on the ecosystem, register at the link and share with your network. "
            "Topics include MLOps, data platforms, and career growth for early engineers."
        )
        assert hamming_distance(simhash(JD), simhash(other)) > 15

    def test_short_text_has_no_fingerprint(self):
        assert simhash("hiring ai engineer pune") == 0
        assert not is_near_duplicate(0, 0)


# ---------------------------------------------------------------------------
# Dedup with near-duplicates
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db")
    database.init_db()
    yield database
    database.close()


def test_cross_author_near_duplicate_in_batch(db, make_raw):
    a = make_raw(post_urn="urn:1", author_name="Asha", content="Excited to share! " + JD)
    b = make_raw(post_urn="urn:2", author_name="Bala", content=JD + " #hiring")
    assert len(Deduplicator(db).filter_new_posts([a, b])) == 1


def test_cross_author_near_duplicate_against_db(db, make_raw):
    a = make_raw(post_urn="urn:1", author_name="Asha", content=JD)
    db.insert_post(parse_post(a))
    b = make_raw(post_urn="urn:2", author_name="Bala", content="Sharing for reach: " + JD)
    assert Deduplicator(db).filter_new_posts([b]) == []


def test_same_author_different_experience_not_duplicate(db, make_raw):
    a = make_raw(post_urn="urn:1", content=JD)
    b = make_raw(post_urn="urn:2", content=JD.replace("2-4 years", "5-7 years"))
    assert len(Deduplicator(db).filter_new_posts([a, b])) == 2


def test_reaction_counts_do_not_change_hash(make_raw):
    a = make_raw(content=JD + "\n12 likes\n3 comments\n2h\nLike Comment Repost Send")
    b = make_raw(content=JD + "\n45 likes\n9 comments\n5h")
    assert a.content_hash == b.content_hash


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestScoring:
    def test_good_post_scores_high(self, make_raw):
        p = parse_post(make_raw(content=JD))
        score_post(p)
        assert p.relevance_score >= 80
        assert "ai_role_in_title" in p.score_breakdown
        assert "location_match" in p.score_breakdown

    def test_too_much_experience_drops_below_threshold(self, make_raw):
        p = parse_post(make_raw(content=JD.replace("2-4 years", "12+ years")))
        score_post(p)
        assert "experience_too_high" in p.score_breakdown
        assert p.relevance_score < config.RELEVANCE_THRESHOLD

    def test_location_override_flips_match_to_mismatch(self, make_raw):
        p = parse_post(make_raw(content=JD))
        score_post(p, target_locations=["Pune"])
        assert "location_mismatch" in p.score_breakdown

    def test_experience_override(self, make_raw):
        p = parse_post(make_raw(content=JD))
        score_post(p, experience_range=(0, 1))
        assert "experience_too_high" in p.score_breakdown

    def test_breakdown_is_persisted_as_reason(self, make_raw):
        p = parse_post(make_raw(content=JD))
        apply_all_filters(p)
        assert p.filter_reason == format_breakdown(p.score_breakdown)
        assert "+" in p.filter_reason

    def test_threshold_override(self, make_raw):
        p = parse_post(make_raw(content=JD))
        assert apply_all_filters(p, threshold=101) is None
        assert apply_all_filters(p, threshold=0) is not None

    def test_score_clamped(self, make_raw):
        p = parse_post(make_raw(content="I am open to work. Hire me. My resume attached."))
        score_post(p)
        assert p.relevance_score == 0
        assert "absolute_reject" in p.score_breakdown


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

class TestTimestamps:
    NOW = datetime(2026, 9, 18, 12, 0, 0)

    @pytest.mark.parametrize("text,delta", [
        ("2h", timedelta(hours=2)),
        ("3 days ago • Edited", timedelta(days=3)),
        ("1w", timedelta(weeks=1)),
        ("45m", timedelta(minutes=45)),
        ("1mo", timedelta(days=30)),
        ("Just now", timedelta(0)),
    ])
    def test_relative(self, text, delta):
        assert parse_relative_timestamp(text, self.NOW) == self.NOW - delta

    def test_unparseable(self):
        assert parse_relative_timestamp("Recent", self.NOW) is None
        assert parse_relative_timestamp("", self.NOW) is None

    def test_parse_post_fills_posted_at(self, make_raw):
        raw = make_raw(content=JD, timestamp_text="2h")
        parsed = parse_post(raw)
        assert parsed.raw.posted_at is not None
        assert abs((raw.scraped_at - parsed.raw.posted_at) - timedelta(hours=2)) < timedelta(seconds=1)


# ---------------------------------------------------------------------------
# Telegram (no network)
# ---------------------------------------------------------------------------

class TestTelegram:
    def test_format_escapes_html(self, make_raw):
        p = parse_post(make_raw(content=JD + " <b>bold</b>"))
        p.role = "AI <Engineer>"
        msg = telegram.format_post(FilteredPost(parsed=p, relevance_score=90))
        assert "&lt;Engineer&gt;" in msg
        assert "score 90" in msg
        assert "<b>AI &lt;Engineer&gt;</b>" in msg

    def test_not_configured_sends_nothing(self, make_raw, monkeypatch):
        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
        p = parse_post(make_raw(content=JD))
        assert telegram.notify_posts([FilteredPost(parsed=p, relevance_score=95)]) == 0

    def test_notify_respects_min_score_and_cap(self, make_raw, monkeypatch):
        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "t")
        monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "c")
        sent: list[str] = []
        monkeypatch.setattr(telegram, "send_message", lambda text: sent.append(text) or True)
        posts = [
            FilteredPost(parsed=parse_post(make_raw(content=JD, post_urn=f"urn:{i}")), relevance_score=s)
            for i, s in enumerate([95, 90, 85, 60])
        ]
        assert telegram.notify_posts(posts, min_score=70, max_per_run=2) == 2
        # two posts + one "…and N more" summary
        assert len(sent) == 3 and "1 more" in sent[-1]
