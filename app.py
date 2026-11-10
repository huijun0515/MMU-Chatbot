"""
App entry point: native multipage navigation (st.navigation / st.Page).

  /assistant  /places  /sources  /events  /calculator   visible in the sidebar
  /admin      /privacy                                  hidden from the menu, reachable by URL

The admin console is still password-gated inside admin.py. The old ?admin=1
flag keeps working as a redirect to /admin.

Everything else lives elsewhere on purpose:
  core/    RAG engine, storage, config        ui/      theme CSS, layout helpers, page registry
  views/   assistant + privacy pages           events.py, locations.py, source_explorer.py,
  app_pages.py  the page list                 cgpa_calculator.py, admin.py — feature pages
"""

import streamlit as st

st.set_page_config(page_title="MMU Campus Assistant", page_icon="🎓", layout="wide",
                   initial_sidebar_state="expanded")

from app_pages import build_pages  # noqa: E402
from ui import nav  # noqa: E402
from ui.styles import inject_css  # noqa: E402

st.logo("mmu_logo.png", size="large")
inject_css()

pages = build_pages()
nav.register(pages)
current = st.navigation(list(pages.values()), position="sidebar")

if "admin" in st.query_params:  # backward-compatible entry point
    st.query_params.clear()
    st.switch_page(pages["admin"])

with st.sidebar:
    st.caption("FYP prototype · Goh Hui Jun · Multimedia University")

current.run()
