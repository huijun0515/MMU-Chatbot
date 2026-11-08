"""
Full (re)build of the vector database from scratch — ./data PDFs AND the
structured locations in ./locations/locations.json.

This is the ONLY place that wipes chroma_db. The admin panel's upload flow
(admin.py) always appends via add_documents() and never calls this.

Run this:
  - the first time you set up the project, or
  - whenever you change EMBEDDING_BACKEND / the embedding model name in
    core/config.py — a different embedding model produces vectors of a
    different dimensionality, which makes the existing chroma_db unreadable.

Usage:
    python build_database.py
"""

import os
import shutil

from core import config
from core.vector_store import build_vector_db, embed_with_retry
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter


def _check_api_key():
    """Only the Gemini embedding backend needs an API key to BUILD the DB.
    (Gemini is still used for answer generation at chat time regardless, but
    that only matters when the app runs, not when this script runs.)"""
    if config.EMBEDDING_BACKEND == "gemini" and not config.get_secret("GEMINI_API_KEY"):
        raise SystemExit(
            "EMBEDDING_BACKEND=gemini but GEMINI_API_KEY is not set.\n"
            "  Add it to .streamlit/secrets.toml, or:\n"
            '  mac/linux:  export GEMINI_API_KEY="your-key"\n'
            "  windows:    set GEMINI_API_KEY=your-key"
        )


def build_database():
    _check_api_key()

    if os.path.isdir(config.CHROMA_DIR):
        print(f"Removing existing {config.CHROMA_DIR} (full rebuild) ...")
        shutil.rmtree(config.CHROMA_DIR)

    print(f"Embedding backend: {config.EMBEDDING_BACKEND}")
    vector_db = build_vector_db()

    print("Step 1: Loading PDFs from ./data ...")
    documents = PyPDFDirectoryLoader(config.DATA_DIR).load()
    print(f"  Loaded {len(documents)} pages.")

    if documents:
        print("Step 2: Splitting into chunks ...")
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
        )
        chunks = splitter.split_documents(documents)
        # Stable key so the admin panel can list / delete these files later.
        for c in chunks:
            c.metadata["source_file"] = os.path.basename(c.metadata.get("source", "unknown.pdf"))
        print(f"  {len(chunks)} chunks.")

        print("Step 3: Embedding + storing PDF chunks ...")
        added = embed_with_retry(vector_db, chunks)
        print(f"  {added} chunks indexed.")
    else:
        print("  No PDFs found in ./data — skipping.")

    print("Step 4: Re-indexing structured locations ...")
    from locations import list_locations, location_to_document

    location_docs = [location_to_document(rec) for rec in list_locations()]
    if location_docs:
        embed_with_retry(vector_db, location_docs)
        print(f"  {len(location_docs)} location(s) indexed.")
    else:
        print("  No locations found — skipping.")

    print(f"DONE. Vector DB saved to {config.CHROMA_DIR}")


if __name__ == "__main__":
    build_database()
