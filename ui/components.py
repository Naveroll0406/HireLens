"""
Presentational helpers for the HireLens dashboard.

Every function here is pure: it takes plain data and returns an HTML string.
Nothing touches Streamlit or the database, so the markup can be unit-tested
directly (see ``tests/test_dashboard.py``).

All interpolated values go through :func:`esc` or :func:`safe_url`.  The old
dashboard escaped only ``<`` and ``>`` in the post body and nothing at all in
role / author / skill names, so a post containing ``&`` or a quote could
corrupt the card markup.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from urllib.parse import urlparse

from ui.motion import stagger_delay
from ui.theme import score_palette

# Only these schemes ever reach an href.
_SAFE_SCHEMES = {"http", "https", "mailto"}

STATUS_META = {
    "new": ("New", "hl-chip-accent"),
    "saved": ("Saved", "hl-chip-violet"),
    "applied": ("Applied", "hl-chip-mint"),
    "hidden": ("Hidden", "hl-chip"),
    "not_relevant": ("Not relevant", "hl-chip-amber"),
}


def esc(value: object, fallback: str = "") -> str:
    """HTML-escape any value, mapping NaN/None to *fallback*."""
    if value is None:
        return html.escape(fallback)
    text = str(value)
    # pandas NaN stringifies to "nan"; treat empty/NaN alike.
    if text in ("nan", "NaT", "None", ""):
        return html.escape(fallback)
    return html.escape(text, quote=True)


def safe_url(url: object) -> str:
    """Return *url* if it is a safe absolute link, else an empty string."""
    if not url:
        return ""
    text = str(url).strip()
    if text in ("nan", "None", ""):
        return ""
    try:
        scheme = urlparse(text).scheme.lower()
    except ValueError:
        return ""
    return text if scheme in _SAFE_SCHEMES else ""


def domain_of(url: str, limit: int = 22) -> str:
    """Short, human-readable host for a link label."""
    try:
        host = urlparse(url).netloc.replace("www.", "")
    except ValueError:
        host = ""
    return host[:limit] or "link"


def parse_json_list(value: object) -> list[str]:
    """Best-effort decode of a JSON-array column into a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v]
    text = str(value).strip()
    if not text or text in ("nan", "None", "[]"):
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(v) for v in data if v] if isinstance(data, list) else []


def format_timestamp(value: object) -> str:
    """Render a stored timestamp as `Mar 04, 14:20`, falling back to raw text."""
    if not value:
        return ""
    text = str(value)
    if text in ("nan", "NaT", "None"):
        return ""
    try:
        return datetime.fromisoformat(text).strftime("%b %d, %H:%M")
    except (ValueError, TypeError):
        return text[:16]


def relative_time(value: object) -> str:
    """`3h ago` / `2d ago` for a stored timestamp, or '' when unparseable."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return ""
    now = datetime.now(moment.tzinfo) if moment.tzinfo else datetime.now()
    delta = now - moment
    seconds = delta.total_seconds()
    if seconds < 0:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 604800:
        return f"{int(seconds // 86400)}d ago"
    return format_timestamp(value)


def format_experience(exp_min: object, exp_max: object) -> str:
    """`2-5 yrs` / `5+ yrs` / `Any experience` from the two stored columns."""
    def _num(v: object) -> int | None:
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if f != f else int(f)  # NaN check

    lo, hi = _num(exp_min), _num(exp_max)
    if lo is not None and hi is not None:
        return f"{lo}-{hi} yrs"
    if lo is not None:
        return f"{lo}+ yrs"
    if hi is not None:
        return f"up to {hi} yrs"
    return "Any experience"


def chip(label: str, icon: str = "", variant: str = "", title: str = "") -> str:
    """A single metadata pill."""
    cls = f"hl-chip {variant}".strip()
    attr = f' title="{esc(title)}"' if title else ""
    body = f"{icon} {esc(label)}" if icon else esc(label)
    return f'<span class="{cls}"{attr}>{body}</span>'


# ---------------------------------------------------------------------------
# Masthead / status
# ---------------------------------------------------------------------------

def masthead(is_running: bool, subtitle: str, pill_text: str = "") -> str:
    status_cls = "hl-status hl-status-live" if is_running else "hl-status"
    status_label = "SCRAPING" if is_running else "IDLE"
    extra = f'<span class="hl-status">{esc(pill_text)}</span>' if pill_text else ""
    progress = '<div class="hl-progress"></div>' if is_running else ""
    # Emitted without indentation and without blank lines on purpose: an empty
    # `extra` used to leave a bare line followed by indented markup, and
    # Streamlit's markdown parser renders 4-space-indented HTML as a *code
    # block* - so the whole masthead appeared as literal <span> text.
    return (
        '<div class="hl-masthead">'
        '<div class="hl-brand">'
        '<div class="hl-logo">&#128270;</div>'
        f'<div><h1 class="hl-wordmark">HireLens</h1>'
        f'<p class="hl-tagline">{esc(subtitle)}</p></div>'
        '</div>'
        f'<div class="hl-masthead-side">{extra}'
        f'<span class="{status_cls}"><span class="hl-dot"></span>{status_label}</span>'
        '</div>'
        f'{progress}'
        '</div>'
    )


def stat_tile(icon: str, value: object, label: str, index: int = 0,
              fill: int = 40, tint: str = "rgba(109,140,255,.35)",
              delta: str = "") -> str:
    style = f"--hl-delay:{stagger_delay(index, step_ms=70)}ms;--hl-tint:{tint};--hl-fill:{max(3, min(100, fill))}%"
    delta_html = f'<span class="hl-stat-delta">{esc(delta)}</span>' if delta else ""
    return f"""<div class="hl-stat" style="{style}">
  <div class="hl-stat-top"><span class="hl-stat-icon">{icon}</span>{delta_html}</div>
  <div class="hl-stat-value">{esc(value)}</div>
  <div class="hl-stat-label">{esc(label)}</div>
  <div class="hl-stat-spark"><i></i></div>
</div>"""


def section_heading(title: str, note: str = "") -> str:
    note_html = f"<span>{esc(note)}</span>" if note else ""
    return f'<div class="hl-section"><h3>{esc(title)}</h3>{note_html}</div>'


def empty_state(title: str, body: str, steps: list[str] | None = None,
                icon: str = "&#128269;") -> str:
    steps_html = ""
    if steps:
        rows = "".join(
            f'<div class="hl-step"><b>{i}</b><span>{esc(s)}</span></div>'
            for i, s in enumerate(steps, 1)
        )
        steps_html = f'<div class="hl-steps">{rows}</div>'
    return f"""<div class="hl-empty">
  <div class="hl-empty-icon">{icon}</div>
  <h3>{esc(title)}</h3>
  <p>{esc(body)}</p>
  {steps_html}
</div>"""


def run_row(index: int, started: object, scraped: int, dupes: int,
            filtered: int, new: int, badge: str = "") -> str:
    style = f"--hl-delay:{stagger_delay(index)}ms"
    badge_html = f'<span class="hl-chip hl-chip-amber">{esc(badge)}</span>' if badge else ""
    return f"""<div class="hl-run" style="{style}">
  <span class="hl-run-time">{esc(format_timestamp(started), "unknown")}</span>
  <span><b>{scraped}</b> scraped</span>
  <span><b>{dupes}</b> dupes</span>
  <span><b>{filtered}</b> filtered</span>
  <span><b>{new}</b> new</span>
  <span class="hl-run-sep"></span>
  {badge_html}
</div>"""


# ---------------------------------------------------------------------------
# Job card
# ---------------------------------------------------------------------------

_EXCERPT_LIMIT = 900

# Interface furniture the scraper picks up along with the post body.  Leaving
# it in means every card opens with "Feed post / Follow / 23h *" before the
# first line that actually matters.
_CHROME_LINE = re.compile(
    r"^(?:"
    r"[​\s]*"                                   # blank / zero-width only
    r"|feed post|suggested|promoted|reposted this"
    r"|follow(?:ing)?|\+ follow|join|connect|send"
    r"|see more|view job\d*|like|comment|repost"
    r"|\d+"                                          # bare reaction counts
    r"|\d+\s*(?:s|m|h|d|w|mo|yr)\b.*"                # "23h *", "2d * Edited *"
    r"|.{0,40}•\s*\d+\s*(?:s|m|h|d|w|mo|yr)\b.*"  # "with 2 others * 23h *"
    r"|.{0,40}•\s*\d+(?:st|nd|rd|th)\+?"        # "* 3rd+"
    r")$",
    re.I,
)


def clean_excerpt(content: str, author: str = "", headline: str = "",
                  max_strip_lines: int = 18) -> str:
    """Drop the LinkedIn actor block from the top of a scraped post.

    The scraper captures the whole post container, so the body is preceded by
    "Feed post / <author> / <headline> / 23h * / Follow".  The card already
    shows the author and headline in its header, so repeating them as the
    first thing in the excerpt wastes the only three lines a reader sees.

    Only the leading block is trimmed: a short line deeper in the post (an
    "Apply" or a bare number) is left alone.
    """
    if not content:
        return ""
    known = {s.strip().lower() for s in (author, headline) if s and s.strip()}
    lines = content.split("\n")
    start = 0
    for i, line in enumerate(lines[:max_strip_lines]):
        stripped = line.strip()
        if _CHROME_LINE.match(stripped) or stripped.lower() in known:
            start = i + 1
        elif stripped:
            break
    return "\n".join(lines[start:]).strip() or content.strip()


def _apply_bar(primary: str, extra: list[str], emails: list[str]) -> str:
    """The call-to-action strip at the bottom of a card."""
    parts: list[str] = []
    if primary:
        parts.append(
            f'<a class="hl-cta" href="{esc(primary)}" target="_blank" rel="noopener noreferrer">'
            f'Apply <span>{esc(domain_of(primary))}</span></a>'
        )
    for link in extra[:4]:
        parts.append(
            f'<a class="hl-link" href="{esc(link)}" target="_blank" rel="noopener noreferrer">'
            f'&#128279; {esc(domain_of(link, 18))}</a>'
        )
    if len(extra) > 4:
        parts.append(f'<span class="hl-link hl-link-more">+{len(extra) - 4} more</span>')
    for addr in emails[:3]:
        parts.append(
            f'<a class="hl-link" href="mailto:{esc(addr)}">&#9993; {esc(addr)}</a>'
        )

    if not parts:
        return ('<div class="hl-apply hl-apply-empty">'
                '<span class="hl-apply-note">&#9888; No apply link or email found '
                '&mdash; check the post body below.</span></div>')
    return '<div class="hl-apply">' + "".join(parts) + "</div>"


def job_card(data: dict, index: int = 0) -> str:
    """Render one job post card.

    *data* is a plain dict of already-extracted values (see
    ``dashboard.card_data``), which keeps this function free of pandas.
    """
    score = int(data.get("score") or 0)
    fg, bg, bd = score_palette(score)
    style = (
        f"--hl-delay:{stagger_delay(index)}ms;--hl-rail:{fg};"
        f"--hl-score-fg:{fg};--hl-score-bg:{bg};--hl-score-bd:{bd}"
    )

    role = esc(data.get("role"), "Job opportunity")
    author = esc(data.get("author"), "Unknown")
    headline = esc(data.get("headline"))
    author_url = safe_url(data.get("author_url"))
    if author_url:
        author_block = (f'<a href="{esc(author_url)}" target="_blank" '
                        f'rel="noopener noreferrer">{author}</a>')
    else:
        author_block = author
    subtitle = f"{author_block} &middot; {headline}" if headline else author_block

    chips = [chip(data.get("location") or "Location not stated", "&#128205;")]
    chips.append(chip(data.get("experience") or "Any experience", "&#127919;"))
    when = data.get("when") or ""
    if when:
        chips.append(chip(when, "&#128336;", title=str(data.get("when_exact") or "")))
    platform = data.get("platform")
    if platform:
        chips.append(chip(platform, "&#128225;", variant="hl-chip-violet"))
    status = str(data.get("status") or "new")
    if status != "new":
        label, variant = STATUS_META.get(status, (status, ""))
        chips.append(chip(label, "", variant=variant))
    # Which engine produced the score, so a surprising number is traceable.
    if str(data.get("scored_by") or "rules").startswith("gemini"):
        rule = data.get("rule_score")
        hint = f"Gemini scored this {score}; the rule engine said {rule}" if rule is not None else ""
        chips.append(chip("Gemini", "&#10024;", variant="hl-chip-mint", title=hint))

    skills = data.get("skills") or []
    skills_html = ""
    if skills:
        tags = "".join(chip(s, variant="hl-chip-accent") for s in skills[:10])
        if len(skills) > 10:
            tags += chip(f"+{len(skills) - 10}")
        skills_html = f'<div class="hl-skills">{tags}</div>'

    body = clean_excerpt(str(data.get("content") or ""),
                         str(data.get("author") or ""),
                         str(data.get("headline") or ""))
    excerpt_html = ""
    if body:
        clipped = body[:_EXCERPT_LIMIT]
        short_cls = " is-short" if len(body) <= 320 else ""
        excerpt_html = f'<div class="hl-excerpt{short_cls}">{esc(clipped)}</div>'

    return f"""<div class="hl-card" style="{style}">
  <div class="hl-card-head">
    <div style="flex:1 1 auto;min-width:0;">
      <div class="hl-card-title">{role}</div>
      <div class="hl-card-sub">{subtitle}</div>
    </div>
    <div class="hl-score" title="Relevance score">{score}<small>SCORE</small></div>
  </div>
  <div class="hl-meta">{"".join(chips)}</div>
  {skills_html}
  {_apply_bar(safe_url(data.get("primary_url")),
              [u for u in (safe_url(x) for x in (data.get("extra_urls") or [])) if u],
              data.get("emails") or [])}
  {excerpt_html}
</div>"""


def group_heading(author: str, count: int) -> str:
    return (f'<div class="hl-group">&#127970; {esc(author, "Unknown")} '
            f'&middot; {count} posts</div>')


_URL_RE = re.compile(r"^https?://([a-z0-9-]+\.)*linkedin\.com(/|$)", re.I)


def is_linkedin_search_url(url: str) -> bool:
    """Whether *url* looks like a LinkedIn URL the scraper can actually open."""
    return bool(_URL_RE.match((url or "").strip()))
