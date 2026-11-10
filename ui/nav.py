"""
Page registry so feature modules can link to / switch to each other without
importing app.py (which would be circular).

app.py creates the st.Page objects on every run and calls register(); pages
then use nav.switch("places") or nav.link("sources", "Open", query_params=...).
"""

import streamlit as st

_pages = {}


def register(pages):
    _pages.clear()
    _pages.update(pages)


def page(name):
    return _pages[name]


def switch(name, **state):
    """Jump to another page, optionally handing it some session_state first."""
    for key, value in state.items():
        st.session_state[key] = value
    st.switch_page(_pages[name])


def link(name, label, **kwargs):
    return st.page_link(_pages[name], label=label, **kwargs)


def url(name):
    return "/" + _pages[name].url_path
