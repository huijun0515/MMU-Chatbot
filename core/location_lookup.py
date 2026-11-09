"""
Exact/alias/room-code lookup over the structured location records.

Why this exists: short alphanumeric codes like "MNCR1001" carry almost no
semantic meaning, so embedding similarity is unreliable for them. A plain
string match against the structured records (the source of truth) is cheap,
deterministic, and never wrong when a code actually exists.

Matching is on TOKEN boundaries: a candidate (id, name, alias or room code)
matches only if its tokens appear as a contiguous run of whole tokens in the
query. "class schedule" therefore does NOT match "SSC", and "Where is
BR 1024" still matches "BR1024". Identifiers shorter than 3 characters are
ignored — "IO", "ML" would fire on ordinary words.

This runs BEFORE semantic retrieval (core/retrieval.py); semantic search still
handles free-text navigation questions ("where do I pay my fees").
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MAX_QUERY_RUN = 6  # longest run of query tokens joined when comparing to a candidate


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower())


def _query_runs(tokens):
    """Every contiguous run of up to _MAX_QUERY_RUN tokens, joined without spaces."""
    runs = set()
    for i in range(len(tokens)):
        joined = ""
        for tok in tokens[i : i + _MAX_QUERY_RUN]:
            joined += tok
            runs.add(joined)
    return runs


def find_matching_location(query, locations):
    """Return the best-matching location record for `query`, or None.
    Longer identifying strings win, so a specific name beats a generic alias."""
    if not query or not locations:
        return None

    runs = _query_runs(_tokens(query))
    best, best_len = None, 0

    for rec in locations:
        candidates = [rec.get("id", ""), rec.get("code", ""), rec.get("name", "")] + list(rec.get("aliases", []) or [])
        for cand in candidates:
            norm = "".join(_tokens(cand))
            if len(norm) < 3:
                continue
            if norm in runs and len(norm) > best_len:
                best, best_len = rec, len(norm)

    return best
