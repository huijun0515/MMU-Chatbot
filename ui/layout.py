"""
Shared page chrome: header, footer, badges, and the error boundary that keeps
raw exceptions off the screen.
"""

import html
from functools import wraps

import streamlit as st

from core.logging_setup import logger
from ui import nav

FOOTER_TEXT = ("Unofficial student project · answers may be incomplete · "
               "verify important matters with the relevant office.")


def page_header(title, subtitle=None, eyebrow=None, icon=None):
    parts = []
    if eyebrow:
        parts.append(f"<div class='pg-eyebrow'>{html.escape(eyebrow)}</div>")
    parts.append(f"<div class='pg-title'>{(icon + ' ') if icon else ''}{html.escape(title)}</div>")
    if subtitle:
        parts.append(f"<div class='pg-sub'>{html.escape(subtitle)}</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def page_footer():
    st.markdown(f"<div class='pg-footer'>{FOOTER_TEXT}</div>", unsafe_allow_html=True)
    nav.link("privacy", "Privacy & data notice", icon=":material/policy:")


def badge(label, kind="info"):
    """kind: ok | warn | bad | info."""
    return f"<span class='badge badge-{kind}'>{html.escape(label)}</span>"


def chip(label):
    return f"<span class='chip'>{html.escape(label)}</span>"


def safe_page(fn):
    """Render a page; on an unexpected error show a friendly message and log the detail."""
    @wraps(fn)
    def wrapper():
        try:
            fn()
        except Exception:  # noqa: BLE001 - this is the page-level error boundary
            logger.exception("Unhandled error while rendering %s", fn.__name__)
            st.error("Something went wrong while loading this page. Please refresh and try again; "
                     "if it keeps happening, let the admin know.")
    return wrapper
