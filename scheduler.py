"""
LinkedIn AI Job Post Monitor — Scheduler

Runs the monitor pipeline on a configurable schedule using APScheduler.
Default: every 60 minutes.

Usage:
  python scheduler.py                 # Run with default interval (60 min)
  python scheduler.py --interval 30   # Run every 30 minutes
  python scheduler.py --run-now       # Run immediately, then schedule
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

# Ensure the project root is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from main import run_pipeline, setup_logging

logger = logging.getLogger(__name__)

# Flag for graceful shutdown
_shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logger.info("🛑 Shutdown signal received. Will stop after current run completes...")
    _shutdown_requested = True


async def scheduled_job():
    """The job that runs on schedule."""
    if _shutdown_requested:
        return

    logger.info("⏰ Scheduled run triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    try:
        stats = await run_pipeline(dry_run=False)
        logger.info("✅ Scheduled run complete: %s", stats.summary())
    except Exception as e:
        logger.exception("❌ Scheduled run failed: %s", e)


async def run_scheduler(interval_minutes: int, run_now: bool = False):
    """Run the monitor on a recurring schedule.

    Uses a simple asyncio loop instead of APScheduler for fewer dependencies
    and better async compatibility.
    """
    global _shutdown_requested

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    interval_seconds = interval_minutes * 60

    logger.info("=" * 70)
    logger.info("🕐 LinkedIn Monitor Scheduler Started")
    logger.info("   Interval: every %d minutes", interval_minutes)
    logger.info("   Run now: %s", run_now)
    logger.info("   Press Ctrl+C to stop")
    logger.info("=" * 70)

    if run_now:
        await scheduled_job()

    while not _shutdown_requested:
        # Dynamically fetch interval from database
        try:
            from storage.database import Database
            db = Database(config.DATABASE_PATH)
            db.init_db()
            db_interval = db.get_setting("run_interval_minutes", "")
            if db_interval and int(db_interval) > 0:
                interval_minutes = int(db_interval)
            db.close()
        except Exception as e:
            logger.debug("Failed to read dynamic interval from DB: %s", e)
            
        interval_seconds = interval_minutes * 60
        next_run = datetime.now().strftime("%H:%M:%S")
        logger.info(
            "💤 Next run in %d minutes (sleeping until ~%s + %dm)...",
            interval_minutes,
            next_run,
            interval_minutes,
        )

        # Sleep in small increments to allow graceful shutdown
        for _ in range(interval_seconds):
            if _shutdown_requested:
                break
            await asyncio.sleep(1)

        if not _shutdown_requested:
            await scheduled_job()

    logger.info("🛑 Scheduler stopped gracefully.")


def main():
    """CLI entry point for the scheduler."""
    parser = argparse.ArgumentParser(
        description="LinkedIn Monitor — Scheduled Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=config.RUN_INTERVAL_MINUTES,
        metavar="MINUTES",
        help=f"Minutes between runs (default: {config.RUN_INTERVAL_MINUTES})",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run immediately before starting the schedule",
    )

    args = parser.parse_args()

    setup_logging()

    try:
        asyncio.run(run_scheduler(
            interval_minutes=args.interval,
            run_now=args.run_now,
        ))
    except KeyboardInterrupt:
        logger.info("🛑 Scheduler interrupted. Goodbye!")


if __name__ == "__main__":
    main()
