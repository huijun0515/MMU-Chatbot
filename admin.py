"""
Admin console (hidden page /admin, password-gated).

Tabs: Insights · Knowledge base · Locations · Events.
Login: constant-time comparison, lockout after 5 failures, 30-minute idle timeout, logout.
Knowledge-base sync is incremental: new PDFs are embedded and appended to the
live Chroma DB, with duplicate detection and rate-limit auto-retry.
"""

import os
import re
import time

import streamlit as st
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core import admin_auth, config, insights
from core.logging_setup import logger
from core.vector_store import get_vector_db, embed_with_retry
from events import render_admin_events
from locations import render_admin_locations
from ui.layout import page_footer, page_header

DATA_DIR = config.DATA_DIR


# ──────────────────────────────────────────────────────────────
#  Login
# ──────────────────────────────────────────────────────────────
def _client_key():
    try:
        return st.context.ip_address or "local"
    except Exception:
        return "local"


def _logout():
    for key in ("admin_authed", "admin_last_seen"):
        st.session_state.pop(key, None)


def _check_password():
    """True when the visitor is logged in. Also enforces the idle timeout."""
    try:
        correct = st.secrets.get("ADMIN_PASSWORD")
    except Exception:
        correct = None
    if not correct:
        st.error("The admin console is not configured (no ADMIN_PASSWORD secret).")
        return False

    if st.session_state.get("admin_authed"):
        if admin_auth.session_expired(st.session_state.get("admin_last_seen")):
            _logout()
            st.warning("You were logged out after 30 minutes of inactivity. Please log in again.")
        else:
            st.session_state.admin_last_seen = time.time()
            return True

    key = _client_key()
    locked = admin_auth.seconds_locked(key)
    if locked:
        st.error(f"Too many failed attempts. Try again in {locked // 60 + (1 if locked % 60 else 0)} minute(s).")
        return False

    with st.form("admin_login"):
        pw = st.text_input("Password", type="password", key="admin_pw_input")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        ok, message = admin_auth.attempt(pw, correct, key)
        if ok:
            st.session_state.admin_authed = True
            st.session_state.admin_last_seen = time.time()
            st.rerun()
        st.error(message)
    return False


# ──────────────────────────────────────────────────────────────
#  Knowledge-base helpers (use the underlying chroma collection so
#  metadata filtering works the same across langchain versions)
# ──────────────────────────────────────────────────────────────
def _list_sources(vector_db):
    """Return {source_file: chunk_count} for everything currently indexed."""
    try:
        data = vector_db._collection.get(include=["metadatas"])
    except Exception:
        logger.exception("Failed to read indexed sources from the vector store")
        return {}
    counts = {}
    for md in data.get("metadatas", []) or []:
        if not md or md.get("type") in ("location",):
            continue  # locations are managed in the Locations tab
        name = md.get("source_file") or os.path.basename(md.get("source", "Unknown"))
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _source_exists(vector_db, name):
    try:
        res = vector_db._collection.get(where={"source_file": name}, limit=1)
        return len(res.get("ids", [])) > 0
    except Exception:
        logger.exception("Could not check whether '%s' is indexed", name)
        return False


def _delete_source(vector_db, name):
    """Remove every chunk of a file from the DB, and delete the saved PDF."""
    vector_db._collection.delete(where={"source_file": name})
    path = os.path.join(DATA_DIR, name)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            logger.exception("Failed to delete stored PDF file '%s'", path)


def _safe_pdf_name(name):
    """A plain file name: no folders, no odd characters, always .pdf."""
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[^\w\s.\-()]", "_", base)
    return base if base.lower().endswith(".pdf") and len(base) > 4 else None


def _validate_pdf(uploaded):
    """Return an error message, or None when the upload is acceptable."""
    if _safe_pdf_name(uploaded.name) is None:
        return "The file name must end in .pdf."
    if uploaded.size > config.PDF_MAX_BYTES:
        return f"Larger than {config.PDF_MAX_BYTES // (1024 * 1024)} MB."
    if not uploaded.getvalue().startswith(b"%PDF-"):
        return "This does not look like a real PDF file."
    return None


def _add_in_batches(vector_db, chunks, status):
    bar = st.progress(0.0)
    added = embed_with_retry(vector_db, chunks, status=status, progress_cb=bar.progress)
    bar.empty()
    return added


def _ingest_file(vector_db, uploaded, replace, status):
    """Full pipeline for one uploaded PDF. Returns number of chunks added."""
    error = _validate_pdf(uploaded)
    if error:
        status.error(f"'{uploaded.name}': {error}")
        return 0
    name = _safe_pdf_name(uploaded.name)

    if _source_exists(vector_db, name):
        if not replace:
            status.warning(f"'{name}' is already indexed — skipped. Tick 'Replace' to overwrite it.")
            return 0
        status.info(f"Replacing existing '{name}'…")
        _delete_source(vector_db, name)

    os.makedirs(DATA_DIR, exist_ok=True)
    save_path = os.path.join(DATA_DIR, name)
    with open(save_path, "wb") as f:
        f.write(uploaded.getbuffer())

    try:
        pages = PyPDFLoader(save_path).load()
    except Exception:
        logger.exception("PDF could not be parsed: %s", name)
        os.remove(save_path)
        status.error(f"'{name}' could not be read as a PDF.")
        return 0
    if not pages:
        status.error(f"Could not read any text from '{name}'. (Is it a scanned image PDF? Those need OCR first.)")
        return 0

    chunks = RecursiveCharacterTextSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
                                            ).split_documents(pages)
    for c in chunks:
        c.metadata["source_file"] = name

    added = _add_in_batches(vector_db, chunks, status)
    status.success(f"'{name}' → {added} chunks indexed.")
    return added


@st.dialog("Remove this document?")
def _confirm_delete_source(name):
    st.write(f"**{name}** will be removed from the knowledge base and its PDF deleted from disk. "
             "Answers will no longer cite it.")
    c1, c2 = st.columns(2)
    if c1.button("Remove", type="primary", key=f"yes_src_{name}", use_container_width=True):
        _delete_source(get_vector_db(), name)
        st.cache_resource.clear()
        st.rerun()
    if c2.button("Cancel", key=f"no_src_{name}", use_container_width=True):
        st.rerun()


def _render_kb_admin():
    vector_db = get_vector_db()

    st.subheader("Upload PDFs")
    files = st.file_uploader("Choose one or more PDF files", type=["pdf"], accept_multiple_files=True, key="kb_uploader")
    replace = st.checkbox("Replace a file if it already exists", value=False)

    if st.button("Ingest & sync", type="primary", disabled=not files, icon=":material/cloud_upload:"):
        status = st.empty()
        total_added = 0
        for uploaded in files:
            with st.spinner(f"Processing {uploaded.name}…"):
                total_added += _ingest_file(vector_db, uploaded, replace, status)
        if total_added > 0:
            st.cache_resource.clear()  # the assistant reloads from the updated index
            st.success(f"Done — {total_added} new chunk(s) added. The assistant is up to date.")
        else:
            st.info("Nothing new was added.")

    st.divider()
    st.subheader("Indexed documents")
    sources = _list_sources(vector_db)
    if not sources:
        st.info("No documents indexed yet.")
        return
    st.caption(f"{len(sources)} document(s) · {sum(sources.values())} chunks")
    for name, count in sources.items():
        c1, c2, c3 = st.columns([6, 2, 1.4], vertical_alignment="center")
        c1.write(f"📄 {name}")
        c2.caption(f"{count} chunks")
        if c3.button("Remove", key=f"del_src_{name}", help="Remove from the knowledge base"):
            _confirm_delete_source(name)


# ──────────────────────────────────────────────────────────────
#  Insights
# ──────────────────────────────────────────────────────────────
def _render_insights():
    df = insights.load_frame()
    if df.empty:
        st.info("No questions have been logged yet. Insights appear once students use the assistant.")
        return
    period = st.segmented_control("Period", ["Last 7 days", "Last 30 days", "All time"], default="Last 30 days",
                                  key="ins_period", label_visibility="collapsed") or "All time"
    days = {"Last 7 days": 7, "Last 30 days": 30}.get(period)
    summ = insights.summarize(df, days)
    if summ["total"] == 0:
        st.info("No questions in this period.")
        return

    knowledge = int(summ["intent"].loc["knowledge", "questions"]) if "knowledge" in summ["intent"].index else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Questions", summ["total"])
    m2.metric("Knowledge questions", knowledge)
    m3.metric("Couldn't answer", f"{summ['unanswered_rate']:.0%}",
              help="Share of knowledge questions answered with “couldn't find”")
    up = summ["up_rate"]
    m4.metric("👍 rate", "—" if up is None else f"{up:.0%}",
              help=f"{summ['rated']} answers rated ({summ['thumbs_up']} up, {summ['thumbs_down']} down)")

    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("**Questions per day**")
        st.bar_chart(summ["per_day"])
    with c2:
        st.markdown("**Chit-chat vs knowledge**")
        st.dataframe(summ["intent"], use_container_width=True)
        st.markdown("**Language · input**")
        st.dataframe(summ["language"], use_container_width=True)
        st.dataframe(summ["input_mode"], use_container_width=True)

    st.markdown("**Top questions**")
    st.dataframe(summ["top_questions"].rename(columns={"example": "question"}), use_container_width=True, hide_index=True)

    st.markdown("**Knowledge gaps — questions the assistant could not answer**")
    if len(summ["gaps"]):
        st.dataframe(summ["gaps"].rename(columns={"example": "question"}), use_container_width=True, hide_index=True)
        st.caption("Add or update a document (Knowledge base tab) or a place (Locations tab) to close these gaps.")
    else:
        st.success("No unanswered questions in this period.")

    d1, d2 = st.columns(2)
    d1.download_button("Download the query log (CSV)", insights.export_csv(df), file_name="query_log.csv",
                       mime="text/csv", icon=":material/download:")
    if len(summ["gaps"]):
        d2.download_button("Download knowledge gaps (CSV)", summ["gaps"].to_csv(index=False).encode("utf-8-sig"),
                           file_name="knowledge_gaps.csv", mime="text/csv", icon=":material/download:")


# ──────────────────────────────────────────────────────────────
#  Page
# ──────────────────────────────────────────────────────────────
def render_admin_page():
    page_header("Admin console", "Insights, knowledge base, campus locations and events.", eyebrow="Restricted")
    if not _check_password():
        page_footer()
        return

    top = st.columns([6, 1])
    if top[1].button("Log out", icon=":material/logout:", use_container_width=True):
        _logout()
        st.rerun()

    tab_ins, tab_kb, tab_loc, tab_ev = st.tabs(["Insights", "Knowledge base", "Locations", "Events"])
    with tab_ins:
        _render_insights()
    with tab_kb:
        _render_kb_admin()
    with tab_loc:
        render_admin_locations()
    with tab_ev:
        render_admin_events()
    page_footer()
