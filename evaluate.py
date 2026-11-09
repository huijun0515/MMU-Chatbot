"""
Evaluation harness — serves FYP Objective 3 (retrieval accuracy and answer
relevancy vs. a keyword-search baseline).

Every question in eval/goldset.json is one of two kinds:

  answerable   the answer is in ./data. Two retrieval checks on the top-k chunks:
                 source-hit    a chunk from the expected FILE was retrieved
                               (lenient — one handbook chunk "hits" for any
                               handbook question, so this overstates quality)
                 evidence-hit  a retrieved chunk from the expected file actually
                               CONTAINS the evidence text (strict — this is the
                               honest retrieval metric)
  no_answer    the answer is NOT in ./data. The correct behaviour is no context,
               no sources and a "couldn't find" reply.

The BM25 baseline is a plain keyword index over the same chunks (no embeddings,
no gating), scored the same way.

Usage:
    python evaluate.py                    # retrieval metrics only: local, fast, no API
    python evaluate.py --with-llm         # + generated-answer checks (needs GEMINI_API_KEY)
    python evaluate.py --validate         # check the gold set against the live index
    python evaluate.py --k 5 --tag k5     # try another top-k; results saved as eval/results/k5.json
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

from rank_bm25 import BM25Okapi

from core import config
from core.vector_store import build_vector_db
from core.retrieval import Retriever

GOLDSET_PATH = "eval/goldset.json"
RESULTS_DIR = "eval/results"
LLM_CALL_SPACING_SECONDS = 7  # stay under the free tier's requests-per-minute limit


def norm_text(s):
    """Lowercase, straighten quotes/dashes, collapse whitespace — applied to both
    the evidence strings and the chunk text before comparing."""
    s = s.lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("−", "-")):
        s = s.replace(a, b)
    return " ".join(s.split())


def tokenize(s):
    return re.findall(r"\w+", s.lower())


def load_goldset(path=GOLDSET_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_corpus(vector_db):
    """Every chunk currently indexed: [{"text", "source"}]."""
    data = vector_db._collection.get(include=["documents", "metadatas"])
    return [
        {"text": t, "source": (m or {}).get("source_file", "Unknown")}
        for t, m in zip(data["documents"], data["metadatas"])
    ]


# ── gold-set validation ────────────────────────────────────────────────────
def validate(goldset, corpus):
    """Prove the gold set is sound against the live index: every answerable
    question's evidence really occurs in a chunk of its expected file, and every
    no_answer question's key terms really occur nowhere. Returns #problems."""
    by_source = defaultdict(list)
    for c in corpus:
        by_source[c["source"]].append(norm_text(c["text"]))
    all_chunks = [t for chunks in by_source.values() for t in chunks]

    problems = 0
    for item in goldset:
        if item["kind"] == "answerable":
            chunks = by_source.get(item["expected_source"])
            if not chunks:
                print(f"FAIL {item['id']}: expected_source {item['expected_source']!r} is not in the index")
                problems += 1
                continue
            for ev in item["evidence"]:
                n = sum(norm_text(ev) in t for t in chunks)
                if n == 0:
                    print(f"FAIL {item['id']}: evidence {ev!r} not found in any chunk of {item['expected_source']}")
                    problems += 1
                else:
                    print(f"ok   {item['id']}: evidence in {n} chunk(s) of {item['expected_source']}")
        else:
            for pat in item.get("absent_terms", []):
                n = sum(bool(re.search(pat, t)) for t in all_chunks)
                if n:
                    print(f"FAIL {item['id']}: term {pat!r} DOES occur in {n} chunk(s) — question may be answerable")
                    problems += 1
                else:
                    print(f"ok   {item['id']}: {pat!r} occurs in no chunk")
    print(f"\n{problems} problem(s) across {len(goldset)} questions")
    return problems


# ── retrieval scoring ──────────────────────────────────────────────────────
def score_chunks(item, chunks):
    """chunks: [{"text", "source"}] actually retrieved. Returns (source_hit, evidence_hit)."""
    expected = item["expected_source"]
    from_expected = [c for c in chunks if c["source"] == expected]
    evidence = [norm_text(e) for e in item["evidence"]]
    ev_hit = any(e in norm_text(c["text"]) for c in from_expected for e in evidence)
    return bool(from_expected), ev_hit


def docs_to_chunks(docs):
    return [{"text": d.page_content, "source": d.metadata.get("source_file", "Unknown")} for d in docs]


class Bm25Baseline:
    """Plain BM25 over every chunk — the keyword-search baseline."""

    def __init__(self, corpus):
        self.corpus = corpus
        self.index = BM25Okapi([tokenize(c["text"]) for c in corpus])

    def top(self, question, k):
        scores = self.index.get_scores(tokenize(question))
        best = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:k]
        return [self.corpus[i] for i in best]


# ── optional LLM pass ──────────────────────────────────────────────────────
def _ask_with_retry(pipeline, question):
    from core.rag_chain import ask

    for attempt in range(4):
        try:
            return ask(pipeline, question, [], log=False)
        except Exception as e:  # noqa: BLE001 - only rate limits are retried
            msg = str(e).lower()
            if attempt < 3 and ("429" in msg or "quota" in msg or "resource_exhausted" in msg):
                print(f"   (rate limited, waiting {config.EMBED_COOLDOWN_SECONDS}s)")
                time.sleep(config.EMBED_COOLDOWN_SECONDS)
            else:
                raise


def llm_pass(goldset, vector_db):
    from locations import list_locations
    from core.rag_chain import build_chat_pipeline

    pipeline = build_chat_pipeline(vector_db, list_locations)
    results = {}
    for i, item in enumerate(goldset):
        if i:
            time.sleep(LLM_CALL_SPACING_SECONDS)
        r = _ask_with_retry(pipeline, item["question"])
        answer = r["answer"].lower()
        entry = {"grounded": r["grounded"], "sources": r["sources"], "answer": r["answer"]}
        if item["kind"] == "answerable":
            kws = [k.lower() for k in item.get("expected_keywords", [])]
            entry["relevant"] = any(k in answer for k in kws) if kws else None
        else:
            entry["correct_no_answer"] = (not r["grounded"]) and r["sources"] == []
        results[item["id"]] = entry
        print(f"   llm {item['id']} done")
    return results


# ── reporting ──────────────────────────────────────────────────────────────
def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goldset", default=GOLDSET_PATH)
    ap.add_argument("--k", type=int, help="override config.RETRIEVER_K for this run")
    ap.add_argument("--mode", help="override config.RETRIEVAL_MODE for this run (vector|hybrid)")
    ap.add_argument("--fusion", help="override config.HYBRID_FUSION for this run (interleave|rrf)")
    ap.add_argument("--with-llm", action="store_true", help="also generate answers (calls Gemini)")
    ap.add_argument("--validate", action="store_true", help="check the gold set against the index and exit")
    ap.add_argument("--tag", default=None, help="save results to eval/results/<tag>.json")
    args = ap.parse_args()

    if args.k:
        config.RETRIEVER_K = args.k
    if args.mode:
        config.RETRIEVAL_MODE = args.mode
    if args.fusion:
        config.HYBRID_FUSION = args.fusion
    k = config.RETRIEVER_K

    goldset = load_goldset(args.goldset)
    vector_db = build_vector_db()
    corpus = load_corpus(vector_db)

    if args.validate:
        return 1 if validate(goldset, corpus) else 0

    from locations import list_locations

    mode = config.RETRIEVAL_MODE + (f"/{config.HYBRID_FUSION}" if config.RETRIEVAL_MODE == "hybrid" else "")
    print(f"{len(goldset)} questions | backend={config.EMBEDDING_BACKEND} | retrieval={mode} | "
          f"k={k} | min_relevance={config.MIN_RELEVANCE_SCORE} | {len(corpus)} chunks indexed\n")

    bm25 = Bm25Baseline(corpus)
    retriever = Retriever(vector_db, list_locations)
    rows = []
    for item in goldset:
        q = item["question"]
        rag_chunks = docs_to_chunks(retriever.retrieve(q))
        row = {"id": item["id"], "kind": item["kind"], "category": item["category"], "question": q,
               "expected_source": item.get("expected_source"), "rag_n_chunks": len(rag_chunks),
               "rag_sources": sorted({c["source"] for c in rag_chunks})}
        if item["kind"] == "answerable":
            row["rag_src"], row["rag_ev"] = score_chunks(item, rag_chunks)
            row["bm25_src"], row["bm25_ev"] = score_chunks(item, bm25.top(q, k))
        rows.append(row)

    llm = llm_pass(goldset, vector_db) if args.with_llm else None

    yn = lambda b: "hit" if b else "MISS"
    print(f"{'id':<4} {'category':<11} {'question':<46} {'RAG src':<8} {'RAG ev':<7} {'BM25 src':<9} {'BM25 ev':<8}"
          + ("  LLM" if llm else ""))
    print("-" * (98 + (6 if llm else 0)))
    for r in rows:
        q = (r["question"][:43] + "...") if len(r["question"]) > 46 else r["question"]
        if r["kind"] == "answerable":
            cells = f"{yn(r['rag_src']):<8} {yn(r['rag_ev']):<7} {yn(r['bm25_src']):<9} {yn(r['bm25_ev']):<8}"
        else:
            cells = f"{str(r['rag_n_chunks']) + ' chunks':<8} {'(none ok)' if r['rag_n_chunks'] == 0 else 'LEAK':<7} {'-':<9} {'-':<8}"
        extra = ""
        if llm:
            e = llm[r["id"]]
            ok = e.get("relevant") if r["kind"] == "answerable" else e.get("correct_no_answer")
            extra = "  " + ("ok" if ok else "MISS")
        print(f"{r['id']:<4} {r['category']:<11} {q:<46} {cells}{extra}")

    ans = [r for r in rows if r["kind"] == "answerable"]
    noans = [r for r in rows if r["kind"] == "no_answer"]
    n = len(ans)
    metrics = {
        "rag_source_hit": sum(r["rag_src"] for r in ans),
        "rag_evidence_hit": sum(r["rag_ev"] for r in ans),
        "bm25_source_hit": sum(r["bm25_src"] for r in ans),
        "bm25_evidence_hit": sum(r["bm25_ev"] for r in ans),
        "avg_sources_shown": round(sum(len(r["rag_sources"]) for r in ans) / n, 2) if n else 0,
        "only_expected_source": sum(r["rag_sources"] == [r["expected_source"]] for r in ans),
        "n_answerable": n,
        "no_answer_retrieval_clean": sum(r["rag_n_chunks"] == 0 for r in noans),
        "n_no_answer": len(noans),
    }
    if llm:
        metrics["answer_relevant"] = sum(bool(llm[r["id"]]["relevant"]) for r in ans)
        metrics["no_answer_correct_e2e"] = sum(bool(llm[r["id"]]["correct_no_answer"]) for r in noans)

    print("\n" + "=" * 60)
    print(f"ANSWERABLE (n={n}), top-{k}")
    print(f"  RAG  source-hit   {pct(metrics['rag_source_hit'], n)}")
    print(f"  RAG  evidence-hit {pct(metrics['rag_evidence_hit'], n)}   <- honest retrieval metric")
    print(f"  BM25 source-hit   {pct(metrics['bm25_source_hit'], n)}")
    print(f"  BM25 evidence-hit {pct(metrics['bm25_evidence_hit'], n)}")
    print(f"  Sources listed per answer {metrics['avg_sources_shown']:.2f} avg; "
          f"only the expected file: {pct(metrics['only_expected_source'], n)}")
    if llm:
        print(f"  Answer relevancy  {pct(metrics['answer_relevant'], n)}   (keyword proxy)")
    print(f"NO-ANSWER (n={len(noans)})")
    print(f"  Retrieval returned nothing   {pct(metrics['no_answer_retrieval_clean'], len(noans))}")
    if llm:
        print(f"  Correct end-to-end (no answer, no sources)  {pct(metrics['no_answer_correct_e2e'], len(noans))}")

    by_cat = defaultdict(lambda: [0, 0, 0])
    for r in ans:
        by_cat[r["category"]][0] += 1
        by_cat[r["category"]][1] += r["rag_ev"]
        by_cat[r["category"]][2] += r["bm25_ev"]
    print("\nEvidence-hit by category (RAG / BM25):")
    for cat, (tot, rag, bm) in sorted(by_cat.items()):
        print(f"  {cat:<12} n={tot:<3} RAG {rag}/{tot}   BM25 {bm}/{tot}")

    if args.tag:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        out = {"tag": args.tag, "k": k, "retrieval": mode, "embedding": config.EMBEDDING_BACKEND,
               "min_relevance_score": config.MIN_RELEVANCE_SCORE, "metrics": metrics,
               "per_question": rows, "llm": llm}
        path = os.path.join(RESULTS_DIR, f"{args.tag}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
