"""
Single source of truth for every tunable literal in the app.

Nothing here does any work — it just defines values. Anything that was
previously a magic number or a string literal copy-pasted across
app.py / build_database.py / admin.py / locations.py should live here instead.
"""

import os

try:
    import streamlit as st
except ImportError:  # pragma: no cover - config must still import in plain scripts
    st = None


def get_secret(key, default=None):
    """
    Read a secret from st.secrets first (works in `streamlit run` AND in plain
    scripts, as long as .streamlit/secrets.toml exists), falling back to an
    environment variable, then to `default`.
    """
    if st is not None:
        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
    return os.environ.get(key, default)


# ── Storage paths ────────────────────────────────────────────────
DATA_DIR = "./data"
CHROMA_DIR = "./chroma_db"
LOCATIONS_DIR = "./locations"
ANNOUNCE_DIR = "./announcements"
QUERY_LOG_PATH = "./data/query_log.jsonl"

# ── Embedding backend ────────────────────────────────────────────
# "local"  -> sentence-transformers via langchain-huggingface. No API key,
#             no rate limit, works offline. DEFAULT.
# "gemini" -> Google's hosted embedding model. Needs GEMINI_API_KEY and is
#             subject to free-tier RPM/RPD quotas.
EMBEDDING_BACKEND = os.environ.get("EMBEDDING_BACKEND", "local").lower()

# Good general-purpose, fast, CPU-friendly local embedding model.
# Swap for "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" if a
# meaningful share of the indexed content is in Bahasa Melayu — it is larger
# and slower but understands both languages.
LOCAL_EMBEDDING_MODEL = os.environ.get(
    "LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"

# ── Generation (Gemini is kept for answer generation regardless of the
#    embedding backend chosen above) ──────────────────────────────
LLM_MODEL = "gemini-2.5-flash"
# Low temperature: this is a grounded, source-citing assistant, not a creative
# one. Keep it low so answers stay close to the retrieved context.
GENERATION_TEMPERATURE = 0.15
MAX_HISTORY_MESSAGES = 20

# ── Chunking / retrieval ─────────────────────────────────────────
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
RETRIEVER_K = 3

# ── Ingestion rate-limit protection (only exercised when
#    EMBEDDING_BACKEND == "gemini"; local embeddings need none of this) ──
EMBED_BATCH_SIZE = 15
EMBED_NORMAL_PAUSE = 1.5
EMBED_COOLDOWN_SECONDS = 45
