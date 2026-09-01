"""Unit tests for processing/dedup.py against a real temp SQLite database."""

from __future__ import annotations

import pytest

from processing.dedup import Deduplicator
from processing.parser import parse_post
from storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.init_db()
    yield database
    database.close()


def test_batch_urn_duplicate(db, make_raw):
    """Two posts sharing a URN in the same batch collapse to one."""
    a = make_raw(post_urn="urn:li:activity:100", content="Hiring an AI Engineer in Bangalore now")
    b = make_raw(post_urn="urn:li:activity:100", content="Totally different body text here please")
    result = Deduplicator(db).filter_new_posts([a, b])
    assert len(result) == 1


def test_batch_content_duplicate(db, make_raw):
    """Same author + same normalized content dedupe even without a URN."""
    a = make_raw(post_urn="", content="Hiring an AI Engineer in Bangalore, apply today")
    b = make_raw(post_urn="", content="Hiring an AI Engineer in Bangalore, apply today")
    result = Deduplicator(db).filter_new_posts([a, b])
    assert len(result) == 1


def test_database_duplicate(db, make_raw):
    """A post already stored in the DB is not returned as new on the next run."""
    raw = make_raw(post_urn="urn:li:activity:200", content="Hiring an LLM Engineer, 3 years, apply")
    db.insert_post(parse_post(raw))

    result = Deduplicator(db).filter_new_posts([raw])
    assert result == []


def test_distinct_posts_all_new(db, make_raw):
    a = make_raw(post_urn="urn:li:activity:1", content="Hiring an AI Engineer in Pune, apply now")
    b = make_raw(post_urn="urn:li:activity:2", content="Hiring an MLOps Engineer in Chennai remotely")
    result = Deduplicator(db).filter_new_posts([a, b])
    assert len(result) == 2
