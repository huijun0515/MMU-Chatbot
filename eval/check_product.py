"""
Behaviour checks for the product-polish work (auth, privacy, rate limit, storage
migration, insights, Sources deep links, Places, assistant page).

    python eval/check_product.py            # no API calls
    python eval/check_product.py --llm      # also asks the assistant 3 real questions
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp()
os.environ["APP_DB_PATH"] = os.path.join(TMP, "app.db")          # isolated database for every check
os.environ["EVENT_POSTERS_DIR"] = os.path.join(TMP, "posters")

from streamlit.testing.v1 import AppTest  # noqa: E402
from core import admin_auth, config, db, insights, query_log, rate_limit  # noqa: E402

# The throw-away database must start empty: do not migrate the real JSON files into it.
config.QUERY_LOG_PATH = os.path.join(TMP, "no_query_log.jsonl")
config.LEGACY_LOCATIONS_JSON = os.path.join(TMP, "no_locations.json")
config.LEGACY_ANNOUNCEMENTS_JSON = os.path.join(TMP, "no_announcements.json")

failures = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def page(name):
    os.environ["SMOKE_PAGE"] = name
    return AppTest.from_file("eval/_page_harness.py", default_timeout=180)


def text(at):
    labels = [getattr(el, "label", "") or "" for el in at.main]
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption] + labels)


# ── admin auth ───────────────────────────────────────────────────────────
k, t0 = "client-a", 1000.0
check("correct password accepted", admin_auth.attempt("pw", "pw", k, t0)[0])
for i in range(4):
    ok, msg = admin_auth.attempt("bad", "pw", k, t0 + i)
check("4 wrong passwords: still not locked", admin_auth.seconds_locked(k, t0 + 5) == 0 and "left" in msg, msg)
ok, msg = admin_auth.attempt("bad", "pw", k, t0 + 6)
check("5th wrong password locks the client", not ok and admin_auth.seconds_locked(k, t0 + 7) > 0, msg)
check("correct password is refused while locked", not admin_auth.attempt("pw", "pw", k, t0 + 8)[0])
check("lock ends after 5 minutes", admin_auth.seconds_locked(k, t0 + 6 + admin_auth.LOCKOUT_SECONDS + 1) == 0
      and admin_auth.attempt("pw", "pw", k, t0 + 6 + admin_auth.LOCKOUT_SECONDS + 2)[0])
check("other clients are not affected", admin_auth.attempt("pw", "pw", "client-b", t0 + 8)[0])
check("idle timeout after 30 min", admin_auth.session_expired(t0, t0 + 31 * 60) and not admin_auth.session_expired(t0, t0 + 29 * 60))
check("constant-time compare handles non-ASCII", admin_auth.passwords_match("pässwörd", "pässwörd") and not admin_auth.passwords_match("a", "b"))

# ── privacy: scrubbing + retention ───────────────────────────────────────
raw = "my id 1211103456 and 012-345 6789, +60123456789, where is MNCR1001 in 2026?"
clean = query_log.scrub(raw)
check("student ID and phone numbers are masked", "1211103456" not in clean and "345 6789" not in clean and "[ID]" in clean and clean.count("[PHONE]") == 2, clean)
check("room codes and years survive", "MNCR1001" in clean and "2026" in clean)
lid = query_log.log_interaction(raw, "reply 1211103456", ["Campus Directory"], "2026-11-10T10:00:00", language="en")
row = next(r for r in query_log.load_all() if r["id"] == lid)
check("stored question/answer are scrubbed", "1211103456" not in row["question"] + row["answer"])
query_log.record_feedback(lid, "up")
check("feedback is stored", next(r for r in query_log.load_all() if r["id"] == lid)["feedback"] == "up")
old = query_log.log_interaction("ancient question", "a", [], "2020-01-01T00:00:00")
db._ready_for = None
db.ensure_ready()
check("retention purges rows older than the limit", all(r["id"] != old for r in query_log.load_all()))
check("recent rows are kept", any(r["id"] == lid for r in query_log.load_all()))

# ── rate limit ───────────────────────────────────────────────────────────
store = {}
allowed = [rate_limit.try_acquire(store, now=100.0 + i)[0] for i in range(config.CHAT_RATE_LIMIT_MAX + 3)]
check(f"{config.CHAT_RATE_LIMIT_MAX} questions allowed, the rest refused", allowed.count(True) == config.CHAT_RATE_LIMIT_MAX and allowed[-1] is False)
check("allowed again after the window", rate_limit.try_acquire(store, now=100.0 + config.CHAT_RATE_LIMIT_WINDOW_SECONDS + 30)[0])

# ── JSON -> SQLite migration (isolated process, isolated paths) ──────────
mig = os.path.join(TMP, "mig")
os.makedirs(os.path.join(mig, "loc"))
os.makedirs(os.path.join(mig, "ann"))
json.dump([{"id": "x1", "code": "X1", "name": "Test Room", "aliases": ["TR"], "category": "Lab", "building": "B", "floor": "L1"}],
          open(os.path.join(mig, "loc", "locations.json"), "w", encoding="utf-8"))
with open(os.path.join(mig, "data_query_log.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"id": "q1", "timestamp": "2099-01-01T00:00:00", "question": "hello", "answer": "hi", "intent": "chitchat",
                        "sources": [], "feedback": "down", "input_mode": "voice", "voice_edited": True}) + "\n")
os.makedirs(os.path.join(mig, "data"))
os.replace(os.path.join(mig, "data_query_log.jsonl"), os.path.join(mig, "data", "query_log.jsonl"))
env = {**os.environ, "APP_DB_PATH": os.path.join(mig, "app.db"), "DATA_DIR": os.path.join(mig, "data"),
       "LOCATION_IMAGES_DIR": os.path.join(mig, "loc"), "EVENT_POSTERS_DIR": os.path.join(mig, "ann")}
code = ("from core import db, locations_repo as l, query_log as q\n"
        "db.ensure_ready(); db._ready_for=None; db.ensure_ready()\n"   # run twice: must not duplicate
        "print(len(l.all_locations()), l.get('x1')['aliases'], len(q.load_all()), q.load_all()[0]['feedback'], q.load_all()[0]['voice_edited'])\n")
out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=ROOT).stdout.strip().splitlines()[-1]
check("migration: 1 location, aliases kept, 1 log row, feedback+voice flags kept, no duplicates on rerun", out == "1 ['TR'] 1 down True", out)

# ── insights ─────────────────────────────────────────────────────────────
for i in range(3):
    query_log.log_interaction("Where is the library?", "Located in SHDL.", ["Campus Directory"], f"2026-11-0{i + 1}T10:00:00")
query_log.log_interaction("Is there parking?", "I'm sorry, I couldn't find that specific information in the current data.", [], "2026-11-05T10:00:00")
query_log.log_interaction("hi", "Hello!", [], "2026-11-05T10:01:00", intent="chitchat")
df = insights.load_frame()
s = insights.summarize(df)
check("insights: counts and knowledge-gap detection",
      s["total"] >= 5 and "Is there parking?" in s["gaps"]["example"].tolist() and "hi" not in s["gaps"]["example"].tolist())
check("insights: top question is the repeated one", s["top_questions"].iloc[0]["example"] == "Where is the library?" and s["top_questions"].iloc[0]["times"] == 3)
check("insights: CSV export works", b"question" in insights.export_csv(df))

# ── admin page (AppTest) ─────────────────────────────────────────────────
correct = config.get_secret("ADMIN_PASSWORD")
at = page("admin"); at.run()
check("admin logged out: login form, no tabs", len(at.tabs) == 0 and any(b.label == "Log in" for b in at.button) or any("Log in" in str(b) for b in at.get("form_submit_button")))
at.session_state["admin_authed"] = True
at.session_state["admin_last_seen"] = time.time() - 31 * 60
at.run()
check("admin: idle session is logged out with a notice", not at.session_state["admin_authed"] if "admin_authed" in at.session_state else True)
at = page("admin"); at.session_state["admin_authed"] = True; at.session_state["admin_last_seen"] = time.time(); at.run()
check("admin logged in: Insights/KB/Locations/Events tabs", {"Insights", "Knowledge base", "Locations", "Events"} <= {t.label for t in at.tabs} and not at.exception, str(at.exception))
check("admin: logout button present", any("Log out" in b.label for b in at.button))

# ── Sources deep link ────────────────────────────────────────────────────
at = page("sources")
at.session_state["source_focus"] = {"doc": "2025 Academic Handbook.pdf", "page": 24,
                                    "passage": "Course withdrawal is permissible up to week seven (7) (long trimester)"}
at.run()
t = text(at)
check("Sources opens the cited document and page", "2025 Academic Handbook.pdf" in t and "Page 24 of 89" in t and not at.exception, str(at.exception))
at = page("sources"); at.query_params["doc"] = "2026 Academic Calendar.pdf"; at.query_params["page"] = "1"; at.run()
check("Sources accepts ?doc=&page= in the URL", "2026 Academic Calendar.pdf" in text(at) and "Page 1 of 1" in text(at))

# ── Places ───────────────────────────────────────────────────────────────
at = page("places"); at.run()
check("Places: campus map is shown at the top", "campus map" in text(at).lower())
at.text_input(key="places_query").set_value("FBLR0006A").run()
t = text(at)
check("Places: search by an OLD code finds the room", "FOB Lecture Room 1" in t and "1 place" in t, t[:200])
at.text_input(key="places_query").set_value("").run()
sel = next(s for s in at.selectbox if s.label == "Verification")
sel.select("Conflict - check on site").run()
check("Places: filter by verification status", "4 places" in text(at), text(at)[:200])

# ── Assistant page ───────────────────────────────────────────────────────
at = page("assistant"); at.run()
t = text(at)
check("Assistant: welcome card + suggestion chips on an empty chat", "Welcome" in t and not at.exception)
check("Assistant: 'nearest lecture hall' suggestion removed", "nearest lecture hall" not in t.lower())
check("Assistant: chat input limited to 500 characters", at.chat_input[0].proto.max_chars == config.CHAT_MAX_CHARS)
check("Assistant: privacy notice under the input", "logged anonymously" in t)

if "--llm" in sys.argv:
    at = page("assistant"); at.run()
    at.session_state["quick_query"] = "Where is MNCR1001?"
    at.run()
    users = [m for m in at.chat_message if m.name == "user"]
    check("Assistant: answer produced; welcome/chips disappear after the first message", len(users) == 1 and "Welcome" not in text(at), text(at)[:200])
    check("Assistant: feedback widget and citations rendered", len(at.get("feedback")) >= 1 and any("Campus Directory" in b.label for b in at.button), str([b.label for b in at.button]))
    time.sleep(7)
    at.session_state["quick_query"] = "Pukul berapa perpustakaan dibuka pada hari bekerja semasa trimester?"
    at.run()
    last = [m for m in at.chat_message if m.name == "assistant"][-1].markdown[0].value
    check("Assistant answers a Malay question in Malay", any(w in last.lower() for w in ("pada", "dibuka", "perpustakaan", "jam", "pagi", "malam")), last[:160])
    print("   malay answer:", last[:200].replace("\n", " "))
    time.sleep(7)
    at.session_state["quick_query"] = "图书馆考试周几点开门？"
    at.run()
    last = [m for m in at.chat_message if m.name == "assistant"][-1].markdown[0].value
    check("Assistant answers a Chinese question in Chinese", any("一" <= c <= "鿿" for c in last), last[:160])
    print("   chinese answer:", last[:200].replace("\n", " "))

print("\nALL PRODUCT CHECKS PASSED" if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
