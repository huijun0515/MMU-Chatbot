"""
Admin panel for the MMU Campus Assistant.

Two tabs (both behind one password gate):
  📚 Knowledge Base  — upload/sync/delete PDFs (no rebuild required)
  📢 Announcements   — publish/delete campus event posters

Knowledge-base sync is incremental: new PDFs are embedded and appended to the
live Chroma DB, with duplicate detection and rate-limit auto-retry.
"""

import os
import streamlit as st
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core import config
from core.vector_store import get_vector_db, embed_with_retry
from core.logging_setup import logger
from announcements import render_admin_announcements
from locations import render_admin_locations

DATA_DIR = config.DATA_DIR


# ──────────────────────────────────────────────────────────────
#  Low-level DB helpers (use the underlying chroma collection so
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
        if not md:
            continue
        if md.get("type") == "location":
            continue  # locations are managed in the Locations tab, not here
        name = md.get("source_file") or os.path.basename(md.get("source", "Unknown"))
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _source_exists(vector_db, name):
    try:
        res = vector_db._collection.get(where={"source_file": name}, limit=1)
        return len(res.get("ids", [])) > 0
    except Exception:
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


def _add_in_batches(vector_db, chunks, status):
    """Embed + store chunks in small batches, retrying on rate limits
    (a no-op concern with the default local embedding backend)."""
    bar = st.progress(0.0)
    added = embed_with_retry(vector_db, chunks, status=status, progress_cb=bar.progress)
    bar.empty()
    return added


def _ingest_file(vector_db, uploaded, replace, status):
    """Full pipeline for one uploaded PDF. Returns number of chunks added."""
    name = uploaded.name

    if _source_exists(vector_db, name):
        if not replace:
            status.warning(f"⏭️ '{name}' is already indexed — skipped. "
                           f"Tick 'Replace' to overwrite it.")
            return 0
        status.info(f"♻️ Replacing existing '{name}'…")
        _delete_source(vector_db, name)

    os.makedirs(DATA_DIR, exist_ok=True)
    save_path = os.path.join(DATA_DIR, name)
    with open(save_path, "wb") as f:
        f.write(uploaded.getbuffer())

    pages = PyPDFLoader(save_path).load()
    if not pages:
        status.error(f"❌ Could not read any text from '{name}'. "
                     f"(Is it a scanned image PDF? Those need OCR first.)")
        return 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(pages)

    for c in chunks:
        c.metadata["source_file"] = name

    added = _add_in_batches(vector_db, chunks, status)
    status.success(f"✅ '{name}' → {added} chunks indexed.")
    return added


# ──────────────────────────────────────────────────────────────
#  Password gate
# ──────────────────────────────────────────────────────────────
def _check_password():
    correct = st.secrets.get("ADMIN_PASSWORD")
    if not correct:
        st.error("No **ADMIN_PASSWORD** found in secrets. Add one to "
                 "`.streamlit/secrets.toml` to use the admin panel.")
        return False

    if st.session_state.get("admin_authed"):
        return True

    st.markdown("### 🔐 Admin Login")
    pw = st.text_input("Password", type="password", key="admin_pw_input")
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("Login"):
            if pw == correct:
                st.session_state.admin_authed = True
                st.rerun()
            else:
                st.error("Wrong password.")
    return False


# ──────────────────────────────────────────────────────────────
#  Knowledge-base tab
# ──────────────────────────────────────────────────────────────
def _render_kb_admin():
    vector_db = get_vector_db()

    st.subheader("📤 Upload PDFs")
    files = st.file_uploader(
        "Choose one or more PDF files",
        type=["pdf"],
        accept_multiple_files=True,
        key="kb_uploader",
    )
    replace = st.checkbox("Replace file if it already exists", value=False)

    if st.button("🚀 Ingest & Sync", type="primary", disabled=not files):
        status = st.empty()
        total_added = 0
        for uploaded in files:
            with st.spinner(f"Processing {uploaded.name}…"):
                total_added += _ingest_file(vector_db, uploaded, replace, status)

        if total_added > 0:
            st.cache_resource.clear()   # assistant reloads from updated DB next answer
            st.success(f"🎉 Done — {total_added} new chunk(s) added. "
                       f"The assistant is now up to date.")
        else:
            st.info("Nothing new was added.")

    st.markdown("---")
    st.subheader("📚 Indexed Sources")
    sources = _list_sources(vector_db)

    if not sources:
        st.info("No documents indexed yet.")
        return

    st.caption(f"{len(sources)} document(s) · {sum(sources.values())} chunks total")
    for name, count in sources.items():
        c1, c2, c3 = st.columns([6, 2, 1])
        c1.write(f"📄 {name}")
        c2.write(f"{count} chunks")
        if c3.button("🗑️", key=f"del_src_{name}", help="Remove from knowledge base"):
            _delete_source(vector_db, name)
            st.cache_resource.clear()
            st.success(f"Removed '{name}'.")
            st.rerun()


# ──────────────────────────────────────────────────────────────
#  Main page
# ──────────────────────────────────────────────────────────────
def render_admin_page():
    st.markdown(
        "<h1 style='text-align:center;color:#0033A0;'>🔐 Admin Console</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;'>Manage the knowledge base and campus announcements.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    if not _check_password():
        return

    tab_kb, tab_loc, tab_ann = st.tabs(
        ["📚 Knowledge Base", "📍 Locations", "📢 Announcements"]
    )
    with tab_kb:
        _render_kb_admin()
    with tab_loc:
        render_admin_locations()
    with tab_ann:
        render_admin_announcements()