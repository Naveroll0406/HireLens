"""Smoke-test the Streamlit dashboard with AppTest against a temp database.

Skipped when streamlit isn't installed (the unit-test env doesn't need it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import config  # noqa: E402
from processing.filters import apply_all_filters  # noqa: E402
from processing.parser import parse_post  # noqa: E402
from storage.database import Database  # noqa: E402
from storage.models import RunStats  # noqa: E402

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard.py"


@pytest.fixture
def seeded_db(tmp_path, monkeypatch, make_raw):
    """Point config at a temp DB holding one accepted and one rejected post."""
    db_path = tmp_path / "dash.db"
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    # The dashboard memoises its aggregate queries and the FTS probe; clear
    # them so each test looks at *this* database rather than the last one's.
    import dashboard
    dashboard.ensure_db.clear()
    dashboard.fts_available.clear()
    dashboard.invalidate_caches()

    db = Database(db_path)
    db.init_db()
    run_id = db.log_run(RunStats())
    posts = [
        make_raw(
            post_urn="urn:li:activity:1",
            content="We're hiring an AI Engineer in Bangalore! 2-4 years with LangChain and RAG. "
                    "Apply at https://acme.greenhouse.io/jobs/1",
            timestamp_text="2h",
        ),
        make_raw(
            post_urn="urn:li:activity:2",
            author_name="Bob Recruiter",
            content="Join us for a webinar on machine learning trends. Register at https://ev.example",
            timestamp_text="1d",
        ),
    ]
    for raw in posts:
        parsed = parse_post(raw)
        parsed.is_hiring = apply_all_filters(parsed) is not None
        db.insert_post(parsed, run_id=run_id)
    stats = RunStats()
    stats.posts_found = 2
    stats.new_posts = 1
    db.update_run(run_id, stats)
    db.close()
    return db_path


def _run_app() -> AppTest:
    at = AppTest.from_file(str(DASHBOARD), default_timeout=60)
    at.run()
    return at


def test_dashboard_renders_without_exceptions(seeded_db):
    at = _run_app()
    assert not at.exception, [e.value for e in at.exception]
    # The accepted post is shown; its score badge and status controls exist.
    assert any("AI Engineer" in md.value for md in at.markdown)
    assert at.button(key="save_all_1") is not None
    # Sidebar controls added by the scoring/status work
    assert at.slider(key="min_score").value == config.RELEVANCE_THRESHOLD
    assert set(at.multiselect(key="status_filter").value) == {"new", "saved", "applied"}


def test_status_button_persists(seeded_db):
    at = _run_app()
    at.button(key="save_all_1").click().run()
    assert not at.exception, [e.value for e in at.exception]

    db = Database(seeded_db)
    db.init_db()
    row = db.conn.execute("SELECT status FROM posts WHERE id = 1").fetchone()
    db.close()
    assert row["status"] == "saved"


def test_not_relevant_records_feedback(seeded_db):
    at = _run_app()
    # Show the rejected post too so we can mark it
    at.checkbox[0].set_value(False)  # "Only show posts that passed the score threshold"
    at.slider(key="min_score").set_value(0).run()
    assert at.button(key="nr_all_2") is not None
    at.text_input(key="nr_reason_all_2").set_value("webinar promo").run()
    at.button(key="nr_all_2").click().run()
    assert not at.exception, [e.value for e in at.exception]

    db = Database(seeded_db)
    db.init_db()
    fb = db.get_feedback()
    db.close()
    assert fb and fb[0]["verdict"] == "not_relevant" and fb[0]["reason"] == "webinar promo"


def test_fts_search_filters_posts(seeded_db):
    at = _run_app()
    at.text_input(key="search_filter").set_value("langchain").run()
    assert not at.exception, [e.value for e in at.exception]
    values = " ".join(md.value for md in at.markdown)
    assert "AI Engineer" in values
    assert "webinar" not in values.lower() or "Showing 1 opportunities" in values
