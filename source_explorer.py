"""
Sources — verify any answer against the real document page.

- Semantic search across the knowledge base, optionally within one document.
- Every hit shows the passage, the PDF and the page; "View source page" renders
  the ACTUAL page with the passage highlighted (PyMuPDF search_for + highlight).
- Deep links: a chat citation hands over session_state["source_focus"]
  ({doc, page, passage}); ?doc=<file>&page=<n> in the URL does the same.
- Browse-all lets users open any indexed PDF at any page and download it.
"""

import html
import os

import streamlit as st

from core.config import DATA_DIR
from core.logging_setup import logger
from core.vector_store import get_vector_db
from ui.layout import page_footer, page_header

try:
    import pymupdf
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


# ── PDF helpers ───────────────────────────────────────────────────────────
def _list_pdf_files():
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf"))


@st.cache_data(show_spinner=False)
def _page_count(path, mtime):
    if not HAS_FITZ:
        return None
    try:
        return pymupdf.open(path).page_count
    except Exception:
        logger.exception("Could not open %s", path)
        return None


def _highlight_lines(passage):
    """The lines of a retrieved chunk worth searching for on the page: long enough
    to be unambiguous, short enough for search_for to match a single text line."""
    out = []
    for line in (passage or "").splitlines():
        line = " ".join(line.split())
        if len(line) >= 12:
            out.append(line[:90])
    return out[:40]


@st.cache_data(show_spinner=False)
def _render_page(path, mtime, page_index, passage, dpi=130):
    """PNG bytes of one page, with the passage highlighted. Returns (png, n_highlights)."""
    if not HAS_FITZ:
        return None, 0
    try:
        doc = pymupdf.open(path)
        page_index = max(0, min(page_index, doc.page_count - 1))
        page = doc[page_index]
        hits = 0
        for line in _highlight_lines(passage):
            for rect in page.search_for(line):
                page.add_highlight_annot(rect)
                hits += 1
        return page.get_pixmap(dpi=dpi).tobytes("png"), hits
    except Exception:
        logger.exception("Could not render page %s of %s", page_index, path)
        return None, 0


def _show_page(path, page_index, passage=None):
    png, hits = _render_page(path, os.path.getmtime(path), page_index, passage or "")
    if png is None:
        st.info("Preview unavailable for this page. You can download the PDF below.")
        return
    if passage and hits == 0:
        st.caption("The exact passage could not be located on the page image (text layout differs); "
                   "the page itself is shown.")
    st.image(png, use_container_width=True)


def _download(path, key):
    try:
        with open(path, "rb") as fh:
            st.download_button("Download full PDF", fh.read(), file_name=os.path.basename(path),
                               mime="application/pdf", key=key, icon=":material/download:")
    except OSError:
        logger.exception("Could not read %s for download", path)


# ── page ──────────────────────────────────────────────────────────────────
def _take_focus(files):
    """A document/page to open first: from a chat citation (session) or the URL."""
    focus = st.session_state.pop("source_focus", None)
    if not focus:
        doc = st.query_params.get("doc")
        if doc:
            try:
                page = int(st.query_params.get("page", 1))
            except ValueError:
                page = 1
            focus = {"doc": doc, "page": page, "passage": ""}
    if focus and focus.get("doc") in files:
        return focus
    return None


def render_source_explorer_page():
    page_header("Sources", "Search the official documents and verify every answer against its exact source page.",
                eyebrow="Knowledge base")
    files = _list_pdf_files()
    if not files:
        st.info("No source documents indexed yet. An admin can add PDFs from the Admin panel.")
        page_footer()
        return

    focus = _take_focus(files)
    if focus:
        path = os.path.join(DATA_DIR, focus["doc"])
        n_pages = _page_count(path, os.path.getmtime(path)) or 1
        page_no = max(1, min(int(focus.get("page") or 1), n_pages))
        with st.container(border=True):
            st.markdown(f"<span class='chip'>📄 {html.escape(focus['doc'])}</span>"
                        f"<span class='chip'>Page {page_no} of {n_pages}</span>", unsafe_allow_html=True)
            if focus.get("passage"):
                st.markdown(f"<div class='snippet'>{html.escape(focus['passage'][:600])}"
                            f"{'…' if len(focus['passage']) > 600 else ''}</div>", unsafe_allow_html=True)
            _show_page(path, page_no - 1, focus.get("passage"))
            _download(path, "dl_focus")
        st.divider()

    # ── Semantic search ─────────────────────────────────────────
    st.subheader("Search the documents")
    c1, c2 = st.columns([2, 1])
    query = c1.text_input("What are you looking for?", placeholder="e.g. rules for retaking a failed subject",
                          icon=":material/search:")
    doc_filter = c2.selectbox("Document", ["All documents"] + files)

    if query:
        vector_db = get_vector_db()
        kwargs = {"k": 5}
        if doc_filter != "All documents":
            kwargs["filter"] = {"source_file": doc_filter}
        else:
            kwargs["filter"] = {"type": {"$ne": "location"}}
        try:
            with st.spinner("Searching official documents…"):
                results = vector_db.similarity_search(query, **kwargs)
        except Exception:
            logger.exception("Source search failed")
            st.error("Search is unavailable right now. Please try again in a moment.")
            results = []

        if not results:
            st.warning("No matching passages found. Try different wording or another document.")
        for n, doc in enumerate(results):
            src = doc.metadata.get("source_file") or "Unknown"
            page_idx = doc.metadata.get("page", 0)
            page_idx = int(page_idx) if isinstance(page_idx, int) else 0
            snippet = " ".join(doc.page_content.split())
            snippet = snippet[:320] + ("…" if len(snippet) > 320 else "")
            st.markdown(f"<span class='chip'>📄 {html.escape(src)}</span><span class='chip'>Page {page_idx + 1}</span>"
                        f"<div class='snippet'>{html.escape(snippet)}</div>", unsafe_allow_html=True)
            path = os.path.join(DATA_DIR, src)
            with st.expander(f"View source page {page_idx + 1} with the passage highlighted"):
                if os.path.exists(path):
                    _show_page(path, page_idx, doc.page_content)
                    _download(path, f"dl_hit_{n}")
                else:
                    st.warning(f"The file '{src}' is no longer on disk.")
            st.markdown("")

    st.divider()

    # ── Browse all documents ────────────────────────────────────
    st.subheader("Browse all documents")
    browse = files if doc_filter == "All documents" else [doc_filter]
    st.caption(f"{len(files)} document(s) in the knowledge base.")
    for f in browse:
        path = os.path.join(DATA_DIR, f)
        n_pages = _page_count(path, os.path.getmtime(path))
        label = f"📄 {f}" + (f"  ·  {n_pages} pages" if n_pages else "")
        with st.expander(label):
            if n_pages and n_pages > 0:
                page_no = st.number_input("Go to page", min_value=1, max_value=n_pages, value=1, step=1, key=f"pageno_{f}")
                _show_page(path, int(page_no) - 1)
            else:
                _show_page(path, 0)
            _download(path, f"dl_{f}")
    page_footer()
