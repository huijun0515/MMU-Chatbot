"""The page registry shared by app.py and the test harness (eval/smoke_pages.py)."""

import streamlit as st

from ui.layout import safe_page
from views.assistant_view import render_assistant_page
from views.privacy_view import render_privacy_page
from locations import render_directory_page
from source_explorer import render_source_explorer_page
from events import render_events_page
from cgpa_calculator import render_cgpa_calculator
from admin import render_admin_page

def _home():
    """The default page is always served at '/'; it only forwards to /assistant
    so that every real page has its own URL."""
    from ui import nav
    nav.switch("assistant")


PAGE_SPECS = {
    "home": (_home, "Home", ":material/home:", "hidden"),
    "assistant": (render_assistant_page, "Assistant", ":material/forum:", "visible"),
    "places": (render_directory_page, "Places", ":material/location_on:", "visible"),
    "sources": (render_source_explorer_page, "Sources", ":material/menu_book:", "visible"),
    "events": (render_events_page, "Events", ":material/event:", "visible"),
    "calculator": (render_cgpa_calculator, "CGPA Calculator", ":material/calculate:", "visible"),
    "admin": (render_admin_page, "Admin", ":material/admin_panel_settings:", "hidden"),
    "privacy": (render_privacy_page, "Privacy", ":material/policy:", "hidden"),
}


def build_pages(default="home"):
    return {
        name: st.Page(safe_page(fn), title=title, icon=icon, url_path=("" if (name == "home" and default == "home") else name),
                      default=(name == default), visibility=visibility)
        for name, (fn, title, icon, visibility) in PAGE_SPECS.items()
    }
