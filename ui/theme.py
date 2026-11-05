"""
HireLens design system.

One place for every token, surface and animation in the dashboard.  The CSS is
injected once per run by :func:`inject`; `dashboard.py` only ever writes
semantic class names (``hl-card``, ``hl-chip``...), never raw colours.

Motion rules (curves live in :mod:`ui.motion`):
  * nothing uses a plain ``ease`` - entrances settle on a spring,
  * lists stagger via a per-element ``--hl-delay``,
  * every animation is disabled under ``prefers-reduced-motion``.
"""

from __future__ import annotations

import streamlit as st

from ui.motion import (
    EASE_IN_OUT,
    EASE_OUT_QUINT,
    SPRING_SNAPPY,
    SPRING_SOFT,
)

# --- Palette ---------------------------------------------------------------

INK = "#07070f"
ACCENT = "#6d8cff"
VIOLET = "#a06bff"
CYAN = "#3ddbd9"
MINT = "#38d39f"
AMBER = "#ffb648"
ROSE = "#ff6b81"


def score_palette(score: int) -> tuple[str, str, str]:
    """(text colour, background, border) for a 0-100 relevance score."""
    if score >= 80:
        return MINT, "rgba(56,211,159,.12)", "rgba(56,211,159,.34)"
    if score >= 60:
        return CYAN, "rgba(61,219,217,.12)", "rgba(61,219,217,.32)"
    if score >= 40:
        return AMBER, "rgba(255,182,72,.12)", "rgba(255,182,72,.32)"
    return ROSE, "rgba(255,107,129,.12)", "rgba(255,107,129,.30)"


_CSS_TEMPLATE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap');

:root {
  /* surfaces */
  --hl-ink: __INK__;
  --hl-raised: rgba(255,255,255,.035);
  --hl-raised-2: rgba(255,255,255,.06);
  --hl-line: rgba(255,255,255,.08);
  --hl-line-strong: rgba(255,255,255,.15);

  /* type */
  --hl-text: #eef1f8;
  --hl-text-2: #9aa3bd;
  --hl-text-3: #697293;

  /* accents */
  --hl-accent: __ACCENT__;
  --hl-violet: __VIOLET__;
  --hl-cyan: __CYAN__;
  --hl-mint: __MINT__;
  --hl-amber: __AMBER__;
  --hl-rose: __ROSE__;

  /* motion */
  --hl-spring: __SPRING_SOFT__;
  --hl-spring-snap: __SPRING_SNAPPY__;
  --hl-out: __EASE_OUT_QUINT__;
  --hl-inout: __EASE_IN_OUT__;
  --hl-delay: 0ms;

  /* elevation */
  --hl-shadow-1: 0 1px 2px rgba(0,0,0,.4);
  --hl-shadow-2: 0 10px 30px -12px rgba(0,0,0,.65);
  --hl-shadow-3: 0 24px 60px -20px rgba(0,0,0,.75);
}

/* ===================================================================== */
/*  Keyframes                                                            */
/* ===================================================================== */

@keyframes hl-rise {
  from { opacity: 0; transform: translate3d(0, 14px, 0) scale(.985); }
  to   { opacity: 1; transform: none; }
}
@keyframes hl-fade {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes hl-pop {
  from { opacity: 0; transform: scale(.88); }
  to   { opacity: 1; transform: scale(1); }
}
@keyframes hl-slide-in {
  from { opacity: 0; transform: translate3d(-10px, 0, 0); }
  to   { opacity: 1; transform: none; }
}
/* slow aurora drift behind the whole app */
@keyframes hl-drift {
  0%   { transform: translate3d(0,0,0) scale(1); }
  33%  { transform: translate3d(3%, -2%, 0) scale(1.06); }
  66%  { transform: translate3d(-2%, 2%, 0) scale(1.03); }
  100% { transform: translate3d(0,0,0) scale(1); }
}
/* gradient sweep used on rules and the top decoration */
@keyframes hl-pan {
  0%   { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
@keyframes hl-shimmer {
  0%   { transform: translateX(-120%); }
  100% { transform: translateX(300%); }
}
@keyframes hl-pulse-ring {
  0%   { box-shadow: 0 0 0 0 rgba(56,211,159,.5); }
  70%  { box-shadow: 0 0 0 9px rgba(56,211,159,0); }
  100% { box-shadow: 0 0 0 0 rgba(56,211,159,0); }
}
@keyframes hl-grow { from { width: 0; } }

/* ===================================================================== */
/*  App shell                                                            */
/* ===================================================================== */

html, body, .stApp { font-family: 'Inter', system-ui, sans-serif; }

.stApp { background: var(--hl-ink); color: var(--hl-text); }

/* Aurora field - a fixed, slowly drifting layer behind everything. */
.stApp::before {
  content: '';
  position: fixed;
  inset: -20%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(42rem 26rem at 8% -6%,   rgba(109,140,255,.20), transparent 62%),
    radial-gradient(38rem 24rem at 94% 2%,   rgba(160,107,255,.17), transparent 60%),
    radial-gradient(34rem 28rem at 52% 104%, rgba(61,219,217,.12), transparent 62%);
  animation: hl-drift 38s var(--hl-inout) infinite;
  will-change: transform;
}
/* fine grain so the large flat areas do not band */
.stApp::after {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: .45;
  background-image: radial-gradient(rgba(255,255,255,.04) 1px, transparent 1px);
  background-size: 3px 3px;
}
.stApp > * { position: relative; z-index: 1; }

.block-container {
  max-width: 1360px;
  padding-top: 1.5rem !important;
  padding-bottom: 5rem !important;
}

/* Streamlit chrome */
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; height: 0; }
[data-testid="stDecoration"] {
  background-image: linear-gradient(90deg, var(--hl-accent), var(--hl-violet), var(--hl-cyan), var(--hl-accent));
  background-size: 200% 100%;
  animation: hl-pan 7s linear infinite;
  height: 2px;
}

::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,.11);
  border-radius: 99px;
  border: 2px solid transparent;
  background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,.24); background-clip: content-box; }

/* ===================================================================== */
/*  Shared primitives                                                    */
/* ===================================================================== */

.hl-rise {
  animation: hl-rise .55s var(--hl-spring) both;
  animation-delay: var(--hl-delay, 0ms);
}
.hl-fade { animation: hl-fade .5s var(--hl-out) both; animation-delay: var(--hl-delay, 0ms); }

.hl-chip {
  display: inline-flex;
  align-items: center;
  gap: .34rem;
  padding: .24rem .62rem;
  border-radius: 8px;
  font-size: .745rem;
  font-weight: 600;
  line-height: 1.5;
  color: var(--hl-text-2);
  background: var(--hl-raised);
  border: 1px solid var(--hl-line);
  transition: transform .35s var(--hl-spring-snap), background .25s var(--hl-out), color .25s var(--hl-out);
}
.hl-chip:hover { transform: translateY(-1px); background: var(--hl-raised-2); color: var(--hl-text); }
.hl-chip-accent { color: var(--hl-accent); background: rgba(109,140,255,.1); border-color: rgba(109,140,255,.26); }
.hl-chip-violet { color: var(--hl-violet); background: rgba(160,107,255,.1); border-color: rgba(160,107,255,.26); }
.hl-chip-amber  { color: var(--hl-amber);  background: rgba(255,182,72,.1);  border-color: rgba(255,182,72,.26); }
.hl-chip-mint   { color: var(--hl-mint);   background: rgba(56,211,159,.1);  border-color: rgba(56,211,159,.26); }

/* ===================================================================== */
/*  Masthead                                                             */
/* ===================================================================== */

.hl-masthead {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.4rem;
  flex-wrap: wrap;
  padding: 1.45rem 1.75rem;
  margin-bottom: 1.25rem;
  border-radius: 22px;
  border: 1px solid var(--hl-line);
  background:
    linear-gradient(135deg, rgba(109,140,255,.10), rgba(160,107,255,.07) 46%, rgba(61,219,217,.06)),
    rgba(13,13,27,.72);
  backdrop-filter: blur(18px);
  box-shadow: var(--hl-shadow-2);
  overflow: hidden;
  animation: hl-rise .7s var(--hl-spring) both;
}
.hl-masthead::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--hl-accent), var(--hl-violet), var(--hl-cyan), transparent);
  background-size: 200% 100%;
  animation: hl-pan 6s linear infinite;
}
.hl-brand { display: flex; align-items: center; gap: .95rem; }
.hl-logo {
  display: grid;
  place-items: center;
  width: 46px; height: 46px;
  flex: 0 0 46px;
  border-radius: 14px;
  font-size: 1.3rem;
  background: linear-gradient(140deg, rgba(109,140,255,.3), rgba(160,107,255,.22));
  border: 1px solid rgba(109,140,255,.35);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 8px 22px -10px rgba(109,140,255,.9);
  animation: hl-pop .6s var(--hl-spring-snap) both .1s;
}
.hl-wordmark {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 800;
  letter-spacing: -.035em;
  line-height: 1.12;
  background: linear-gradient(100deg, #ffffff 10%, #b9c6ff 48%, #9ad7e8 90%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hl-tagline { margin: .2rem 0 0; font-size: .84rem; color: var(--hl-text-2); font-weight: 450; }
.hl-masthead-side { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }

/* live status pill */
.hl-status {
  display: inline-flex;
  align-items: center;
  gap: .45rem;
  padding: .36rem .8rem;
  border-radius: 999px;
  font-size: .74rem;
  font-weight: 700;
  letter-spacing: .02em;
  border: 1px solid var(--hl-line);
  background: var(--hl-raised);
  color: var(--hl-text-2);
}
.hl-status .hl-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.hl-status-live { color: var(--hl-mint); background: rgba(56,211,159,.1); border-color: rgba(56,211,159,.3); }
.hl-status-live .hl-dot { animation: hl-pulse-ring 1.9s var(--hl-inout) infinite; }

/* ===================================================================== */
/*  Stat tiles                                                           */
/* ===================================================================== */

.hl-stat {
  position: relative;
  height: 100%;
  padding: 1rem 1.1rem;
  border-radius: 18px;
  border: 1px solid var(--hl-line);
  background: linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.012));
  backdrop-filter: blur(14px);
  overflow: hidden;
  animation: hl-rise .55s var(--hl-spring) both;
  animation-delay: var(--hl-delay, 0ms);
  transition: transform .45s var(--hl-spring-snap), border-color .3s var(--hl-out), box-shadow .4s var(--hl-out);
}
.hl-stat::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  opacity: 0;
  background: radial-gradient(18rem 9rem at 50% -40%, var(--hl-tint, rgba(109,140,255,.35)), transparent 70%);
  transition: opacity .45s var(--hl-out);
  pointer-events: none;
}
.hl-stat:hover { transform: translateY(-4px); border-color: var(--hl-line-strong); box-shadow: var(--hl-shadow-3); }
.hl-stat:hover::after { opacity: 1; }
.hl-stat-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: .5rem; }
.hl-stat-icon {
  display: grid; place-items: center;
  width: 30px; height: 30px;
  border-radius: 9px;
  font-size: .88rem;
  background: var(--hl-raised-2);
  border: 1px solid var(--hl-line);
}
.hl-stat-delta { font-size: .7rem; font-weight: 700; color: var(--hl-text-3); font-variant-numeric: tabular-nums; }
.hl-stat-value {
  font-size: 2rem;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -.045em;
  font-variant-numeric: tabular-nums;
  color: var(--hl-text);
}
.hl-stat-label {
  margin-top: .32rem;
  font-size: .715rem;
  font-weight: 600;
  letter-spacing: .085em;
  text-transform: uppercase;
  color: var(--hl-text-3);
}
.hl-stat-spark { margin-top: .6rem; height: 3px; border-radius: 99px; background: var(--hl-raised-2); overflow: hidden; }
.hl-stat-spark i {
  display: block; height: 100%; border-radius: inherit;
  background: linear-gradient(90deg, var(--hl-accent), var(--hl-violet));
  width: var(--hl-fill, 40%);
  animation: hl-grow .9s var(--hl-out) both;
  animation-delay: calc(var(--hl-delay, 0ms) + 140ms);
}

/* ===================================================================== */
/*  Job card                                                             */
/* ===================================================================== */

.hl-card {
  position: relative;
  padding: 1.1rem 1.25rem 1.15rem;
  border-radius: 20px;
  border: 1px solid var(--hl-line);
  background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.015));
  backdrop-filter: blur(14px);
  box-shadow: var(--hl-shadow-1);
  overflow: hidden;
  animation: hl-rise .6s var(--hl-spring) both;
  animation-delay: var(--hl-delay, 0ms);
  transition: transform .45s var(--hl-spring-snap), border-color .3s var(--hl-out), box-shadow .45s var(--hl-out);
}
.hl-card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, var(--hl-rail, var(--hl-accent)), transparent 88%);
}
.hl-card:hover { transform: translateY(-3px); border-color: var(--hl-line-strong); box-shadow: var(--hl-shadow-3); }
.hl-card-head { display: flex; align-items: flex-start; gap: .8rem; }
.hl-card-title {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -.02em;
  line-height: 1.35;
  color: var(--hl-text);
}
.hl-card-sub {
  margin: .24rem 0 0;
  font-size: .81rem;
  color: var(--hl-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hl-card-sub a { color: var(--hl-text-2); text-decoration: none; border-bottom: 1px dotted rgba(255,255,255,.2); }
.hl-card-sub a:hover { color: var(--hl-accent); border-bottom-color: var(--hl-accent); }

/* score dial */
.hl-score {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 46px; height: 46px;
  border-radius: 14px;
  font-size: 1rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.03em;
  color: var(--hl-score-fg, var(--hl-accent));
  background: var(--hl-score-bg, rgba(109,140,255,.12));
  border: 1px solid var(--hl-score-bd, rgba(109,140,255,.3));
  animation: hl-pop .5s var(--hl-spring-snap) both;
  animation-delay: calc(var(--hl-delay, 0ms) + 90ms);
}
.hl-score small { display: block; font-size: .5rem; font-weight: 700; letter-spacing: .1em; opacity: .7; margin-top: 1px; }

.hl-meta { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .8rem; }
.hl-skills { display: flex; flex-wrap: wrap; gap: .34rem; margin-top: .55rem; }

/* apply bar */
.hl-apply {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: .45rem;
  margin-top: .85rem;
  padding: .6rem .7rem;
  border-radius: 14px;
  background: rgba(56,211,159,.06);
  border: 1px solid rgba(56,211,159,.2);
}
.hl-apply-empty { background: rgba(255,182,72,.05); border-color: rgba(255,182,72,.2); }
.hl-apply-note { font-size: .76rem; color: var(--hl-amber); font-weight: 600; }
.hl-cta {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  padding: .42rem .85rem;
  border-radius: 10px;
  font-size: .81rem;
  font-weight: 700;
  text-decoration: none !important;
  color: #04120c !important;
  background: linear-gradient(135deg, var(--hl-mint), #5fe3b6);
  box-shadow: 0 8px 20px -10px rgba(56,211,159,.9);
  transition: transform .4s var(--hl-spring-snap), box-shadow .3s var(--hl-out), filter .3s var(--hl-out);
}
.hl-cta:hover { transform: translateY(-2px) scale(1.02); filter: brightness(1.06); box-shadow: 0 14px 28px -12px rgba(56,211,159,.95); }
.hl-cta:active { transform: translateY(0) scale(.98); }
.hl-cta span { font-weight: 500; opacity: .75; font-size: .74rem; }
.hl-link {
  display: inline-flex;
  align-items: center;
  gap: .3rem;
  padding: .3rem .6rem;
  border-radius: 9px;
  font-size: .745rem;
  font-weight: 600;
  text-decoration: none !important;
  color: var(--hl-text-2) !important;
  background: var(--hl-raised);
  border: 1px solid var(--hl-line);
  transition: transform .4s var(--hl-spring-snap), color .25s var(--hl-out), border-color .25s var(--hl-out);
}
.hl-link:hover { transform: translateY(-1px); color: var(--hl-text) !important; border-color: var(--hl-line-strong); }
.hl-link-more { color: var(--hl-text-3) !important; border-style: dashed; }

/* post body - clamped with a fade, full text lives in the expander */
.hl-excerpt {
  position: relative;
  margin-top: .8rem;
  padding: .72rem .85rem;
  max-height: 7.2rem;
  overflow: hidden;
  border-radius: 12px;
  font-size: .815rem;
  line-height: 1.62;
  color: var(--hl-text-2);
  background: rgba(0,0,0,.26);
  border: 1px solid rgba(255,255,255,.05);
  white-space: pre-wrap;
  word-break: break-word;
}
.hl-excerpt::after {
  content: '';
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 2.4rem;
  background: linear-gradient(transparent, #0a0a16);
  pointer-events: none;
}
.hl-excerpt.is-short { max-height: none; }
.hl-excerpt.is-short::after { display: none; }

/* group header when posts are grouped by recruiter */
.hl-group {
  display: flex;
  align-items: center;
  gap: .55rem;
  margin: 1.1rem 0 .5rem;
  font-size: .78rem;
  font-weight: 700;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: var(--hl-text-3);
  animation: hl-slide-in .5s var(--hl-out) both;
}
.hl-group::after { content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, var(--hl-line), transparent); }

/* ===================================================================== */
/*  Run-history row                                                      */
/* ===================================================================== */

.hl-run {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: .45rem .85rem;
  padding: .68rem .95rem;
  margin-bottom: .45rem;
  border-radius: 13px;
  border: 1px solid var(--hl-line);
  background: var(--hl-raised);
  font-size: .79rem;
  color: var(--hl-text-2);
  animation: hl-rise .5s var(--hl-spring) both;
  animation-delay: var(--hl-delay, 0ms);
  transition: transform .4s var(--hl-spring-snap), border-color .3s var(--hl-out), background .3s var(--hl-out);
}
.hl-run:hover { transform: translateX(3px); border-color: var(--hl-line-strong); background: var(--hl-raised-2); }
.hl-run b { color: var(--hl-text); font-variant-numeric: tabular-nums; }
.hl-run-time { font-family: 'JetBrains Mono', monospace; font-size: .735rem; color: var(--hl-text-3); }
.hl-run-sep { flex: 1; }

/* ===================================================================== */
/*  Empty state                                                          */
/* ===================================================================== */

.hl-empty {
  text-align: center;
  padding: 3rem 1.5rem;
  border-radius: 22px;
  border: 1px dashed var(--hl-line-strong);
  background: var(--hl-raised);
  animation: hl-rise .6s var(--hl-spring) both;
}
.hl-empty-icon {
  display: inline-grid;
  place-items: center;
  width: 62px; height: 62px;
  margin-bottom: 1rem;
  border-radius: 20px;
  font-size: 1.75rem;
  background: linear-gradient(140deg, rgba(109,140,255,.2), rgba(160,107,255,.14));
  border: 1px solid rgba(109,140,255,.28);
  animation: hl-pop .6s var(--hl-spring-snap) both .15s;
}
.hl-empty h3 { margin: 0 0 .4rem; font-size: 1.08rem; font-weight: 700; color: var(--hl-text); }
.hl-empty p { margin: 0 auto; max-width: 30rem; font-size: .85rem; line-height: 1.7; color: var(--hl-text-2); }
.hl-steps { display: inline-flex; flex-direction: column; gap: .55rem; margin-top: 1.1rem; text-align: left; }
.hl-step { display: flex; align-items: center; gap: .6rem; font-size: .83rem; color: var(--hl-text-2); }
.hl-step b {
  display: grid; place-items: center;
  width: 22px; height: 22px; flex: 0 0 22px;
  border-radius: 7px;
  font-size: .72rem;
  color: var(--hl-accent);
  background: rgba(109,140,255,.14);
  border: 1px solid rgba(109,140,255,.3);
}

/* ===================================================================== */
/*  Section heading + progress                                           */
/* ===================================================================== */

.hl-section {
  display: flex;
  align-items: baseline;
  gap: .6rem;
  margin: .2rem 0 .7rem;
  animation: hl-slide-in .5s var(--hl-out) both;
}
.hl-section h3 { margin: 0; font-size: .98rem; font-weight: 700; letter-spacing: -.015em; color: var(--hl-text); }
.hl-section span { font-size: .77rem; color: var(--hl-text-3); }

.hl-progress {
  position: relative;
  height: 3px;
  margin-top: .7rem;
  border-radius: 99px;
  background: var(--hl-raised-2);
  overflow: hidden;
}
.hl-progress::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 34%;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, var(--hl-accent), var(--hl-violet), transparent);
  animation: hl-shimmer 1.35s var(--hl-inout) infinite;
}

/* ===================================================================== */
/*  Streamlit widget overrides                                           */
/* ===================================================================== */

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, rgba(12,12,24,.97), rgba(8,8,16,.97));
  border-right: 1px solid var(--hl-line);
  backdrop-filter: blur(16px);
}
[data-testid="stSidebar"] hr { margin: .8rem 0; border-color: var(--hl-line); }
.hl-side-title {
  display: flex; align-items: center; gap: .45rem;
  margin: .2rem 0 .45rem;
  font-size: .72rem; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase;
  color: var(--hl-text-3);
}

.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 11px !important;
  font-weight: 600 !important;
  border: 1px solid var(--hl-line) !important;
  background: var(--hl-raised) !important;
  color: var(--hl-text) !important;
  transition: transform .4s var(--hl-spring-snap), background .25s var(--hl-out),
              border-color .25s var(--hl-out), box-shadow .3s var(--hl-out) !important;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
  transform: translateY(-2px);
  background: var(--hl-raised-2) !important;
  border-color: var(--hl-line-strong) !important;
  box-shadow: var(--hl-shadow-2) !important;
}
.stButton > button:active { transform: translateY(0) scale(.985); }
.stButton > button:disabled { opacity: .4; transform: none !important; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: linear-gradient(135deg, var(--hl-accent), var(--hl-violet)) !important;
  border-color: transparent !important;
  color: #fff !important;
  box-shadow: 0 10px 26px -12px rgba(109,140,255,.95) !important;
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.08); box-shadow: 0 16px 34px -12px rgba(109,140,255,1) !important; }

.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-baseweb="select"] > div {
  background: var(--hl-raised) !important;
  border: 1px solid var(--hl-line) !important;
  border-radius: 11px !important;
  color: var(--hl-text) !important;
  transition: border-color .25s var(--hl-out), box-shadow .3s var(--hl-out), background .25s var(--hl-out) !important;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
  border-color: rgba(109,140,255,.6) !important;
  box-shadow: 0 0 0 3px rgba(109,140,255,.16) !important;
  background: var(--hl-raised-2) !important;
}
.stTextInput input::placeholder { color: var(--hl-text-3); }
[data-testid="stWidgetLabel"] p { font-size: .81rem !important; font-weight: 600 !important; color: var(--hl-text-2) !important; }

.stTabs [data-baseweb="tab-list"] {
  gap: .3rem;
  padding: .3rem;
  border-radius: 14px;
  background: var(--hl-raised);
  border: 1px solid var(--hl-line);
}
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab-border"] { display: none !important; }
.stTabs button[role="tab"] {
  height: auto !important;
  padding: .5rem .95rem !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
  color: var(--hl-text-2) !important;
  transition: color .25s var(--hl-out), background .3s var(--hl-out) !important;
}
.stTabs button[role="tab"] p { font-size: .84rem !important; }
.stTabs button[role="tab"]:hover { color: var(--hl-text) !important; background: var(--hl-raised-2); }
.stTabs button[role="tab"][aria-selected="true"] {
  color: #fff !important;
  background: linear-gradient(135deg, rgba(109,140,255,.9), rgba(160,107,255,.85)) !important;
  box-shadow: 0 8px 20px -12px rgba(109,140,255,1);
}
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.1rem; animation: hl-rise .45s var(--hl-out) both; }

[data-testid="stExpander"] {
  border: 1px solid var(--hl-line) !important;
  border-radius: 14px !important;
  background: var(--hl-raised) !important;
  overflow: hidden;
  transition: border-color .3s var(--hl-out);
}
[data-testid="stExpander"]:hover { border-color: var(--hl-line-strong) !important; }
[data-testid="stExpander"] summary { font-size: .81rem; font-weight: 600; color: var(--hl-text-2); }
[data-testid="stExpander"] summary:hover { color: var(--hl-text); }

[data-testid="stMetric"] {
  padding: .85rem 1rem;
  border-radius: 15px;
  border: 1px solid var(--hl-line);
  background: var(--hl-raised);
  transition: transform .45s var(--hl-spring-snap), border-color .3s var(--hl-out);
}
[data-testid="stMetric"]:hover { transform: translateY(-3px); border-color: var(--hl-line-strong); }
[data-testid="stMetricValue"] { font-weight: 800 !important; letter-spacing: -.035em; font-variant-numeric: tabular-nums; }
[data-testid="stMetricLabel"] p { font-size: .73rem !important; letter-spacing: .05em; text-transform: uppercase; }

[data-testid="stSlider"] [role="slider"] { transition: transform .35s var(--hl-spring-snap); }
[data-testid="stSlider"] [role="slider"]:hover { transform: scale(1.18); }

[data-testid="stAlert"] {
  border-radius: 14px;
  border: 1px solid var(--hl-line);
  animation: hl-rise .45s var(--hl-spring) both;
}
[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; border: 1px solid var(--hl-line); }

/* ===================================================================== */
/*  Scroll-linked reveal (progressive enhancement)                       */
/* ===================================================================== */

@supports (animation-timeline: view()) {
  @media (prefers-reduced-motion: no-preference) {
    .hl-card, .hl-run {
      animation: hl-rise linear both;
      animation-timeline: view();
      animation-range: entry 0% entry 40%;
      animation-delay: 0ms;
    }
  }
}

/* ===================================================================== */
/*  Responsive                                                           */
/* ===================================================================== */

@media (max-width: 860px) {
  .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
  .hl-masthead { padding: 1.1rem; border-radius: 18px; }
  .hl-wordmark { font-size: 1.25rem; }
  .hl-stat-value { font-size: 1.65rem; }
  .hl-card { padding: 1rem; border-radius: 16px; }
}

/* ===================================================================== */
/*  Reduced motion - kill every animation, keep every colour             */
/* ===================================================================== */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .001ms !important;
  }
}
</style>
"""

_SUBSTITUTIONS = {
    "__INK__": INK,
    "__ACCENT__": ACCENT,
    "__VIOLET__": VIOLET,
    "__CYAN__": CYAN,
    "__MINT__": MINT,
    "__AMBER__": AMBER,
    "__ROSE__": ROSE,
    "__SPRING_SOFT__": SPRING_SOFT,
    "__SPRING_SNAPPY__": SPRING_SNAPPY,
    "__EASE_OUT_QUINT__": EASE_OUT_QUINT,
    "__EASE_IN_OUT__": EASE_IN_OUT,
}


def css() -> str:
    """The full stylesheet with design tokens substituted in."""
    out = _CSS_TEMPLATE
    for token, value in _SUBSTITUTIONS.items():
        out = out.replace(token, value)
    return out


def inject() -> None:
    """Inject the design system.  Call once, right after `set_page_config`."""
    st.markdown(css(), unsafe_allow_html=True)
