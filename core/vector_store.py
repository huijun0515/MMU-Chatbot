"""
Shared vector-store access for the whole app.

The chatbot (views/assistant_view.py), the admin panel (admin.py), the
location directory (locations.py), build_database.py and evaluate.py all
import from here, so they use the SAME embedding function and the SAME
Chroma collection. That is what lets a freshly uploaded PDF show up in the
assistant's answers without rebuilding anything.

Two layers on purpose:
  build_vector_db() / build_embeddings()  -> plain functions, no Streamlit
                                              dependency. Safe to call from
                                              build_database.py / evaluate.py.
  get_vector_db()   / get_embeddings()    -> @st.cache_resource wrappers used
                                              ONLY inside the running app, so
                                              every page gets the exact same
                                              object.
"""

import time

import streamlit as st

from core import config
from core.logging_setup import logger

try:
    from langchain_chroma import Chroma
except ImportError as exc:  # pragma: no cover - this package is a hard pin
    raise ImportError(
        "langchain-chroma is required. Install it with `pip install langchain-chroma`."
    ) from exc


def build_embeddings():
    """Construct the embedding function for the configured backend. No caching."""
    if config.EMBEDDING_BACKEND == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        api_key = config.get_secret("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "EMBEDDING_BACKEND=gemini but GEMINI_API_KEY is not set in "
                "st.secrets or the environment."
            )
        return GoogleGenerativeAIEmbeddings(
            model=config.GEMINI_EMBEDDING_MODEL, google_api_key=api_key
        )

    # Default: local, offline, free, deterministic.
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=config.LOCAL_EMBEDDING_MODEL)


def build_vector_db():
    """Construct a Chroma handle pointing at CHROMA_DIR. No caching."""
    return Chroma(persist_directory=config.CHROMA_DIR, embedding_function=build_embeddings())


def embed_with_retry(vector_db, docs, batch_size=None, status=None, progress_cb=None):
    """
    Add documents to the vector DB in batches, retrying on Gemini rate-limit
    errors. With the local embedding backend this just runs straight through
    with no sleeps at all (no API, no quota).

    `status` is an optional Streamlit element (e.g. st.empty()) to post
    progress/cooldown messages to; `progress_cb(fraction_done)` is an optional
    callback (e.g. to drive a st.progress bar). Both are safe to omit for
    script/CLI use.
    """
    batch_size = batch_size or config.EMBED_BATCH_SIZE
    is_local = config.EMBEDDING_BACKEND != "gemini"
    added = 0
    total = len(docs)
    for i in range(0, total, batch_size):
        batch = docs[i : i + batch_size]
        while True:
            try:
                vector_db.add_documents(batch)
                break
            except Exception as e:
                msg = str(e).lower()
                if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
                    logger.warning("Embedding rate limit hit — cooling down %ss", config.EMBED_COOLDOWN_SECONDS)
                    if status is not None:
                        status.warning(f"🚦 Rate limit hit — cooling down {config.EMBED_COOLDOWN_SECONDS}s…")
                    time.sleep(config.EMBED_COOLDOWN_SECONDS)
                else:
                    raise
        added += len(batch)
        if progress_cb is not None:
            progress_cb(min(added / total, 1.0))
        if not is_local:
            time.sleep(config.EMBED_NORMAL_PAUSE)
    return added


@st.cache_resource
def get_embeddings():
    """One embeddings client, reused everywhere inside the running app."""
    return build_embeddings()


@st.cache_resource
def get_vector_db():
    """
    One shared Chroma handle pointing at ./chroma_db.

    Because this is @st.cache_resource, every part of the app gets the exact
    same object. When admin.py adds documents to it, the assistant's retriever
    (built on this same object) sees them immediately after st.cache_resource.clear().
    """
    return Chroma(persist_directory=config.CHROMA_DIR, embedding_function=get_embeddings())
