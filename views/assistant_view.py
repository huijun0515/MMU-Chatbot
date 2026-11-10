"""
The Campus Assistant chat page. All RAG logic lives in core/rag_chain.py; this
module is Streamlit UI only.
"""

import html

import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

from core import config, voice
from core.logging_setup import logger
from core.rate_limit import try_acquire
from core.vector_store import get_vector_db
from core.rag_chain import build_chat_pipeline, answer_stream, trim_history
from core.query_log import record_feedback
from locations import list_locations, location_card_from_context, status_badge_html
from ui import nav
from ui.layout import page_footer, page_header
from ui.widgets import answer_actions_html

SUGGESTIONS = [
    "Where is the FIST Unix Lab?",
    "Library hours during exam week",
    "How do I withdraw from a subject?",
    "Scholarships for undergraduates",
    "When is the convocation ceremony?",
    "Any events this week?",
]
WELCOME = ("Hello! I am the MMU Campus Assistant. Ask me about academic regulations, the calendar, "
           "scholarships, opening hours, campus locations or upcoming events — in English, Bahasa Melayu or 中文.")


@st.cache_resource
def _load_chat_pipeline():
    vector_db = get_vector_db()  # same shared handle the admin panel writes to
    return build_chat_pipeline(vector_db, list_locations)


def _reset_chat():
    st.session_state.messages = []
    st.session_state.chat_history = []


# ── message parts ─────────────────────────────────────────────────────────
def _render_location_card(card, key):
    if not card:
        return
    with st.container(border=True):
        sub = " · ".join(x for x in [card.get("building", ""), card.get("floor", "")] if x)
        if card.get("image_path"):
            st.image(card["image_path"], use_container_width=True)
        st.markdown(f"**📍 {html.escape(card.get('name', ''))}**" + (f" — {html.escape(sub)}" if sub else "")
                    + "<br>" + status_badge_html(card.get("status")), unsafe_allow_html=True)
        if card.get("opening_hours"):
            st.caption(f"🕒 {card['opening_hours']}")
        if card.get("contact"):
            st.caption(f"📞 {card['contact']}")
        if st.button("View on Places", key=f"loc_{key}", type="tertiary", icon=":material/location_on:"):
            nav.switch("places", places_query=card.get("name", ""))


def _render_citations(citations, key):
    if not citations:
        return
    st.caption("Sources")
    cols = st.columns(min(len(citations), 3))
    for i, c in enumerate(citations):
        with cols[i % len(cols)]:
            if c["type"] == "pdf" and c["page"]:
                if st.button(c["label"], key=f"cite_{key}_{i}", icon=":material/description:",
                             help="Open this page in Sources with the passage highlighted", use_container_width=True):
                    nav.switch("sources", source_focus={"doc": c["doc"], "page": c["page"], "passage": c["passage"]})
            elif c["type"] == "location":
                if st.button(c["label"], key=f"cite_{key}_{i}", icon=":material/location_on:", use_container_width=True):
                    nav.switch("places")
            elif c["type"] == "event":
                if st.button(c["label"], key=f"cite_{key}_{i}", icon=":material/event:", use_container_width=True):
                    nav.switch("events")
            else:
                st.markdown(f"<span class='cite'>📄 {html.escape(c['label'])}</span>", unsafe_allow_html=True)


def _on_feedback(log_id, widget_key):
    value = st.session_state.get(widget_key)
    if value is not None:
        record_feedback(log_id, "up" if value == 1 else "down")


def _render_assistant_extras(message, key):
    """Location card, citations, copy/read-aloud and feedback under an assistant message.
    Used for both the live answer and the history re-render so they never disagree."""
    _render_location_card(message.get("location"), key)
    _render_citations(message.get("citations") or [], key)
    if message.get("log_id"):
        st.iframe(answer_actions_html(message["content"], tts=config.TTS_ENABLED), height=42)
        st.feedback("thumbs", key=f"fb_{message['log_id']}", on_change=_on_feedback,
                    args=(message["log_id"], f"fb_{message['log_id']}"))


# ── voice ─────────────────────────────────────────────────────────────────
def _reset_voice():
    for key in ("voice_raw", "voice_text"):
        st.session_state.pop(key, None)
    st.session_state.voice_n = st.session_state.get("voice_n", 0) + 1  # fresh recorder widget


def _voice_panel():
    """Record -> Transcribe -> edit -> Send. The transcript is NEVER sent automatically."""
    if not config.VOICE_ENABLED:
        return
    n = st.session_state.setdefault("voice_n", 0)
    with st.popover("Ask by voice", icon=":material/mic:"):
        st.caption(f"Record up to {config.VOICE_MAX_SECONDS} s in English, Bahasa Melayu or 中文, then check the text "
                   "before sending. The microphone needs HTTPS or localhost and the browser must be allowed to use it "
                   "(if recording does nothing, click the lock icon in the address bar and allow the microphone).")
        audio = st.audio_input("Record your question", key=f"voice_audio_{n}")
        if audio is not None and st.button("Transcribe", key=f"voice_tx_{n}", icon=":material/edit_note:"):
            allowed, wait = try_acquire(st.session_state)
            if not allowed:
                st.warning(f"Too many requests — please wait {wait}s and try again.")
            else:
                try:
                    with st.spinner("Listening…"):
                        text = voice.transcribe(audio.getvalue())
                    st.session_state.voice_raw = text
                    st.session_state.voice_text = text
                except voice.VoiceError as exc:
                    st.error(str(exc))
        if "voice_raw" in st.session_state:
            st.text_area("Transcript — fix anything misheard (e.g. room codes) before sending", key="voice_text",
                         max_chars=config.CHAT_MAX_CHARS)
            c1, c2 = st.columns(2)
            if c1.button("Send", type="primary", key="voice_send", use_container_width=True, icon=":material/send:"):
                text = st.session_state.voice_text.strip()
                if text:
                    st.session_state.voice_query = (text, text != st.session_state.voice_raw)
                    _reset_voice()
                    st.rerun()
            if c2.button("Discard", key="voice_discard", use_container_width=True):
                _reset_voice()
                st.rerun()


# ── page ──────────────────────────────────────────────────────────────────
def render_assistant_page():
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("chat_history", [])

    head, actions = st.columns([4, 1])
    with head:
        page_header("Assistant", "Grounded answers from official MMU documents and the campus directory.",
                    eyebrow="MMU Campus Assistant")
    with actions:
        if st.session_state.messages and st.button("New chat", icon=":material/add_comment:", use_container_width=True):
            _reset_chat()
            st.rerun()

    prompt = None
    if not st.session_state.messages:
        st.markdown(f"<div class='welcome'><h2>👋 Welcome</h2><p>{WELCOME}</p></div>", unsafe_allow_html=True)
        picked = st.pills("Try asking", SUGGESTIONS, key=f"suggest_{len(st.session_state.messages)}",
                          label_visibility="collapsed")
        if picked:
            prompt = picked
            st.session_state.input_mode = "quick"

    try:
        pipeline = _load_chat_pipeline()
    except Exception:
        logger.exception("Could not start the assistant")
        st.error("The assistant is not available right now (configuration problem). Please try again later.")
        page_footer()
        return

    for i, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                _render_assistant_extras(message, message.get("log_id") or f"m{i}")

    st.markdown("<div class='privacy-note'>Questions and answers are logged anonymously to improve this assistant — "
                "no names or student IDs. See the privacy notice in the footer.</div>", unsafe_allow_html=True)
    _voice_panel()
    typed = st.chat_input("Ask about MMU — English, Bahasa Melayu or 中文", max_chars=config.CHAT_MAX_CHARS)

    input_mode, voice_edited = st.session_state.pop("input_mode", "text"), None
    if typed:
        prompt, input_mode = typed, "text"
    if "quick_query" in st.session_state:  # prefilled from another page ("Ask the assistant about this place")
        prompt, input_mode = st.session_state.pop("quick_query"), "quick"
    if "voice_query" in st.session_state:
        (prompt, voice_edited), input_mode = st.session_state.pop("voice_query"), "voice"

    if prompt and len(prompt) > config.CHAT_MAX_CHARS:
        st.warning(f"Please keep your question under {config.CHAT_MAX_CHARS} characters.")
        prompt = None
    if prompt:
        allowed, wait = try_acquire(st.session_state)
        if not allowed:
            st.warning(f"You're sending messages very quickly — please wait {wait}s and try again.")
            prompt = None

    if prompt:
        with st.chat_message("user"):
            st.markdown(html.escape(prompt))
        st.session_state.messages.append({"role": "user", "content": html.escape(prompt)})

        with st.chat_message("assistant"):
            try:
                stream = answer_stream(pipeline, prompt, st.session_state.chat_history,
                                       input_mode=input_mode, voice_edited=voice_edited)
                answer = st.write_stream(stream.tokens())
                result = stream.result()
                message = {
                    "role": "assistant",
                    "content": answer,
                    "sources": result["sources"],
                    "citations": result["citations"],
                    "location": location_card_from_context(result["context"]) if result["grounded"] else None,
                    "log_id": result["log_id"],
                }
                _render_assistant_extras(message, message["log_id"] or "live")
                # Memory covers chit-chat too, so "thanks" after an answer stays in context.
                st.session_state.chat_history.append(HumanMessage(content=prompt))
                st.session_state.chat_history.append(AIMessage(content=answer))
                st.session_state.chat_history = trim_history(st.session_state.chat_history)
                st.session_state.messages.append(message)
                st.rerun()  # redraw via the message loop so the widgets get stable keys
            except Exception:
                logger.exception("Answer failed")
                msg = ("Sorry — I couldn't get an answer just now. Please try again in a moment, "
                       "or contact the Student Service Centre (ssc@mmu.edu.my) for urgent matters.")
                st.error(msg)
                st.session_state.messages.append({"role": "assistant", "content": msg})

    page_footer()
