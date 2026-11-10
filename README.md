# MMU Intelligent Campus Assistant

A Streamlit RAG chatbot for Multimedia University (Melaka campus). It answers
academic questions grounded in official MMU documents, campus-navigation
questions from a structured, verification-aware location directory, and event
questions from a live calendar — in English, Bahasa Melayu and Chinese — and
always shows where an answer came from.

Stack: Streamlit 1.56 · LangChain · ChromaDB · local sentence-transformers
embeddings · Google Gemini (answers, translation of search queries, transcription).

## Pages

| URL | Page | Notes |
|---|---|---|
| `/assistant` (also `/`) | Assistant | streaming answers, citations that open the exact PDF page, location cards, 👍/👎, voice input |
| `/places` | Places | search by code/name/alias/old code, filters, campus map, per-place dialog |
| `/sources` | Sources | search or deep-link (`?doc=&page=`) to a page with the passage highlighted |
| `/events` | Events | hero, filters, cards, past events collapsed |
| `/calculator` | CGPA calculator | MMU grading scheme (Handbook §8.1) |
| `/admin` | Admin console | hidden from the menu, password-gated (`?admin=1` redirects here) |
| `/privacy` | Privacy notice | linked from every footer |

## Project structure

```
app.py, app_pages.py       entry point (st.navigation) and the page registry
views/                     assistant page, privacy page
events.py, locations.py, source_explorer.py, cgpa_calculator.py, admin.py   feature pages
ui/                        styles.py (theme CSS variables), layout.py (header/footer/error boundary),
                           nav.py (page links), widgets.py (copy / read-aloud buttons)
core/                      no page code
  config.py                  every tunable and every storage path
  db.py                      the SQLite schema + one-time JSON migrations
  locations_repo.py, events_db.py, query_log.py     repositories on that database
  vector_store.py, retrieval.py, rag_chain.py       embeddings, hybrid retrieval, streaming chain
  language.py                language detection, English search query for BM/ZH questions, query expansion
  intent.py, location_lookup.py, event_context.py   chit-chat gate, exact place lookup, live events
  voice.py, rate_limit.py, admin_auth.py, insights.py, posters.py, location_import.py
build_database.py          FULL rebuild of the vector index (PDFs + locations)
evaluate.py, eval/         gold sets, results, and the test scripts below
.streamlit/config.toml     MMU theme (light + dark) — colours are defined here and in ui/styles.py only
```

## Setup

```bash
python -m venv fyp_env
# Windows: fyp_env\Scripts\activate      macOS/Linux: source fyp_env/bin/activate
pip install -r requirements.txt
python build_database.py        # builds the vector index (no API key needed)
streamlit run app.py
```

`.streamlit/secrets.toml` (never committed):

```toml
GEMINI_API_KEY = "your-gemini-api-key"      # answers, translation, voice transcription
ADMIN_PASSWORD = "a-long-random-password"
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MMU_STORAGE_DIR` | `.` | one root for everything below — point it at a persistent volume |
| `DATA_DIR` | `<root>/data` | source PDFs, `Location File.xlsx` |
| `CHROMA_DIR` | `<root>/chroma_db` | vector index |
| `APP_DB_PATH` | `<root>/data/app.db` | SQLite: events, locations, query log |
| `LOCATION_IMAGES_DIR`, `EVENT_POSTERS_DIR` | `<root>/locations`, `<root>/announcements` | uploaded images |
| `EMBEDDING_BACKEND` | `local` | `local` or `gemini` |
| `GEMINI_API_KEY`, `ADMIN_PASSWORD` | — | also accepted as environment variables |

## Data and storage

One SQLite file (`data/app.db`) holds events, locations and the query log. On
first start the old files are imported once and then ignored:
`announcements/announcements.json`, `locations/locations.json`,
`data/query_log.jsonl`. `data/Location File.xlsx` remains the editable source of
truth for places: `python build_database.py` or **Admin → Locations → Import /
export** upserts it by room code (never duplicates; empty cells stay empty) and
the admin can also edit places inline and download the current data as Excel.

Rebuild the vector index after changing the embedding model:
`python build_database.py` (the admin PDF upload is incremental and never rebuilds).

## How answers are produced

* **Intent gate** — greetings/thanks skip retrieval and show no sources.
* **Hybrid retrieval** — vector + BM25 merged round-robin, a relevance gate, exact
  room-code/alias lookup, and the live events calendar for event questions.
  Non-English questions are translated into an English *search query*; the answer
  is written in the user's language. A small query-expansion table bridges
  student/document wording (`subject`→`course`, `July`→`Jul`, `withdraw`→`withdrawal`).
* **Grounding gate** — sources are shown only if the answer rests on retrieved
  passages. Passages are treated as data: the system prompt tells the model to
  ignore any instruction inside them.
* **Place status** — unverified rooms are flagged as possibly outdated; conflicting
  entries show both versions and ask the user to check on site.

## Evaluation

```bash
python evaluate.py --validate                       # prove the gold set against the index
python evaluate.py [--with-llm] [--tag name]        # retrieval (and answer) metrics
python evaluate.py --goldset eval/goldset_heldout.json [--with-llm]
python evaluate.py --events --with-llm              # live-calendar questions on a frozen date
python eval/smoke_pages.py                          # every page renders, logged out/in
python eval/check_product.py [--llm]                # auth, privacy, rate limit, migration, insights, pages
python eval/check_events.py                         # events feature
```

*Evidence-hit* means a retrieved chunk of the expected file contains the evidence
text (file-level hits overstate quality). `eval/goldset.json` is the tuning set
(35 answerable incl. 6 Malay/Chinese and the 4 welcome-page suggestions, + 5
no-answer); `eval/goldset_heldout.json` (11 + 3) was never tuned on. Results are
saved in `eval/results/`.

## Privacy

Question text, answer, sources, time, input mode and 👍/👎 are logged; no names or
student IDs. Student-ID-like numbers and phone numbers are masked before storage;
rows older than `QUERY_LOG_RETENTION_DAYS` (180) are deleted automatically. The
policy shown to users is `views/privacy_view.py`. Voice recordings are sent to
Gemini for transcription and not kept.

## Security and cost controls

* Admin: constant-time password check, 5-minute lockout after 5 failures per
  client, 30-minute idle logout, logout button, confirm dialogs before deletes,
  uploads validated (PDF magic bytes and size; images re-encoded with Pillow),
  admin-entered text HTML-escaped.
* Per-session chat limit: 20 questions / 10 minutes (`CHAT_RATE_LIMIT_*`); typed,
  suggested and voice-transcription requests all count. Input is capped at 500 characters.
* The microphone only works on **HTTPS or localhost**.

## Deployment

* **Streamlit Community Cloud**: quick to publish, but the disk is **ephemeral** —
  `app.db` (events, locations edits, query log), uploaded PDFs and posters, and the
  vector index are lost on every restart/redeploy. Use it for a demo only; the repo
  (PDFs, `Location File.xlsx`, `build_database.py`) lets you recreate the index, but
  admin-entered data would vanish.
* **A host with a persistent volume** (VM, container platform, or any PaaS volume):
  mount the volume, set `MMU_STORAGE_DIR` to it, put secrets in the environment or
  `.streamlit/secrets.toml`, run `python build_database.py` once, then
  `streamlit run app.py --server.port 8501` behind HTTPS (needed for the microphone).
  Back up `app.db` and `data/`.
* Single-process note: the rate limit and admin lockout are per process/session
  (in memory); a multi-instance deployment would need a shared store.

## Future work

Move from Streamlit to a **React front end + FastAPI back end**: a proper
session/auth model (per-user rate limiting and admin roles instead of in-process
state), streaming over SSE/WebSocket, installable PWA/offline shell, CI-run
evaluation, and a managed vector store / Postgres so several instances can share
data. The `core/` package is already UI-free to make that move straightforward.
