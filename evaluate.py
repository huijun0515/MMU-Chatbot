"""
Evaluation harness — serves FYP Objective 3 (measure retrieval accuracy and
answer relevancy vs. a keyword-search baseline).

For each question in eval/goldset.json:
  1. RAG retrieval  — the same hybrid retriever used in the live chat
     (location lookup + semantic Chroma search) returns top-k sources;
     hit = expected_source is among them.
  2. BM25 baseline  — a classic keyword/BM25 index built from every chunk
     currently in the vector store; same hit-rate check, no embeddings
     involved at all. This is the "vs. a keyword-search baseline" comparison.
  3. Answer relevancy (optional, needs GEMINI_API_KEY) — runs the full
     chat chain and checks whether any of the question's expected_keywords
     show up in the generated answer. A cheap, deterministic proxy for
     relevancy that needs no extra LLM-judge calls.

Usage:
    python evaluate.py
"""

import json
import sys

from rank_bm25 import BM25Okapi

from core import config
from core.vector_store import build_vector_db
from core.location_lookup import find_matching_location


def _tokenize(text):
    return text.lower().split()


def load_goldset(path="eval/goldset.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_bm25_corpus(vector_db):
    """Pull every chunk currently indexed and build a BM25 index over it."""
    data = vector_db._collection.get(include=["documents", "metadatas"])
    texts = data.get("documents", []) or []
    metadatas = data.get("metadatas", []) or []
    tokenized = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized) if tokenized else None
    sources = [md.get("source_file", "Unknown") for md in metadatas]
    return bm25, sources


def rag_retrieve_sources(vector_db, list_locations_fn, question, k):
    """Mirror core/rag_chain.py's hybrid retriever (semantic + exact location match)."""
    docs = vector_db.as_retriever(search_kwargs={"k": k}).invoke(question)
    match = find_matching_location(question, list_locations_fn())
    sources = []
    if match:
        sources.append("Campus Directory")
    sources += [d.metadata.get("source_file", "Unknown") for d in docs]
    return sources[:k]


def bm25_retrieve_sources(bm25, sources, question, k):
    if bm25 is None:
        return []
    scores = bm25.get_scores(_tokenize(question))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [sources[i] for i in ranked]


def run_answer_relevancy(questions):
    """Optional: generate real answers and keyword-match them. Skipped
    gracefully if no Gemini API key is configured."""
    if not config.get_secret("GEMINI_API_KEY"):
        print("\n(No GEMINI_API_KEY configured — skipping answer-relevancy pass.)")
        return None

    from core.rag_chain import build_chat_chain
    from locations import list_locations

    chain = build_chat_chain(build_vector_db(), list_locations)
    results = []
    for item in questions:
        response = chain.invoke({"input": item["question"], "chat_history": []})
        answer = response["answer"].lower()
        keywords = [k.lower() for k in item.get("expected_keywords", [])]
        hit = any(k in answer for k in keywords) if keywords else None
        results.append(hit)
    return results


def main():
    goldset = load_goldset()
    k = config.RETRIEVER_K

    print(f"Loaded {len(goldset)} gold questions. Embedding backend: {config.EMBEDDING_BACKEND}\n")

    vector_db = build_vector_db()
    from locations import list_locations

    bm25, bm25_sources = build_bm25_corpus(vector_db)

    rows = []
    rag_hits = 0
    bm25_hits = 0
    for item in goldset:
        q, expected = item["question"], item["expected_source"]

        rag_sources = rag_retrieve_sources(vector_db, list_locations, q, k)
        rag_hit = expected in rag_sources
        rag_hits += rag_hit

        bm_sources = bm25_retrieve_sources(bm25, bm25_sources, q, k)
        bm_hit = expected in bm_sources
        bm25_hits += bm_hit

        rows.append({"question": q, "expected": expected, "rag_hit": rag_hit, "bm25_hit": bm_hit})

    relevancy = run_answer_relevancy(goldset)

    total = len(goldset)
    print(f"{'Question':<60} {'RAG':<6} {'BM25':<6}")
    print("-" * 74)
    for i, row in enumerate(rows):
        q_short = (row["question"][:57] + "...") if len(row["question"]) > 57 else row["question"]
        rel = ""
        if relevancy is not None:
            rel = "  relevancy=" + ("hit" if relevancy[i] else "miss")
        print(f"{q_short:<60} {'hit' if row['rag_hit'] else 'miss':<6} {'hit' if row['bm25_hit'] else 'miss':<6}{rel}")

    print("-" * 74)
    print(f"RAG hit-rate@{k}:  {rag_hits}/{total} ({100 * rag_hits / total:.0f}%)")
    print(f"BM25 hit-rate@{k}: {bm25_hits}/{total} ({100 * bm25_hits / total:.0f}%)")
    if relevancy is not None:
        rel_hits = sum(1 for r in relevancy if r)
        print(f"Answer relevancy:  {rel_hits}/{total} ({100 * rel_hits / total:.0f}%)")


if __name__ == "__main__":
    sys.exit(main())
