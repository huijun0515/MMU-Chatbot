"""
The Campus Assistant chat page — pulled out of app.py so app.py can stay a
thin router. All RAG logic itself lives in core/rag_chain.py; this module is
Streamlit UI only.
"""

import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

from core import config, voice
from core.rate_limit import try_acquire
from core.vector_store import get_vector_db
from core.rag_chain import build_chat_pipeline, ask, trim_history
from core.query_log import record_feedback
from locations import list_locations, location_card_from_context, status_badge_html


@st.cache_resource
def _load_chat_pipeline():
    vector_db = get_vector_db()  # same shared handle the admin panel writes to
    return build_chat_pipeline(vector_db, list_locations)


def _render_location_card(card):
    if not card:
        return
    sub = " · ".join(x for x in [card.get("building", ""), card.get("floor", "")] if x)
    if card.get("image_path"):
        st.image(card["image_path"], caption=f"📍 {card.get('name', '')}" + (f" — {sub}" if sub else ""),
                 use_container_width=True)
    else:
        st.markdown(f"**📍 {card.get('name', '')}**" + (f" — {sub}" if sub else ""))
    badge = status_badge_html(card.get("status"))
    if badge:
        st.markdown(badge, unsafe_allow_html=True)
    if card.get("opening_hours"):
        st.caption(f"🕒 {card['opening_hours']}")
    if card.get("contact"):
        st.caption(f"📞 {card['contact']}")


def _render_answer_extras(message):
    """Location card + sources under an assistant message. Used by BOTH the live
    answer and the history re-render so the two can never disagree; the sources
    expander is omitted entirely when there are none (chit-chat, ungrounded)."""
    if message.get("location"):
        _render_location_card(message["location"])
    if message.get("sources"):
        with st.expander("📚 View Sources"):
            for source in message["sources"]:
                st.caption(f"📄 {source}")


def _render_feedback(message):
    """👍/👎 on a past answer, written back into the query log by its id."""
    entry_id = message.get("log_id")
    if not entry_id:
        return
    key = f"fb_{entry_id}"
    if st.session_state.get(key):
        st.caption("Thanks for the feedback!" if st.session_state[key] == "noted" else "")
        return
    c1, c2, _ = st.columns([0.06, 0.06, 0.88])
    with c1:
        if st.button("👍", key=f"up_{entry_id}"):
            record_feedback(entry_id, "up")
            st.session_state[key] = "noted"
            st.rerun()
    with c2:
        if st.button("👎", key=f"down_{entry_id}"):
            record_feedback(entry_id, "down")
            st.session_state[key] = "noted"
            st.rerun()


def _reset_voice():
    for key in ("voice_raw", "voice_text"):
        st.session_state.pop(key, None)
    st.session_state.voice_n = st.session_state.get("voice_n", 0) + 1  # fresh recorder widget


def _voice_panel():
    """Record -> Transcribe -> edit -> Send. The transcript is NEVER sent automatically."""
    if not config.VOICE_ENABLED:
        return
    n = st.session_state.setdefault("voice_n", 0)
    with st.popover("🎤 Ask by voice"):
        st.caption(f"Record up to {config.VOICE_MAX_SECONDS} s in English, Bahasa Melayu or 中文, then check the text "
                   "before sending. The microphone needs HTTPS or localhost, and the browser must be allowed to use it "
                   "(if recording does nothing, click the lock icon in the address bar and allow the microphone).")
        audio = st.audio_input("Record your question", key=f"voice_audio_{n}")
        if audio is not None and st.button("📝 Transcribe", key=f"voice_tx_{n}"):
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
            st.text_area("Transcript — fix anything misheard (e.g. room codes) before sending", key="voice_text")
            c1, c2 = st.columns(2)
            if c1.button("➤ Send", type="primary", key="voice_send", use_container_width=True):
                text = st.session_state.voice_text.strip()
                if text:
                    st.session_state.voice_query = (text, text != st.session_state.voice_raw)
                    _reset_voice()
                    st.rerun()
            if c2.button("Discard", key="voice_discard", use_container_width=True):
                _reset_voice()
                st.rerun()


def render_assistant_page():
    pipeline = _load_chat_pipeline()

    st.markdown("<h1 style='text-align: center; color: #0033A0;'>🎓 MMU Campus Assistant</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Your 24/7 intelligent guide to Multimedia University.</p>", unsafe_allow_html=True)
    st.markdown("---")

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hello! I am the MMU Campus Assistant Bot. You can ask me anything!"}
        ]
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    st.write("**Suggested Queries:**")
    col1, col2, col3, col4 = st.columns(4)

    def set_query(query):
        st.session_state.quick_query = query

    with col1:
        st.button("📍 Find Lecture Hall", on_click=set_query, args=("Where is the nearest lecture hall?",), use_container_width=True)
    with col2:
        st.button("📅 Exam Rules", on_click=set_query, args=("What are the rules for final exams?",), use_container_width=True)
    with col3:
        st.button("💰 Finance Office", on_click=set_query, args=("Where is the finance office?",), use_container_width=True)
    with col4:
        st.button("📚 Library Hours", on_click=set_query, args=("What time does the library open?",), use_container_width=True)

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            _render_answer_extras(message)
            if message["role"] == "assistant" and message.get("log_id"):
                if config.TTS_ENABLED:
                    st.iframe(voice.read_aloud_html(message["content"]), height=42)
                _render_feedback(message)

    _voice_panel()
    prompt = st.chat_input("Type your question here...")
    input_mode, voice_edited = "text", None
    if "quick_query" in st.session_state:
        prompt = st.session_state.quick_query
        del st.session_state.quick_query
        input_mode = "quick"
    if "voice_query" in st.session_state:
        prompt, voice_edited = st.session_state.pop("voice_query")
        input_mode = "voice"

    if prompt:
        allowed, wait = try_acquire(st.session_state)
        if not allowed:
            st.warning(f"You're sending messages very quickly — please wait {wait}s and try again.")
            prompt = None

    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("🧠 Thinking for the answer..."):
                try:
                    response = ask(pipeline, prompt, st.session_state.chat_history,
                                   input_mode=input_mode, voice_edited=voice_edited)
                    ai_answer = response["answer"]

                    # Sources and the location photo only appear for grounded answers
                    # (ask() already empties `sources` otherwise).
                    message = {
                        "role": "assistant",
                        "content": ai_answer,
                        "sources": response["sources"],
                        "location": location_card_from_context(response["context"])
                        if response["grounded"] else None,
                        "log_id": response["log_id"],
                    }
                    st.markdown(ai_answer)
                    _render_answer_extras(message)

                    # Memory covers chit-chat too, so "thanks" after an answer stays in context.
                    st.session_state.chat_history.append(HumanMessage(content=prompt))
                    st.session_state.chat_history.append(AIMessage(content=ai_answer))
                    st.session_state.chat_history = trim_history(st.session_state.chat_history)

                    st.session_state.messages.append(message)
                    st.rerun()  # redraw via the message loop so the 👍/👎 buttons attach

                except Exception as e:
                    error_message = f"❌ Oops, something went wrong: {e}"
                    st.markdown(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
