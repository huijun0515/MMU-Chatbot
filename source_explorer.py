"""
Source Explorer — lets users verify the assistant's answers against the real PDFs.

- Semantic search across everything in the knowledge base.
- Each hit shows the passage, which PDF it came from, and the page number.
- "View source page" renders the ACTUAL page of the PDF as an image, so a
  student can see with their own eyes where an answer came from.
- Browse-all section lets users open any indexed PDF at any page and download it.

This is the traceability / anti-hallucination feature: the bot never asks to be
trusted blindly — every claim can be traced back to an official document page.

Page rendering uses PyMuPDF (pip install pymupdf). If it's not installed the
page's text is shown instead, so the feature still works.
"""

import os
import streamlit as st

from vector_store import get_vector_db, DATA_DIR

# Optional: PyMuPDF for rendering a page as an image
try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    try:
        import pymupdf as fitz
        HAS_FITZ = True
    except ImportError:
        HAS_FITZ = False

# pypdf ships with langchain's PDF loader, so it's always available
try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


_SRC_CSS = """
<style>
.src-snippet {
    background:#f8fafc; border-left:4px solid #0033A0;
    padding:12px 16px; border-radius:8px; color:#334155;
    font-size:.9rem; line-height:1.55;
}
.src-tag {
    display:inline-block; background:#EEF3FF; color:#0033A0;
    font-size:.72rem; font-weight:700; padding:3px 10px;
    border-radius:999px; margin-right:6px;
}
</style>
"""


def _list_pdf_files():
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf"))


def _page_count(path):
    if HAS_PYPDF:
        try:
            return len(PdfReader(path).pages)
        except Exception:
            pass
    if HAS_FITZ:
        try:
            return fitz.open(path).page_count
        except Exception:
            pass
    return None


def _render_pdf_page(path, page_index, dpi=130):
    """Return PNG bytes of a single page, or None if rendering isn't possible."""
    if not HAS_FITZ:
        return None
    try:
        doc = fitz.open(path)
        if page_index < 0 or page_index >= doc.page_count:
            page_index = max(0, min(page_index, doc.page_count - 1))
        pix = doc.load_page(page_index).get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    except Exception:
        return None


def _page_text(path, page_index):
    if not HAS_PYPDF:
        return ""
    try:
        reader = PdfReader(path)
        if 0 <= page_index < len(reader.pages):
            return reader.pages[page_index].extract_text() or ""
    except Exception:
        pass
    return ""


def _show_page(path, page_index, key_prefix):
    """Render a page visually if possible, else fall back to its text."""
    png = _render_pdf_page(path, page_index)
    if png is not None:
        st.image(png, use_container_width=True)
    else:
        txt = _page_text(path, page_index)
        if txt:
            st.text(txt)
        else:
            st.info("Preview unavailable. Install PyMuPDF (`pip install pymupdf`) "
                    "to see page images, or download the PDF below.")


def render_source_explorer_page():
    st.markdown(_SRC_CSS, unsafe_allow_html=True)
    st.markdown("<h1 style='text-align:center;color:#0033A0;'>📚 Source Explorer</h1>",
                unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;'>Search the official documents and verify every answer "
                "against its exact source page.</p>", unsafe_allow_html=True)
    st.markdown("---")

    files = _list_pdf_files()
    if not files:
        st.info("No source documents indexed yet. An admin can add PDFs from the Admin panel.")
        return

    # ── Semantic search ─────────────────────────────────────────
    st.subheader("🔎 Search the documents")
    query = st.text_input("What are you looking for?",
                          placeholder="e.g. rules for retaking a failed subject")

    if query:
        vector_db = get_vector_db()
        with st.spinner("Searching official documents…"):
            try:
                results = vector_db.similarity_search(query, k=5)
            except Exception as e:
                st.error(f"Search failed: {e}")
                results = []

        if not results:
            st.warning("No matching passages found. Try different wording.")
        else:
            st.caption(f"Top {len(results)} matching passage(s):")
            for n, doc in enumerate(results):
                src = doc.metadata.get("source_file") or os.path.basename(
                    doc.metadata.get("source", "Unknown"))
                page_idx = doc.metadata.get("page", 0)
                try:
                    page_idx = int(page_idx)
                except (TypeError, ValueError):
                    page_idx = 0

                snippet = doc.page_content.strip().replace("\n", " ")
                if len(snippet) > 320:
                    snippet = snippet[:320] + "…"

                st.markdown(
                    f"<span class='src-tag'>📄 {src}</span>"
                    f"<span class='src-tag'>Page {page_idx + 1}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"<div class='src-snippet'>{snippet}</div>",
                            unsafe_allow_html=True)

                with st.expander(f"🔍 View source page {page_idx + 1} in {src}"):
                    path = os.path.join(DATA_DIR, src)
                    if os.path.exists(path):
                        _show_page(path, page_idx, key_prefix=f"search_{n}")
                    else:
                        st.warning(f"The file '{src}' is no longer on disk.")
                st.markdown("")

    st.markdown("---")

    # ── Browse all documents ────────────────────────────────────
    st.subheader("🗂️ Browse all documents")
    st.caption(f"{len(files)} document(s) in the knowledge base.")

    for f in files:
        path = os.path.join(DATA_DIR, f)
        n_pages = _page_count(path)
        label = f"📄 {f}" + (f"  ·  {n_pages} pages" if n_pages else "")
        with st.expander(label):
            if n_pages and n_pages > 0:
                page_no = st.number_input(
                    "Go to page",
                    min_value=1, max_value=n_pages, value=1, step=1,
                    key=f"pageno_{f}",
                )
                _show_page(path, int(page_no) - 1, key_prefix=f"browse_{f}")
            else:
                _show_page(path, 0, key_prefix=f"browse_{f}")

            try:
                with open(path, "rb") as fh:
                    st.download_button(
                        "⬇️ Download full PDF",
                        data=fh.read(),
                        file_name=f,
                        mime="application/pdf",
                        key=f"dl_{f}",
                    )
            except Exception:
                pass