"""
Exact/alias/room-code lookup over the structured location records.

Why this exists: short alphanumeric codes like "BR1024" carry almost no
semantic meaning, so embedding similarity (local or Gemini, doesn't matter)
is unreliable for them — "where is BR1024" can retrieve an unrelated chunk
just because some other sentence happens to be closer in vector space. A
plain string match against the structured records (which ARE the source of
truth) is cheap, deterministic, and never wrong when a code actually exists.

This runs BEFORE semantic retrieval in core/rag_chain.py; semantic search
still runs for the general, free-text navigation questions this can't catch
("where can I get food near the library").
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize(text):
    return "".join(_TOKEN_RE.findall((text or "").lower()))


def find_matching_location(query, locations):
    """
    Return the best-matching location record for `query`, or None.

    Matching strategy, in order:
      1. Exact match: a normalized token in the query equals the normalized
         id, name, or an alias of a location (handles "BR1024", "br 1024",
         "Finance Office" etc. regardless of spacing/case/punctuation).
      2. Substring match: a location's normalized name/alias appears inside
         the normalized query (handles "where is the library").
    Locations with longer identifying strings win ties, so a more specific
    alias is preferred over a short generic one.
    """
    if not query or not locations:
        return None

    norm_query = _normalize(query)
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))

    best = None
    best_len = 0

    for rec in locations:
        candidates = [rec.get("id", ""), rec.get("name", "")] + list(rec.get("aliases", []) or [])
        for cand in candidates:
            norm_cand = _normalize(cand)
            if not norm_cand:
                continue
            if norm_cand in query_tokens or norm_cand in norm_query:
                if len(norm_cand) > best_len:
                    best = rec
                    best_len = len(norm_cand)

    return best
