"""
Telegram notifications — stdlib only.

Enable by setting TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env:
  1. Talk to @BotFather on Telegram, /newbot, copy the token.
  2. Send your bot any message, then open
     https://api.telegram.org/bot<TOKEN>/getUpdates and copy "chat":{"id":...}.

Only posts scoring >= config.NOTIFY_MIN_SCORE are sent, newest/highest first,
capped at config.NOTIFY_MAX_PER_RUN so a big backfill can't flood the chat.
"""

from __future__ import annotations

import html
import json
import logging
import urllib.error
import urllib.request

import config
from storage.models import FilteredPost

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10


def is_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def format_post(fp: FilteredPost) -> str:
    """HTML-formatted message for one post (Telegram's parse_mode=HTML)."""
    p = fp.parsed
    e = html.escape
    lines = [
        f"<b>{e(p.role or 'Job Opportunity')}</b>  <i>score {fp.relevance_score}</i>",
        f"🏢 {e(p.raw.author_name or 'Unknown')}",
        f"📍 {e(p.location_str)}   🎯 {e(p.experience_str)}",
    ]
    if p.skills:
        lines.append("🛠 " + e(", ".join(p.skills[:8])))
    if p.primary_url:
        lines.append(f'🔗 <a href="{e(p.primary_url)}">Apply</a>')
    if p.emails:
        lines.append("✉️ " + e(", ".join(p.emails[:2])))
    if p.raw.post_url:
        lines.append(f'💬 <a href="{e(p.raw.post_url)}">View post</a>')
    elif p.author_url:
        lines.append(f'👤 <a href="{e(p.author_url)}">Author profile</a>')
    snippet = " ".join((p.raw.clean_content or "").split())[:280]
    if snippet:
        lines.append("")
        lines.append(e(snippet) + ("…" if len(p.raw.clean_content or "") > 280 else ""))
    return "\n".join(lines)


def send_message(text: str) -> bool:
    """POST one message. Returns True on success; never raises."""
    if not is_configured():
        return False
    payload = json.dumps({
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        _API.format(token=config.TELEGRAM_BOT_TOKEN),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return True
            logger.warning("Telegram rejected message: %s", body.get("description"))
    except urllib.error.HTTPError as exc:
        logger.warning("Telegram HTTP %s: %s", exc.code, exc.read()[:200])
    except Exception as exc:  # network down, DNS, timeout
        logger.warning("Telegram send failed: %s", exc)
    return False


def notify_posts(posts: list[FilteredPost],
                 min_score: int | None = None,
                 max_per_run: int | None = None) -> int:
    """Send the best posts of a run. Returns how many were delivered."""
    if not is_configured():
        logger.debug("Telegram not configured; skipping notifications.")
        return 0
    if min_score is None:
        min_score = config.NOTIFY_MIN_SCORE
    if max_per_run is None:
        max_per_run = config.NOTIFY_MAX_PER_RUN

    eligible = sorted(
        (p for p in posts if p.relevance_score >= min_score),
        key=lambda p: p.relevance_score,
        reverse=True,
    )
    sent = 0
    for fp in eligible[:max_per_run]:
        if send_message(format_post(fp)):
            sent += 1
    skipped = len(eligible) - min(len(eligible), max_per_run)
    if skipped:
        send_message(f"…and {skipped} more post(s) scoring ≥ {min_score}. Open the dashboard to see them.")
    logger.info("Telegram: sent %d/%d eligible posts (min score %d).", sent, len(eligible), min_score)
    return sent
