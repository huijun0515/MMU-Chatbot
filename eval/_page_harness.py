"""Test entry point: identical shell to app.py, but the page named in SMOKE_PAGE
is the default page, so AppTest (which cannot switch between function pages) can
render any page. Not used by the real app."""

import os

import streamlit as st

st.set_page_config(page_title="MMU Campus Assistant", page_icon="🎓", layout="wide")

from app_pages import build_pages  # noqa: E402
from ui import nav  # noqa: E402
from ui.styles import inject_css  # noqa: E402

inject_css()
pages = build_pages(default=os.environ.get("SMOKE_PAGE", "assistant"))
nav.register(pages)
st.navigation(list(pages.values()), position="sidebar").run()
