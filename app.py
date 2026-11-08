"""
App entry point — thin router only.

Everything else lives elsewhere on purpose:
  core/        RAG engine (config, vector store, chat chain, location lookup, query log)
  ui/          shared CSS
  views/       the chat page
  admin.py, announcements.py, locations.py, cgpa_calculator.py, source_explorer.py
               self-contained feature pages

The admin console has NO button in the student-facing sidebar. It opens only
via a URL flag — e.g. http://localhost:8501/?admin=1 — and is still gated by
the password check inside admin.py itself.
"""

import streamlit as st

from ui.styles import SIDEBAR_CSS
from views.assistant_view import render_assistant_page
from cgpa_calculator import render_cgpa_calculator
from admin import render_admin_page
from announcements import render_announcements_page
from source_explorer import render_source_explorer_page
from locations import render_directory_page


st.set_page_config(
    page_title="MMU Campus Assistant",
    page_icon="🎓",
    layout="wide",
)
st.markdown(SIDEBAR_CSS, unsafe_allow_html=True)


if "current_page" not in st.session_state:
    st.session_state.current_page = "Assistant"

# Hidden admin entry point: http://localhost:8501/?admin=1 (still password-gated).
if "admin" in st.query_params:
    st.session_state.current_page = "Admin"
    st.query_params.clear()  # consume the flag so normal nav still works

PAGES = {
    "Assistant": render_assistant_page,
    "Calculator": render_cgpa_calculator,
    "Announcements": render_announcements_page,
    "Sources": render_source_explorer_page,
    "Places": render_directory_page,
    "Admin": render_admin_page,
}

NAV_ITEMS = [
    ("Assistant", "🤖 Assistant"),
    ("Calculator", "📊 Calculator"),
    ("Announcements", "📢 Events"),
    ("Sources", "📚 Sources"),
    ("Places", "📍 Places"),
]  # "Admin" is intentionally absent — reachable only via ?admin=1


with st.sidebar:
    st.markdown("""
    <div class="sidebar-header">
        <div class="sidebar-icon">🏛️</div>
        <h2>MMU Student Hub</h2>
        <p>Multimedia University</p>
    </div>
    """, unsafe_allow_html=True)

    for r in range(0, len(NAV_ITEMS), 2):
        nav_cols = st.columns(2)
        for col, (key, label) in zip(nav_cols, NAV_ITEMS[r:r + 2]):
            with col:
                if st.button(
                    label,
                    use_container_width=True,
                    type="primary" if st.session_state.current_page == key else "secondary",
                    key=f"nav_{key}",
                ):
                    st.session_state.current_page = key
                    st.rerun()

    st.markdown("<div class='features-title'>FEATURES</div>", unsafe_allow_html=True)
    st.markdown("""
    <div class='feature-item'>📍 Campus Navigation</div>
    <div class='feature-item'>📖 Academic Regulations</div>
    <div class='feature-item'>📞 Staff & Faculty Info</div>
    <div class='feature-item'>📊 CGPA Calculator</div>
    """, unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)

    if st.session_state.current_page == "Assistant":
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state.messages = [{"role": "assistant", "content": "Hello! I am the MMU Campus Assistant. Ask me anything!"}]
            st.session_state.chat_history = []
            st.rerun()

    st.markdown("<div class='sidebar-footer'>FYP Prototype · Developed by Goh Hui Jun</div>", unsafe_allow_html=True)


PAGES[st.session_state.current_page]()
