"""
Motion-style animation primitives for the HireLens dashboard.

The visual language is borrowed from Motion (motion.dev): nothing moves on a
plain `ease`.  Entrances overshoot slightly and settle, hovers are springy,
and everything that enters the viewport does so with a short, staggered
fade-up rather than appearing all at once.

Springs are expressed as CSS `linear()` easings — the same technique Motion's
own spring-to-CSS generator uses — so the physics survive in pure CSS with no
JavaScript, which matters here because Streamlit strips <script> tags out of
`st.markdown`.
"""

from __future__ import annotations

# --- Spring curves ---------------------------------------------------------
# stiffness 100 / damping 10 — a gentle overshoot, used for entrances.
SPRING_SOFT = (
    "linear(0, 0.006, 0.025 2.8%, 0.101 6.1%, 0.539 18.9%, 0.721 25.3%,"
    " 0.849 31.5%, 0.937 38.1%, 0.968 41.8%, 0.991 45.7%, 1.006 50.1%,"
    " 1.015 55%, 1.017 63.9%, 1.001)"
)
# stiffness 300 / damping 20 — snappier, used for hovers and taps.
SPRING_SNAPPY = (
    "linear(0, 0.045, 0.176 6.3%, 0.63 17.5%, 0.838 24.1%, 0.925 28.1%,"
    " 0.989 32.4%, 1.028 37%, 1.043 42.4%, 1.04 49.7%, 1.011 60.6%, 0.998 76.7%, 1)"
)
# A hard, no-overshoot decelerate for things that must not bounce (text, tables).
EASE_OUT_QUINT = "cubic-bezier(0.22, 1, 0.36, 1)"
EASE_OUT_EXPO = "cubic-bezier(0.16, 1, 0.3, 1)"
EASE_IN_OUT = "cubic-bezier(0.65, 0, 0.35, 1)"

# Base stagger step between sibling entrances, in milliseconds.
STAGGER_MS = 45
# Cards past this index all share the last delay, so a long list does not
# take four seconds to finish appearing.
STAGGER_CAP = 14


def stagger_delay(index: int, step_ms: int = STAGGER_MS, cap: int = STAGGER_CAP) -> int:
    """Delay in ms for the *index*-th sibling in a staggered group."""
    return min(max(index, 0), cap) * step_ms


def stagger_style(index: int, **extra: str) -> str:
    """Inline `style="..."` payload carrying the stagger delay for one element.

    Returns just the declarations (no `style=`), so callers can drop it into an
    f-string attribute.
    """
    decls = [f"--hl-delay:{stagger_delay(index)}ms"]
    decls.extend(f"{k.replace('_', '-')}:{v}" for k, v in extra.items())
    return ";".join(decls)
