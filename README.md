# MMU Intelligent Campus Assistant

A Streamlit RAG chatbot for Multimedia University. It answers academic
questions grounded in official MMU handbook PDFs, and campus-navigation
questions from a structured location dataset — one hybrid knowledge base,
one retriever, source-traceable answers.

Stack: Streamlit · LangChain · ChromaDB · local sentence-transformers
embeddings (default) · Google Gemini (answer generation).

## Project structure

```
core/                RAG engine — no Streamlit UI code
  config.py             all tunables: models, paths, chunk size, k, temperature, embedding backend
  vector_store.py        embeddings + shared Chroma handle (local embeddings by default)
  rag_chain.py            history-aware retrieval + generation (LangChain's official chain helpers)
  intent.py                chit-chat vs knowledge check (decides whether to retrieve at all)
  location_lookup.py      exact/alias/room-code short-circuit for the location dataset
  query_log.py             JSONL logging of every question/answer/sources, + 👍/👎 feedback
  logging_setup.py          one logger used instead of silent except/pass

ui/styles.py          shared CSS
views/assistant_view.py   the chat page

app.py                thin router: page config, CSS, sidebar, ?admin=1 gate, dispatch
admin.py               password-gated admin console (PDF upload, locations, announcements)
locations.py           structured location dataset + directory page
announcements.py       campus events/announcements feature
cgpa_calculator.py     CGPA calculator (standalone, no RAG dependency)
source_explorer.py     search + page-level PDF source verification

build_database.py     FULL rebuild of chroma_db from ./data + locations.json (wipes and rebuilds)
evaluate.py            retrieval/answer evaluation harness (Objective 3)
eval/goldset.json       hand-written question / expected-source pairs
```

The admin console has no button anywhere in the student-facing UI. It only
opens via a URL flag (`?admin=1`) and is still password-gated.

## Setup

```bash
python -m venv fyp_env
# Windows: fyp_env\Scripts\activate      macOS/Linux: source fyp_env/bin/activate
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml` (never committed — see `.gitignore`):

```toml
GEMINI_API_KEY = "your-gemini-api-key"
ADMIN_PASSWORD = "choose-a-password"
```

`GEMINI_API_KEY` is required for answer generation (Gemini is always used for
that, regardless of embedding backend). It is **not** required to build or
query the vector database with the default local embedding backend.

## Build the knowledge base

```bash
python build_database.py
```

This is a **full rebuild**: it wipes `./chroma_db` and re-embeds every PDF in
`./data` plus every record in `./locations/locations.json`. With the default
local embedding backend (`sentence-transformers/all-MiniLM-L6-v2`) this needs
no API key, no network calls beyond the one-time model download, and finishes
in well under a minute for this project's dataset.

Run it again whenever you change `EMBEDDING_BACKEND` or
`LOCAL_EMBEDDING_MODEL` in `core/config.py` — a different embedding model
produces vectors of a different dimensionality, which makes the existing
`chroma_db` unreadable.

Day-to-day PDF additions do **not** need this script — use the admin panel
(below), which appends incrementally without ever rebuilding.

## Run the app

```bash
streamlit run app.py
```

Open `http://localhost:8501`. For the admin console:
`http://localhost:8501/?admin=1`, then log in with `ADMIN_PASSWORD`.

## Run the evaluation harness

```bash
python evaluate.py
```

For each question in `eval/goldset.json`, compares the live hybrid
retriever's hit-rate against a BM25 keyword-search baseline built from the
same indexed chunks, and (if `GEMINI_API_KEY` is set) a keyword-based
answer-relevancy check on the generated answer. Edit `eval/goldset.json` to
add more questions as the knowledge base grows — `expected_source` must match
a `source_file` value exactly (a PDF's basename, or `"Campus Directory"` for
locations).

## Configuration

Everything tunable lives in `core/config.py`: model names, chunk size/overlap,
retriever `k`, generation temperature, paths, and the embedding backend
switch (`EMBEDDING_BACKEND=local` default, or `gemini`). Override via
environment variables without editing the file, e.g.:

```bash
EMBEDDING_BACKEND=gemini python build_database.py
```

If a meaningful share of the indexed content is in Bahasa Melayu, switch
`LOCAL_EMBEDDING_MODEL` to
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (larger, slower,
multilingual) and rebuild.

## When are "View Sources" shown?

Only when an answer is genuinely grounded in retrieved context. Two gates in
`core/config.py` (both can be toggled off):

1. **Intent** (`INTENT_GATE_ENABLED`, `CHITCHAT_PATTERNS`): greetings, thanks,
   goodbyes and "who are you" are matched against the *whole* message, skip
   retrieval entirely, are answered directly by the LLM, and show no sources.
   `"hi, where is the library?"` is still a knowledge question.
2. **Grounding** (`GROUNDING_GATE_ENABLED`, `MIN_RELEVANCE_SCORE`,
   `NO_ANSWER_MARKER`): retrieved chunks scoring below the threshold are
   discarded, and if the model itself answers "I couldn't find that..." no
   sources are listed. The threshold is calibrated to `all-MiniLM-L6-v2`
   - re-measure it if you change `LOCAL_EMBEDDING_MODEL`.

Every logged query records its `intent` (`chitchat` / `knowledge`).

## Retrieval and evaluation

Retrieval is hybrid (`core/retrieval.py`): vector search + BM25, merged by
round-robin, with a relevance gate. `python evaluate.py --validate` proves the
gold sets against the index; `eval/goldset.json` (25 answerable + 5 no-answer)
was used for tuning and `eval/goldset_heldout.json` (11 + 3) was not.
Metric: *evidence-hit* = a retrieved chunk of the expected file contains the
evidence text (file-level "source-hit" overstates quality). Results are in
`eval/results/`; compare configs with `--mode`, `--fusion`, `--k`.

| config (dev n=25 / held-out n=11) | evidence-hit | sources/answer |
|---|---|---|
| vector k=3 (old default) | 64% / 91% | 1.60 |
| vector k=5 | 76% / 91% | 1.88 |
| hybrid RRF k=3 | 84% / 100% | 1.68 |
| **hybrid interleave k=5 (default)** | **88% / 100%** | 2.04 |

Known misses: q01 (the data has the graduation *rule* but no credit total),
q18 ("July" vs "JUL" in the calendar), q24 (paraphrased location question).

## Campus locations

`data/Location File.xlsx` is the source of truth for places (code, name, category,
building, floor, directions, aliases, opening hours, contact, source, verification
status, notes). `python build_database.py` imports it; in the admin panel,
**Re-import from Excel** upserts by room code (never duplicates) and re-syncs the
assistant. Empty cells stay empty. Answers and cards carry the verification status:
unverified rooms are flagged as possibly outdated, conflicting entries show both
versions and ask the user to check on site. Lookup matches whole tokens only.

## Notes

- `chroma_db/` and `data/query_log.jsonl` are generated, not versioned — see
  `.gitignore`. Rebuild the DB with `build_database.py` after cloning.
- `data/` holds the source PDFs (versioned) plus the generated query log
  (not versioned).
- The admin panel's PDF upload is **incremental**: `add_documents()` only,
  duplicate-checked by `metadata["source_file"]`, with a Replace option and a
  per-file delete button. It never rebuilds `chroma_db`.
