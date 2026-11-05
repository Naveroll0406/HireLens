"""
Background scraper runner.

The old dashboard kept the run flag and the result stats in
``st.session_state`` and wrote to them *from the worker thread*.  That had two
real failure modes:

1. ``st.session_state`` belongs to one browser session.  The page used a
   ``<meta http-equiv="refresh">`` to poll while scraping, and a full browser
   reload starts a *new* session - so the "running" flag and the finished
   stats were thrown away mid-run, leaving the UI stuck or blank.
2. Writing session state from a non-script thread is not supported and raises
   ``NoSessionContext`` warnings once the script run has ended.

State lives here instead: module level, guarded by a lock.  This module is
*imported*, so unlike `dashboard.py` (which Streamlit re-executes top to
bottom on every interaction) its globals survive reruns, reloads and multiple
browser tabs.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

_LOCK = threading.RLock()

_STATE: dict[str, Any] = {
    "running": False,
    "url": "",
    "started_at": None,
    "finished_at": None,
    "since_run_id": None,   # max run_log id before the run, to isolate new posts
    "stats": None,          # dict of counters from the last finished run
    "error": None,
}


def snapshot() -> dict[str, Any]:
    """A copy of the current state, safe to read from the script thread."""
    with _LOCK:
        return dict(_STATE)


def is_running() -> bool:
    with _LOCK:
        return bool(_STATE["running"])


def elapsed_seconds() -> float:
    with _LOCK:
        started = _STATE["started_at"]
        if not started or not _STATE["running"]:
            return 0.0
        return (datetime.now() - started).total_seconds()


def reset_results() -> None:
    """Drop the last run's stats (used by the 'dismiss' control)."""
    with _LOCK:
        if not _STATE["running"]:
            _STATE["stats"] = None
            _STATE["error"] = None


def _finish(stats: dict[str, Any] | None, error: str | None) -> None:
    with _LOCK:
        _STATE["running"] = False
        _STATE["finished_at"] = datetime.now()
        _STATE["stats"] = stats
        _STATE["error"] = error


def start(url: str,
          since_run_id: int | None = None,
          filter_locations: list[str] | None = None,
          filter_experience: tuple[int, int] | None = None) -> bool:
    """Kick off a pipeline run in a daemon thread.

    Returns False if a run is already in flight, so a double-click cannot open
    two Playwright browsers against the same profile directory.
    """
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE.update(
            running=True,
            url=url,
            started_at=datetime.now(),
            finished_at=None,
            since_run_id=since_run_id,
            stats=None,
            error=None,
        )

    # Copy the mutable filters so a later sidebar edit cannot mutate them
    # underneath the running pipeline.
    locations = list(filter_locations) if filter_locations else None
    experience = tuple(filter_experience) if filter_experience else None

    def _work() -> None:
        try:
            import asyncio
            import sys

            from main import run_pipeline, setup_logging

            setup_logging()

            # On Windows the default SelectorEventLoop cannot spawn the
            # subprocess Playwright needs, and a thread gets no loop at all.
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                stats = loop.run_until_complete(run_pipeline(
                    dry_run=False,
                    url=url,
                    filter_locations=locations,
                    filter_experience=experience,
                ))
            finally:
                # Let pending transports close before tearing the loop down,
                # otherwise Playwright logs "Event loop is closed" on exit.
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)

            _finish({
                "posts_found": getattr(stats, "posts_found", 0),
                "duplicates_removed": getattr(stats, "duplicates_removed", 0),
                "filtered_out": getattr(stats, "filtered_out", 0),
                "new_posts": getattr(stats, "new_posts", 0),
                "notified": getattr(stats, "notified", 0),
                "blocked": getattr(stats, "blocked", False),
                "duration": getattr(stats, "duration_seconds", 0.0),
                "errors": list(getattr(stats, "errors", []) or []),
                "url_used": url,
            }, None)
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            _finish(None, f"{type(exc).__name__}: {exc}")

    threading.Thread(target=_work, name="hirelens-scraper", daemon=True).start()
    return True
