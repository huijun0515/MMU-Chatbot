"""
Retrieval: query (str) -> list[Document].

  1. Candidates come from semantic search (RETRIEVAL_MODE="vector") or from
     semantic search + BM25 keyword search fused with reciprocal rank fusion
     (RETRIEVAL_MODE="hybrid").
  2. Relevance gate (config.MIN_RELEVANCE_SCORE), so off-topic text returns
     nothing:
       vector  every chunk must score above the threshold.
       hybrid  a query-level gate: the query's BEST vector score must reach
               the threshold, OR the best BM25 chunk must contain most of the
               query's content words. A per-chunk vector gate would defeat the
               point of BM25, whose whole value is rescuing chunks the embedding
               model scores poorly; and raw BM25 scores are unnormalised, so
               they can't be thresholded — term coverage can.
  3. An exact location match (core/location_lookup.py) is pinned to the front.
"""

import re
import warnings

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from core import config
from core.location_lookup import find_matching_location

# similarity_search_with_relevance_scores warns (and prints every retrieved
# document) whenever a score is negative, which is normal for off-topic text
# with this embedding model. We handle low scores ourselves via the threshold.
warnings.filterwarnings("ignore", message="Relevance scores must be between 0 and 1")


def _tokens(text):
    return [t for t in re.findall(r"\w+", text.lower()) if t not in config.BM25_STOPWORDS]


class Bm25Index:
    """BM25 over a snapshot of every chunk in the vector store. The snapshot is
    taken when the Retriever is built; the app rebuilds it whenever the admin
    panel changes the store (st.cache_resource.clear())."""

    def __init__(self, vector_db):
        data = vector_db._collection.get(include=["documents", "metadatas"])
        self.ids = data["ids"]
        self.texts = data["documents"]
        self.metadatas = data["metadatas"]
        token_lists = [_tokens(t) for t in self.texts]
        self._token_sets = [set(t) for t in token_lists]
        self._index = BM25Okapi(token_lists) if self.texts else None

    def best_coverage(self, query):
        """(share of the query's distinct content words found in the single
        best-matching chunk, number of content words in the query)."""
        words = list(dict.fromkeys(_tokens(query)))
        if self._index is None or not words:
            return 0.0, len(words)
        scores = self._index.get_scores(words)
        best = max(range(len(scores)), key=scores.__getitem__)
        if scores[best] <= 0:
            return 0.0, len(words)
        return sum(w in self._token_sets[best] for w in words) / len(words), len(words)

    def search(self, query, n):
        """Best-first [(Document, score)], only chunks sharing a term with the query."""
        tokens = _tokens(query)
        if self._index is None or not tokens:
            return []
        scores = self._index.get_scores(tokens)
        best = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:n]
        return [
            (Document(id=self.ids[i], page_content=self.texts[i], metadata=dict(self.metadatas[i] or {})), scores[i])
            for i in best
            if scores[i] > 0
        ]


def _fuse_interleave(vec_docs, bm_docs):
    """Round-robin: vector #1, BM25 #1, vector #2, BM25 #2 ... skipping duplicates.
    Guarantees each retriever's most confident picks a seat. Scored best on the
    gold sets at small k, where RRF's summing favours mid-ranked chunks both
    lists agree on over a single retriever's top pick (e.g. BM25's #2 for a
    lecturer's name, which the embedding model can't place at all)."""
    seen, merged = set(), []
    for i in range(max(len(vec_docs), len(bm_docs))):
        for ranking in (vec_docs, bm_docs):
            if i < len(ranking) and ranking[i].id not in seen:
                seen.add(ranking[i].id)
                merged.append(ranking[i])
    return merged


def _fuse_rrf(vec_docs, bm_docs):
    """Reciprocal rank fusion: score = sum over lists of 1 / (RRF_K + rank)."""
    score, by_id = {}, {}
    for ranking in (vec_docs, bm_docs):
        for rank, d in enumerate(ranking, 1):
            score[d.id] = score.get(d.id, 0.0) + 1.0 / (config.RRF_K + rank)
            by_id.setdefault(d.id, d)
    return [by_id[i] for i in sorted(score, key=score.__getitem__, reverse=True)]


def _cap_locations(docs):
    """Keep at most config.MAX_LOCATION_CHUNKS campus-directory chunks. With
    ~150 location records indexed, they would otherwise crowd the handbook and
    facility chunks out of the top-k for any query that mentions a building."""
    kept, n = [], 0
    for d in docs:
        if d.metadata.get("type") == "location":
            n += 1
            if n > config.MAX_LOCATION_CHUNKS:
                continue
        kept.append(d)
    return kept


def _location_record_to_document(rec):
    from locations import location_to_document  # local import avoids a cycle at module load

    return location_to_document(rec)


class Retriever:
    def __init__(self, vector_db, list_locations_fn):
        self.vector_db = vector_db
        self.list_locations_fn = list_locations_fn
        self._bm25 = None

    def _bm25_index(self):
        if self._bm25 is None:
            self._bm25 = Bm25Index(self.vector_db)
        return self._bm25

    def _vector(self, query):
        docs = []
        for doc, score in self.vector_db.similarity_search_with_relevance_scores(
            query, k=config.RETRIEVER_K
        ):
            if config.GROUNDING_GATE_ENABLED and score < config.MIN_RELEVANCE_SCORE:
                continue
            doc.metadata["relevance_score"] = round(score, 3)
            docs.append(doc)
        return docs

    def _passes_hybrid_gate(self, query, vec):
        if not config.GROUNDING_GATE_ENABLED:
            return True
        if vec and vec[0][1] >= config.MIN_RELEVANCE_SCORE:
            return True
        coverage, n_words = self._bm25_index().best_coverage(query)
        return n_words >= config.BM25_GATE_MIN_TERMS and coverage >= config.BM25_GATE_MIN_COVERAGE

    def _hybrid(self, query):
        vec = self.vector_db.similarity_search_with_relevance_scores(query, k=config.HYBRID_POOL)
        if not self._passes_hybrid_gate(query, vec):
            return []

        # Capped per ranking, BEFORE merging: otherwise location records take
        # BM25's trusted top-N seats and push the real answer chunk out.
        vec_docs = _cap_locations([d for d, _ in vec])
        bm_docs = _cap_locations([d for d, _ in self._bm25_index().search(query, config.HYBRID_POOL)])
        merge = _fuse_rrf if config.HYBRID_FUSION == "rrf" else _fuse_interleave

        vec_scores = {d.id: s for d, s in vec}
        merged = merge(vec_docs, bm_docs)
        if config.GROUNDING_GATE_ENABLED:
            # Per-chunk gate: a chunk must clear the relevance threshold unless
            # BM25 itself vouches for it (its top-N). Without this, the tail of
            # the vector list pads the result with off-topic chunks.
            trusted = {d.id for d in bm_docs[: config.HYBRID_BM25_TRUSTED]}
            merged = [
                d for d in merged
                if vec_scores.get(d.id, float("-inf")) >= config.MIN_RELEVANCE_SCORE or d.id in trusted
            ]
        docs = _cap_locations(merged)[: config.RETRIEVER_K]
        for d in docs:  # informational only; None = found by BM25 alone
            s = vec_scores.get(d.id)
            d.metadata["relevance_score"] = None if s is None else round(s, 3)
        return docs

    def retrieve(self, query):
        docs = self._hybrid(query) if config.RETRIEVAL_MODE == "hybrid" else self._vector(query)

        match = find_matching_location(query, self.list_locations_fn())
        if match:
            loc_doc = _location_record_to_document(match)
            loc_doc.metadata["relevance_score"] = 1.0
            docs = _cap_locations([loc_doc] + [d for d in docs if d.metadata.get("loc_id") != match.get("id")])

        # Normalize "page" for the document prompt — PDF loaders set an int,
        # location/other docs may not set it at all.
        for d in docs:
            d.metadata.setdefault("page", "N/A")
            if isinstance(d.metadata.get("page"), int):
                d.metadata["page"] += 1  # 1-indexed for humans
        return docs[: config.RETRIEVER_K]
