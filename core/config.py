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
LOCATIONS_XLSX = "./data/Location File.xlsx"
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
RETRIEVER_K = 5

# "vector": semantic search only.
# "hybrid": semantic search + BM25 keyword search, merged. The two find different
#           things — vectors handle paraphrase, BM25 handles exact terms, numbers
#           and names that embeddings blur. Measured against vector-only on
#           eval/goldset*.json; see README "Retrieval".
RETRIEVAL_MODE = "hybrid"
HYBRID_FUSION = "interleave"  # or "rrf" (reciprocal rank fusion)
HYBRID_POOL = 20   # candidates taken from EACH retriever before merging
RRF_K = 60         # RRF damping constant (only used when HYBRID_FUSION = "rrf")
# BM25's top-N results are kept even when their vector score is under
# MIN_RELEVANCE_SCORE; a chunk that only vector search found must still clear it.
# (N=1 lost recall; N=2..5 kept it, and 2 left the fewest off-topic sources.)
HYBRID_BM25_TRUSTED = 2
MAX_LOCATION_CHUNKS = 1  # campus-directory chunks allowed in the top-k (incl. an exact match)
# Hybrid gate, second way through: a query the embedding model finds unimpressive
# (e.g. "When is Deepavali in 2026?" scores 0.08) is still in-domain if the
# best-matching chunk contains most of its content words. Off-topic text doesn't
# — and one-word queries never qualify, as a single common word matches anything.
BM25_GATE_MIN_COVERAGE = 0.8
BM25_GATE_MIN_TERMS = 2
BM25_STOPWORDS = frozenset(
    "the a an is are was were be do does did what when where which who whom how to of in on at "
    "for and or i my me can am it there by with from this that as if so than then also any".split()
)

# ── When are "View Sources" shown? Two gates, both must let a message through ──
# Layer 1 — intent: obvious social messages (greeting / thanks / goodbye / "who
# are you") skip retrieval entirely, are answered directly by the LLM, and show
# no sources. Matching is a FULL match on the normalized message (lowercased,
# punctuation stripped), so "hi, where is the library?" is still a knowledge
# question. Anything that doesn't match falls through to layer 2, so a miss here
# is harmless — it just costs one retrieval.
INTENT_GATE_ENABLED = True
CHITCHAT_MAX_CHARS = 60
CHITCHAT_PATTERNS = [
    # greetings
    r"(?:hi+|hello+|hey+|hiya|howdy|yo|greetings|hai|helo|assalamualaikum)(?: (?:there|everyone|all|bot|assistant|mmu))*",
    r"good (?:morning|afternoon|evening|night|day)",
    r"selamat (?:pagi|petang|malam|tengahari)",
    # how-are-you / small talk
    r"how (?:are|r) (?:you|u)(?: doing)?(?: today)?",
    r"how(?: is| s)? it going",
    r"(?:whats|what is) up",
    r"sup",
    r"apa khabar",
    # thanks
    r"(?:thanks+|thank you|thank u|thx|ty|tq|cheers|much appreciated|many thanks|terima kasih)(?: (?:so|very|a) (?:much|lot))?(?: (?:bot|assistant))?",
    # acknowledgements
    r"(?:ok+|okay|okey|cool|nice|great|awesome|alright|got it|i see|noted|sure|fine)",
    # farewells
    r"(?:bye+|goodbye|good bye|see you|see ya|cya|take care|goodnight)(?: (?:later|soon))?",
    # identity / capability
    r"(?:who|what) are you",
    r"what(?: is| s)? your name",
    r"who (?:made|created|built|developed) you",
    r"are you (?:a |an )?(?:bot|robot|ai|human|real)",
    r"what (?:can you do|do you do)",
    # Chinese
    r"(?:你好|您好|嗨|哈喽|哈啰|早安|早上好|下午好|晚上好|晚安|谢谢|谢谢你|谢谢您|多谢|感谢|再见|拜拜|你是谁|你叫什么名字|你叫什么|你好吗|你怎么样|最近怎么样|你能做什么|你会什么)(?:啊|呀|吗|啦|哦|喔)?",
]

# Layer 2 — grounding: for everything else we still retrieve, but a chunk only
# counts (is shown to the model AND listed as a source) if its relevance score
# (1 - L2distance/sqrt(2), range roughly -0.4..1) reaches this threshold.
# Measured on this index with all-MiniLM-L6-v2: real questions score 0.22-0.55 on
# their best chunk; greetings and off-topic text score <= 0.13. RE-MEASURE and
# retune if you change the embedding model — scales differ per model.
GROUNDING_GATE_ENABLED = True
MIN_RELEVANCE_SCORE = 0.15
# If the model itself says it found nothing (the fallback line in the answer
# prompt), no sources are shown even when some chunk cleared the threshold.
NO_ANSWER_MARKER = "couldn't find that specific information"

# ── Ingestion rate-limit protection (only exercised when
#    EMBEDDING_BACKEND == "gemini"; local embeddings need none of this) ──
EMBED_BATCH_SIZE = 15
EMBED_NORMAL_PAUSE = 1.5
EMBED_COOLDOWN_SECONDS = 45
