"""
LinkedIn AI Job Post Monitor — Main Pipeline

Orchestrates the full workflow:
  Scrape → Parse → Filter → Deduplicate → Notify → Log

Usage:
  python main.py                    # Run once
  python main.py --dry-run          # Scrape & parse
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
from processing.dedup import Deduplicator
from processing.filters import apply_all_filters
from processing.parser import parse_post
from scraper.linkedin import LinkedInScraper
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
    logging.getLogger("telegram").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_pipeline(dry_run: bool = False, url: str = "",
                       filter_locations: list[str] | None = None,
                       filter_experience: tuple[int, int] | None = None,
                       ) -> RunStats:
    """Execute the full monitor pipeline.

    1. Initialize database
    2. Load keywords (or use direct URL)
    3. Scrape LinkedIn Posts
    4. Parse posts (extract role, experience, location, skills)
    5. Filter posts (hiring signal, experience, location, seniority)
    6. Deduplicate against database
    7. Store new posts
    8. Send Telegram notifications (unless dry_run)
    9. Log run statistics

    Args:
        dry_run: If True, scrape & parse but don't send notifications.
        url: If provided, scrape this URL directly instead of using keywords.
        filter_locations: Optional list of accepted locations (overrides config).
        filter_experience: Optional (min, max) experience range (overrides config).

    Returns RunStats with the results.
    """
    stats = RunStats()
    db = Database(config.DATABASE_PATH)
    scraper = LinkedInScraper()
    dedup = Deduplicator(db)

    try:
        # --- Step 1: Initialize ---
        db.init_db()
        db.seed_default_keywords(config.DEFAULT_KEYWORDS)

        # --- Step 2: Get keywords ---
        keywords = db.get_active_keywords()
        if not keywords:
            keywords = config.DEFAULT_KEYWORDS
        stats.keywords_searched = len(keywords) if not url else 1

        logger.info("=" * 70)
        logger.info("🚀 Starting LinkedIn Monitor Run")
        if url:
            logger.info("   Mode: Direct URL | Dry Run: %s", dry_run)
            logger.info("   URL: %s", url[:80])
        else:
            logger.info("   Keywords: %d | Dry Run: %s", len(keywords), dry_run)
        logger.info("=" * 70)

        # --- Step 3: Start browser and check login ---
        await scraper.start()

        if not await scraper.ensure_logged_in():
            logger.error("Cannot proceed without LinkedIn login.")
            stats.errors.append("LinkedIn login failed")
            return stats

        # --- Step 4: Scrape ---
        if url:
            # Direct URL mode — scrape the user-provided URL
            raw_posts = await scraper.search_direct_url(url)
        else:
            # Keyword mode — search all active keywords
            raw_posts = await scraper.search_all_keywords(keywords)
        stats.posts_found = len(raw_posts)
        logger.info("📥 Total raw posts scraped: %d", len(raw_posts))

        if not raw_posts:
            logger.info("No posts found. Ending run.")
            stats.completed_at = datetime.now()
            db.log_run(stats)
            return stats

        # --- Step 5: Deduplicate ---
        new_posts = dedup.filter_new_posts(raw_posts)
        # We don't set stats.new_posts here yet, we set it after filtering to reflect only relevant posts.
        logger.info("🆕 New (unseen) posts: %d", len(new_posts))

        if not new_posts:
            logger.info("No new posts. Ending run.")
            stats.completed_at = datetime.now()
            db.log_run(stats)
            return stats

        # --- Step 6: Parse & Filter ---
        filtered_posts: list[FilteredPost] = []

        # Pre-log run to get a run_id we can tag posts with
        stats.completed_at = datetime.now()  # temporary, will be overwritten
        current_run_id = db.log_run(stats)

        for raw in new_posts:
            # Parse
            parsed = parse_post(raw)

            # Filter (with optional overrides from the dashboard)
            filtered = apply_all_filters(
                parsed,
                target_locations=filter_locations,
                experience_range=filter_experience,
            )
            if filtered:
                filtered_posts.append(filtered)
            else:
                # If it didn't pass our AI/Location filters, we mark it as not hiring
                # so it is hidden by default in the dashboard, but still saved for dedup.
                parsed.is_hiring = False

            # Store ALL new posts in DB (even filtered-out ones, for dedup)
            db.insert_post(parsed, run_id=current_run_id)

        logger.info(
            "🔍 Filtered: %d/%d posts passed all filters",
            len(filtered_posts), len(new_posts),
        )
        
        # Set new_posts to the number of filtered posts for the UI
        stats.new_posts = len(filtered_posts)

        if not filtered_posts:
            logger.info("No posts passed filters. Ending run.")
            stats.completed_at = datetime.now()
            # Update the run log we created earlier
            db.conn.execute("UPDATE run_log SET new_posts = ? WHERE id = ?", (stats.new_posts, current_run_id))
            db.conn.commit()
            return stats

        # --- Step 7: Done (Notifications removed) ---
        stats.completed_at = datetime.now()
        # Update the run log we created earlier
        db.conn.execute("UPDATE run_log SET new_posts = ? WHERE id = ?", (stats.new_posts, current_run_id))
        db.conn.commit()

    except Exception as e:
        logger.exception("❌ Pipeline error: %s", e)
        stats.errors.append(str(e))

    finally:
        # Cleanup
        await scraper.stop()
        stats.completed_at = stats.completed_at or datetime.now()
        db.log_run(stats)
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
  python main.py --dry-run            Scrape & parse without side effects
  python main.py --stats              Show database statistics
  python main.py --list-keywords      List all active search keywords
  python main.py --add-keyword "AI"   Add a search keyword
  python main.py --remove-keyword "AI"  Remove a search keyword
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline without inserting to the database (if needed)",
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

    # Run the main pipeline
    stats = asyncio.run(run_pipeline(dry_run=args.dry_run, url=args.url or ""))

    # Exit with error code if there were errors
    if stats.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
