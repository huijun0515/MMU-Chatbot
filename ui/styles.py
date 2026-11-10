"""
The app's CSS, in one place.

Colours are CSS variables set from the active Streamlit theme (light/dark),
so no page hardcodes a colour. Most styling comes from .streamlit/config.toml
(theme + sidebar theme); the CSS here only covers what Streamlit's theme
cannot express: cards, badges, the events hero, and phone-width layout.
"""

import streamlit as st

LIGHT = {
    "--mmu-blue": "#0033A0", "--mmu-blue-dark": "#002B7F", "--mmu-red": "#E31837",
    "--surface": "#FFFFFF", "--surface-2": "#F3F6FC", "--border": "#E5E7EB",
    "--text": "#1F2937", "--text-2": "#4B5563", "--text-3": "#6B7280",
    "--chip-bg": "#EEF3FF", "--chip-fg": "#0033A0",
    "--ok-bg": "#DCFCE7", "--ok-fg": "#166534", "--warn-bg": "#FEF9C3", "--warn-fg": "#854D0E",
    "--bad-bg": "#FEE2E2", "--bad-fg": "#991B1B", "--info-bg": "#DBEAFE", "--info-fg": "#1E40AF",
    "--shadow": "0 1px 4px rgba(0,0,0,.12)",
}
DARK = {
    **LIGHT,
    "--mmu-blue": "#5B8DEF", "--mmu-blue-dark": "#0B1F4D", "--mmu-red": "#FF4D63",
    "--surface": "#141A26", "--surface-2": "#1A2235", "--border": "#2A3447",
    "--text": "#E5E7EB", "--text-2": "#C3C9D4", "--text-3": "#9AA3B2",
    "--chip-bg": "#1E2A47", "--chip-fg": "#9DBBFF",
    "--ok-bg": "#113B25", "--ok-fg": "#86EFAC", "--warn-bg": "#3F3313", "--warn-fg": "#FDE68A",
    "--bad-bg": "#451A1A", "--bad-fg": "#FCA5A5", "--info-bg": "#1E2A47", "--info-fg": "#9DBBFF",
    "--shadow": "0 1px 4px rgba(0,0,0,.5)",
}

# Decorative poster backgrounds (white text on top) — used when an event has no poster image.
CATEGORY_COLOURS = {
    "Academic Talk": "#0B2A6F", "Career": "#0A2F7A", "Sports": "#B5122B",
    "Clubs & Societies": "#1F3A8A", "Faculty": "#2D3142", "Other": "#3B4A6B",
}

BASE_CSS = """
<style>
/* ── page chrome ─────────────────────────────────────────────── */
.block-container { padding-top: 1.6rem; padding-bottom: 2.5rem; }
.pg-eyebrow { font-size:.72rem; font-weight:700; letter-spacing:.08em; color:var(--mmu-blue); text-transform:uppercase; }
.pg-title { font-size:2rem; font-weight:800; color:var(--text); margin:0; line-height:1.15; }
.pg-sub { color:var(--text-2); margin:4px 0 14px; }
.pg-footer { color:var(--text-3); font-size:.78rem; margin-top:40px; padding-top:12px; border-top:1px solid var(--border); }

/* the logo has dark-blue parts: sit it on a white pill so it reads on the blue sidebar */
img[data-testid="stLogo"] { background:#fff; padding:5px 10px; border-radius:10px; }

/* ── shared atoms ────────────────────────────────────────────── */
.chip { display:inline-block; background:var(--chip-bg); color:var(--chip-fg); font-size:.72rem; font-weight:700;
        padding:3px 10px; border-radius:999px; margin:0 6px 6px 0; }
.badge { display:inline-block; font-size:.7rem; font-weight:700; padding:2px 9px; border-radius:999px; margin:0 6px 6px 0; }
.badge-ok { background:var(--ok-bg); color:var(--ok-fg); }
.badge-warn { background:var(--warn-bg); color:var(--warn-fg); }
.badge-bad { background:var(--bad-bg); color:var(--bad-fg); }
.badge-info { background:var(--info-bg); color:var(--info-fg); }
.badge-muted { background:var(--surface-2); color:var(--text-3); }
.dlg-title { font-size:1.55rem; font-weight:800; color:var(--text); margin:6px 0; }
.dlg-text { color:var(--text-2); }
.dlg-muted { color:var(--text-3); margin-top:8px; }
.dlg-sep { margin:8px 0; border:none; border-top:1px solid var(--border); }
.muted { color:var(--text-3); font-size:.85rem; }
.empty { text-align:center; padding:48px 20px; color:var(--text-3); border:2px dashed var(--border);
         border-radius:16px; background:var(--surface-2); }
.card { background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:14px 16px; }
.snippet { background:var(--surface-2); border-left:4px solid var(--mmu-blue); padding:12px 16px; border-radius:8px;
           color:var(--text-2); font-size:.9rem; line-height:1.55; }
mark { background:#FDE68A; color:#111827; padding:0 2px; border-radius:3px; }

/* ── chat ────────────────────────────────────────────────────── */
.welcome { background:linear-gradient(135deg, var(--mmu-blue-dark) 0%, var(--mmu-blue) 100%); color:#fff;
           border-radius:18px; padding:26px 28px; margin-bottom:14px; }
.welcome h2 { color:#fff !important; margin:0 0 6px; font-size:1.5rem; }
.welcome p { color:rgba(255,255,255,.85); margin:0; }
.cite { display:inline-block; background:var(--chip-bg); color:var(--chip-fg); border-radius:8px;
        padding:3px 9px; font-size:.78rem; margin:2px 6px 2px 0; }
.privacy-note { color:var(--text-3); font-size:.74rem; text-align:center; margin-top:4px; }

/* ── places ──────────────────────────────────────────────────── */
.loc-row { display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); }
.loc-code { font-family:ui-monospace, monospace; font-size:.8rem; color:var(--text-3); min-width:92px; }
.loc-name { font-weight:600; color:var(--text); }
.loc-sub { font-size:.8rem; color:var(--text-3); }

/* ── events ──────────────────────────────────────────────────── */
.st-key-ev_hero { background:var(--mmu-blue); border-radius:20px; padding:0 !important; overflow:hidden; }
.st-key-ev_hero [data-testid="stHorizontalBlock"] { gap:0 !important; align-items:stretch; }
.st-key-ev_hero [data-testid="stColumn"]:first-child { position:relative; min-height:340px; }
.st-key-ev_hero [data-testid="stColumn"]:first-child [data-testid="stElementContainer"],
.st-key-ev_hero [data-testid="stColumn"]:first-child [data-testid="stVerticalBlock"],
.st-key-ev_hero [data-testid="stColumn"]:first-child [data-testid="stMarkdown"] { position:static !important; }
.ev-hero-poster { position:absolute !important; inset:0; background-size:cover; background-position:center;
                  display:flex; align-items:flex-end; padding:28px; box-sizing:border-box; }
.ev-hero-poster span { color:#fff; font-size:2.3rem; font-weight:800; line-height:1.05; text-transform:uppercase; }
.ev-hero-text { padding:26px 0 6px; color:#fff; }
.ev-hero-text h2 { color:#fff; font-size:1.7rem; line-height:1.2; margin:12px 0 14px; padding:0; }
.ev-hero-row { margin:5px 0; font-size:.95rem; color:#fff; }
.ev-hero-desc { color:rgba(255,255,255,.85); font-size:.88rem; margin:12px 0 4px; }
.ev-badge-red { display:inline-block; background:var(--mmu-red); color:#fff; font-size:.72rem; font-weight:700;
                padding:3px 11px; border-radius:999px; margin-right:6px; }
.ev-badge-blue { display:inline-block; background:rgba(255,255,255,.18); color:#fff; font-size:.72rem;
                 font-weight:700; padding:3px 11px; border-radius:999px; }
.st-key-ev_hero [data-testid="stColumn"]:last-child { padding:0 28px 24px; }
.st-key-ev_hero [data-testid="stColumn"]:last-child [data-testid="stColumn"] { padding:0 !important; min-height:0; }
.st-key-ev_hero button, .st-key-ev_hero [data-testid="stDownloadButton"] button {
    background:transparent !important; color:#fff !important; border:1px solid rgba(255,255,255,.55) !important; }
.st-key-ev_hero a[data-testid="stBaseLinkButton-primary"] { background:var(--mmu-red) !important; color:#fff !important; border:none !important; }
.st-key-ev_hero .stButton button[kind="tertiary"] { border:none !important; text-decoration:underline; padding:0; }
[class*="st-key-evc-"] { background:var(--surface); border:1px solid var(--border); border-radius:16px; overflow:hidden; gap:0 !important; padding:0 !important; }
[class*="st-key-evc-"] [data-testid="stElementContainer"] { margin:0; }
[class*="st-key-evc-"] [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; align-items:center; padding:0 16px 10px; gap:.5rem; }
[class*="st-key-evc-"] [data-testid="stColumn"] { min-width:0 !important; }
[class*="st-key-evc-"] button { color:var(--mmu-blue) !important; font-weight:700 !important; padding:0 !important; justify-content:flex-end; }
.ev-poster { position:relative; aspect-ratio:16/9; background-size:cover; background-position:center;
             display:flex; align-items:flex-end; padding:14px; box-sizing:border-box; }
.ev-poster b { color:#fff; font-size:1.25rem; font-weight:800; text-transform:uppercase; line-height:1.1;
               display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.ev-date { position:absolute; top:10px; left:10px; background:#fff; border-radius:10px; text-align:center;
           padding:4px 10px; line-height:1.05; box-shadow:var(--shadow); }
.ev-date b { display:block; font-size:1.25rem; color:#111827; }
.ev-date span { font-size:.62rem; font-weight:800; color:#E31837; letter-spacing:.06em; }
.ev-body { padding:12px 16px 8px; }
.ev-title { font-weight:700; font-size:1rem; color:var(--text); margin:8px 0 6px; line-height:1.3; min-height:2.6em;
            display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.ev-meta { font-size:.82rem; color:var(--text-2); margin:2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ev-org { font-size:.78rem; color:var(--text-3); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ev-orgline { border-top:1px solid var(--border); margin:0 16px 8px; }
.ev-past { opacity:.55; filter:grayscale(.6); }
.ev-dlg-poster { width:100%; aspect-ratio:16/9; max-height:320px; background-size:cover; background-position:center;
                 border-radius:14px; display:flex; align-items:flex-end; padding:20px; box-sizing:border-box; }
.ev-dlg-poster b { color:#fff; font-size:1.8rem; font-weight:800; text-transform:uppercase; line-height:1.05; }
.ev-dlg-box { border:1px solid var(--border); border-radius:12px; padding:10px 14px; margin:10px 0; }
[role="dialog"] [data-testid="stBaseButton-tertiary"] { color:var(--mmu-blue); font-weight:700; text-decoration:underline; padding:0; }

/* ── calculator ──────────────────────────────────────────────── */
.res-panel { border-radius:16px; overflow:hidden; border:1.5px solid var(--border); }
.res-block { padding:16px 18px; text-align:center; border-bottom:1px solid var(--border); background:var(--surface); }
.res-block:nth-child(odd) { background:var(--surface-2); }
.res-block:last-child { border-bottom:none; }
.res-label { font-size:.72rem; text-transform:uppercase; letter-spacing:.1em; color:var(--text-3); font-weight:600; margin-bottom:4px; }
.res-value { font-size:2.4rem; font-weight:800; line-height:1; }
.res-small { font-size:1.5rem !important; color:var(--text); }
.honours { border-radius:10px; padding:12px 16px; text-align:center; font-weight:700; font-size:.92rem; margin-top:10px; }
.deans-badge { background:var(--warn-bg); color:var(--warn-fg); border-radius:10px; padding:10px 14px; text-align:center;
               font-weight:700; font-size:.85rem; margin-top:8px; }
.grade-table { width:100%; border-collapse:collapse; font-size:.9rem; }
.grade-table th { background:var(--mmu-blue); color:#fff; padding:10px 16px; text-align:center; }
.grade-table td { padding:7px 16px; text-align:center; border-bottom:1px solid var(--border); color:var(--text); }

/* ── phones ──────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .block-container { padding-left:1rem; padding-right:1rem; }
  .pg-title { font-size:1.6rem; }
  .st-key-ev_hero [data-testid="stColumn"]:first-child { min-height:210px; }
  div[data-testid="stDialog"], div[data-testid="stDialog"] > div { align-items:flex-end !important; }
  div[data-testid="stDialog"] div[role="dialog"] { width:100% !important; max-width:100% !important; margin:0 !important;
      border-radius:22px 22px 0 0 !important; max-height:92vh; }
  .res-value { font-size:1.9rem; }
}
</style>
"""


def inject_css():
    """Set the colour variables for the active theme and the shared CSS."""
    theme_type = "light"
    try:
        theme_type = st.context.theme.type or "light"
    except Exception:
        pass
    tokens = DARK if theme_type == "dark" else LIGHT
    variables = ";".join(f"{k}:{v}" for k, v in tokens.items())
    st.markdown(f"<style>:root{{{variables}}}</style>" + BASE_CSS, unsafe_allow_html=True)
