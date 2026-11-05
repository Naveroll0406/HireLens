"""
LinkedIn AI Job Post Monitor — Main Pipeline

Orchestrates the full workflow:
  Scrape → Deduplicate → Parse → Score → Store → Notify → Log

Usage:
  python main.py                    # Run once
  python main.py --dry-run          # Scrape, parse & score; write nothing
  python main.py --deep             # Force the 7-day lookback window
  python main.py --stats            # Show database statistics
  python main.py --add-keyword "AI"  # Add a search keyword
  python main.py --remove-keyword "AI"  # Remove a search keyword
  python main.py --list-keywords     # List active keywords
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure the project root is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from notifications import telegram
from processing import llm_scoring
from processing.dedup import Deduplicator
from processing.filters import apply_all_filters
from processing.parser import parse_post
from processing.scoring import score_post
from scraper.linkedin import BlockedError, LinkedInScraper
from storage.database import Database
from storage.models import FilteredPost, RunStats

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging():
    """Configure logging to both console and file."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(config.LOG_FORMAT, config.LOG_DATE_FORMAT))
    root_logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(str(config.LOG_FILE), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(config.LOG_FORMAT, config.LOG_DATE_FORMAT))
    root_logger.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def _should_deep_scan(db: Database, force: bool = False) -> bool:
    """Use the long lookback window once every DEEP_SCAN_EVERY_HOURS."""
    if force:
        return True
    last = db.last_deep_scan_at()
    if last is None:
        return True
    age_hours = (datetime.now() - last).total_seconds() / 3600
    return age_hours >= config.DEEP_SCAN_EVERY_HOURS


def _threshold_from_db(db: Database) -> int:
    """Dashboard-configurable score threshold, falling back to config."""
    raw = db.get_setting("relevance_threshold", "")
    try:
        return int(raw) if raw else config.RELEVANCE_THRESHOLD
    except ValueError:
        return config.RELEVANCE_THRESHOLD


async def run_pipeline(dry_run: bool = False, url: str = "",
                       filter_locations: list[str] | None = None,
                       filter_experience: tuple[int, int] | None = None,
                       deep: bool = False,
                       use_llm: bool | None = None,
                       ) -> RunStats:
    """Execute the full monitor pipeline.

    1. Initialize database, load keywords (or use the direct URL)
    2. Scrape LinkedIn Posts (24h window; 7d once a day or with --deep)
    3. Deduplicate against the database (URN, content hash, SimHash)
    4. Parse posts (role, experience, location, skills, links)
    5. Score posts; those at/above the threshold are "hiring" posts
    6. Store every new post (rejects too, for dedup and tuning)
    7. Push the best posts to Telegram (if configured)
    8. Log run statistics — exactly one run_log row per run

    dry_run: scrape, parse and score, but write nothing (no posts, no run_log,
             no notifications).
    url:     scrape this LinkedIn search URL instead of the keyword list.
    filter_locations / filter_experience: dashboard overrides for scoring.
    deep:    force the long lookback window.
    """
    stats = RunStats()
    db = Database(config.DATABASE_PATH)
    scraper = LinkedInScraper()
    dedup = Deduplicator(db)
    run_id: int | None = None

    try:
        # --- Step 1: Initialize ---
        db.init_db()
        db.seed_default_keywords(config.DEFAULT_KEYWORDS)
        threshold = _threshold_from_db(db)
        if use_llm is None:
            use_llm = db.get_setting("use_llm_scoring", "1") == "1"
        use_llm = bool(use_llm) and llm_scoring.is_configured()

        keywords = db.get_active_keywords() or list(config.DEFAULT_KEYWORDS)
        stats.keywords_searched = 1 if url else len(keywords)
        stats.deep_scan = bool(not url and _should_deep_scan(db, force=deep))
        window = config.SEARCH_WINDOW_DEEP_SECONDS if stats.deep_scan else config.SEARCH_WINDOW_SECONDS

        logger.info("=" * 70)
        logger.info("🚀 Starting LinkedIn Monitor Run")
        if url:
            logger.info("   Mode: Direct URL | Dry Run: %s", dry_run)
            logger.info("   URL: %s", url[:80])
        else:
            logger.info("   Keywords: %d | Window: %dh | Deep scan: %s | Dry Run: %s",
                        len(keywords), window // 3600, stats.deep_scan, dry_run)
        logger.info("   Score threshold: %d", threshold)
        logger.info("=" * 70)

        if not dry_run:
            run_id = db.log_run(stats)  # placeholder row; finalised in `finally`

        # --- Step 2: Browser + login ---
        await scraper.start()
        if not await scraper.ensure_logged_in():
            logger.error("Cannot proceed without LinkedIn login.")
            stats.errors.append("LinkedIn login failed")
            return stats

        # --- Step 3: Scrape ---
        if url:
            raw_posts = await scraper.search_direct_url(url)
        else:
            raw_posts = await scraper.search_all_keywords(keywords, window_seconds=window)
        stats.posts_found = len(raw_posts)
        logger.info("📥 Total raw posts scraped: %d", len(raw_posts))
        if not raw_posts:
            logger.info("No posts found. Ending run.")
            return stats

        # --- Step 4: Deduplicate ---
        new_posts = dedup.filter_new_posts(raw_posts)
        stats.duplicates_removed = len(raw_posts) - len(new_posts)
        logger.info("🆕 New (unseen) posts: %d", len(new_posts))
        if not new_posts:
            logger.info("No new posts. Ending run.")
            return stats

        # --- Step 5: Parse (worker threads: parse_post resolves short URLs) ---
        parsed_posts = await asyncio.gather(
            *(asyncio.to_thread(parse_post, raw) for raw in new_posts)
        )

        # --- Step 6: Score + store ---
        # The rule engine always runs, so there is a score even with no API
        # key, no network, or a Gemini outage.
        for parsed in parsed_posts:
            score_post(parsed, target_locations=filter_locations,
                       experience_range=filter_experience)

        # Optional second pass: let Gemini override the scores. Never fatal -
        # on any failure every post keeps the rule score just computed.
        if use_llm:
            engine, detail = llm_scoring.apply(
                parsed_posts,
                target_locations=filter_locations,
                experience_range=filter_experience,
                profile=db.get_setting("candidate_profile",
                                       llm_scoring.DEFAULT_PROFILE),
            )
        else:
            engine, detail = "rules", "LLM scoring disabled"
            for parsed in parsed_posts:
                parsed.rule_score = parsed.relevance_score
                parsed.scored_by = "rules"
        stats.scored_by = engine
        logger.info("Scoring engine: %s (%s)", engine, detail)

        filtered_posts: list[FilteredPost] = []
        for parsed in parsed_posts:
            filtered = apply_all_filters(
                parsed,
                target_locations=filter_locations,
                experience_range=filter_experience,
                threshold=threshold,
                rescore=False,
            )
            # is_hiring is what the dashboard shows by default; the score and
            # breakdown are stored alongside so rejects can be reviewed.
            parsed.is_hiring = filtered is not None
            if filtered:
                filtered_posts.append(filtered)
            if not dry_run:
                db.insert_post(parsed, run_id=run_id)

        stats.filtered_out = len(new_posts) - len(filtered_posts)
        stats.new_posts = len(filtered_posts)
        logger.info("🔍 Scored: %d/%d posts at or above %d", len(filtered_posts), len(new_posts), threshold)

        # --- Step 7: Notify ---
        if filtered_posts and not dry_run:
            stats.notified = telegram.notify_posts(filtered_posts)

    except BlockedError as e:
        logger.error("🚫 %s", e)
        stats.blocked = True
        stats.errors.append(f"blocked: {e}")

    except Exception as e:
        logger.exception("❌ Pipeline error: %s", e)
        stats.errors.append(str(e))

    finally:
        await scraper.stop()
        stats.completed_at = datetime.now()
        if not dry_run:
            if run_id is None:
                run_id = db.log_run(stats)
            else:
                db.update_run(run_id, stats)
            db.cleanup_old_posts(config.POST_RETENTION_DAYS)
        db.close()

        logger.info("=" * 70)
        logger.info("📊 %s", stats.summary())
        logger.info("=" * 70)

    return stats


# ---------------------------------------------------------------------------
# CLI utilities
# ---------------------------------------------------------------------------


def show_stats():
    """Display database statistics."""
    db = Database(config.DATABASE_PATH)
    db.init_db()
    stats = db.get_stats()
    db.close()

    print("\n📊 LinkedIn Monitor Statistics")
    print("─" * 40)
    print(f"  Total posts tracked:    {stats['total_posts']}")
    print(f"  Hiring posts:           {stats['hiring_posts']}")
    print(f"  Total runs:             {stats['total_runs']}")
    print("─" * 40)


def show_feedback():
    """Print the most common phrases in 'not relevant' feedback reasons."""
    db = Database(config.DATABASE_PATH)
    db.init_db()
    phrases = db.feedback_phrase_counts(min_count=2)
    recent = db.get_feedback(limit=10)
    db.close()

    print("\n🧭 Feedback phrases (add recurring ones to NON_HIRING_SIGNALS / ABSOLUTE_REJECT_PHRASES)")
    print("─" * 60)
    if not phrases:
        print("  No recurring phrases yet — mark posts 'Not relevant' in the dashboard with a reason.")
    for phrase, count in phrases:
        print(f"  {count:3d}× {phrase}")
    if recent:
        print("\nMost recent feedback:")
        for fb in recent:
            print(f"  [{fb['verdict']}] {fb['role'] or '-'} — {fb['reason'] or '(no reason)'}")


def list_keywords():
    """List all active keywords."""
    db = Database(config.DATABASE_PATH)
    db.init_db()
    db.seed_default_keywords(config.DEFAULT_KEYWORDS)
    keywords = db.get_active_keywords()
    db.close()

    print(f"\n🔑 Active Keywords ({len(keywords)}):")
    print("─" * 40)
    for i, kw in enumerate(keywords, 1):
        print(f"  {i:2d}. {kw}")


def add_keyword(keyword: str):
    """Add a search keyword."""
    db = Database(config.DATABASE_PATH)
    db.init_db()
    db.add_keyword(keyword)
    db.close()
    print(f"✅ Added keyword: '{keyword}'")


def remove_keyword(keyword: str):
    """Remove (deactivate) a search keyword."""
    db = Database(config.DATABASE_PATH)
    db.init_db()
    db.remove_keyword(keyword)
    db.close()
    print(f"🗑️  Removed keyword: '{keyword}'")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="LinkedIn AI Job Post Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                      Run monitor once
  python main.py --dry-run            Scrape, parse & score without writing anything
  python main.py --deep               Use the 7-day lookback window
  python main.py --feedback           Show recurring 'not relevant' phrases for tuning
  python main.py --stats              Show database statistics
  python main.py --list-keywords      List all active search keywords
  python main.py --add-keyword "AI"   Add a search keyword
  python main.py --remove-keyword "AI"  Remove a search keyword
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape, parse and score but write nothing to the database",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Force the 7-day lookback window for this run",
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="Show recurring phrases from 'not relevant' feedback (for tuning config.py)",
    )
    parser.add_argument(
        "--url",
        type=str,
        metavar="URL",
        help="Scrape a specific LinkedIn search URL directly",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show database statistics",
    )
    parser.add_argument(
        "--list-keywords",
        action="store_true",
        help="List all active search keywords",
    )
    parser.add_argument(
        "--add-keyword",
        type=str,
        metavar="KEYWORD",
        help="Add a search keyword",
    )
    parser.add_argument(
        "--remove-keyword",
        type=str,
        metavar="KEYWORD",
        help="Remove a search keyword",
    )

    args = parser.parse_args()

    setup_logging()

    # Handle utility commands (no browser needed)
    if args.stats:
        show_stats()
        return

    if args.list_keywords:
        list_keywords()
        return

    if args.add_keyword:
        add_keyword(args.add_keyword)
        return

    if args.remove_keyword:
        remove_keyword(args.remove_keyword)
        return

    if args.feedback:
        show_feedback()
        return

    # Run the main pipeline
    stats = asyncio.run(run_pipeline(dry_run=args.dry_run, url=args.url or "", deep=args.deep))

    # Exit with error code if there were errors
    if stats.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
