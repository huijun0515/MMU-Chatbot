"""
Language handling for a knowledge base that is written in English.

detect(text)        -> "en" | "ms" | "zh"  (cheap, no API call)
to_english(llm, q)  -> English search query for a Malay/Chinese question, so the
                       embedding model and BM25 (both English-only) can find the
                       right passages. Room codes and names are kept verbatim.
The ANSWER is still written in the user's language — that is handled by the
answer prompt, not here.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage

_CJK = re.compile(r"[一-鿿㐀-䶿]")
# Common Malay function words / question words. A hit on any two is enough —
# English questions essentially never contain them.
_MALAY = frozenset("""
di mana dimana bila berapa bagaimana macam mana apakah siapa kenapa mengapa adakah boleh
saya awak anda kami kita dan atau yang untuk dengan dari pada ke tidak ada ialah adalah
pukul hari minggu bulan tahun bila bilakah tempat pejabat perpustakaan makmal bilik dewan
yuran biasiswa peperiksaan kursus subjek pelajar universiti sila tolong nak hendak mahu
""".split())

_TRANSLATE_SYSTEM = (
    "Translate the user's question into a short English search query for a university handbook search. "
    "Keep room codes, building names, acronyms and proper names exactly as written. "
    "Output only the English question, nothing else."
)


def detect(text):
    if _CJK.search(text or ""):
        return "zh"
    words = re.findall(r"[a-zA-Z]+", (text or "").lower())
    hits = sum(w in _MALAY for w in words)
    if hits >= 2 or (hits == 1 and len(words) <= 3):
        return "ms"
    return "en"


def to_english(llm, question):
    """One short LLM call; falls back to the original text on any failure."""
    try:
        out = llm.invoke([SystemMessage(content=_TRANSLATE_SYSTEM), HumanMessage(content=question)])
        text = (out.text or "").strip().splitlines()[0].strip()
        return text or question
    except Exception:
        return question


def expand(query):
    """Append document-side synonyms (config.QUERY_EXPANSIONS) for words found in the query."""
    from core import config

    words = re.findall(r"[a-z]+", query.lower())
    extra = [config.QUERY_EXPANSIONS[w] for w in dict.fromkeys(words) if w in config.QUERY_EXPANSIONS]
    return f"{query} {' '.join(extra)}" if extra else query


def query_for_retrieval(question, llm=None):
    """What to search with: the question (English) or its English translation, plus synonyms."""
    if detect(question) != "en" and llm is not None:
        question = to_english(llm, question)
    return expand(question)
