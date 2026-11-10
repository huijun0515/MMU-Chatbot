"""
End-to-end checks for the Events feature, on a throw-away database and a frozen clock.

    python eval/check_events.py

Covers: migration of the old announcements.json, create / edit / duplicate / pin /
delete, validation, hero choice, events expiring (fake date), HTML escaping, the
student page and the admin panel (logged out / logged in / creating an event).
"""

import datetime as dt
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["APP_DB_PATH"] = os.path.join(TMP, "app.db")
os.environ["EVENT_POSTERS_DIR"] = os.path.join(TMP, "posters")
sys.path.insert(0, os.getcwd())

from streamlit.testing.v1 import AppTest  # noqa: E402


def open_page(name):
    os.environ["SMOKE_PAGE"] = name
    return AppTest.from_file("eval/_page_harness.py", default_timeout=60)



from core import config, events_db as db  # noqa: E402

NOW = dt.datetime(2026, 11, 10, 10, 0)
failures = []


def check(name, condition, detail=""):
    print(("ok   " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def ev(**kw):
    base = dict(category="Career", all_day=0, venue_location_id="", venue_text="", description="", organiser="",
                registration_url="", poster="", status="published", pinned=0)
    base.update(kw)
    return db.create_event(**base)


def at(days, hour):
    return (NOW.replace(hour=hour) + dt.timedelta(days=days)).isoformat(timespec="minutes")


def page_text(app):
    return " ".join([m.value for m in app.markdown] + [e.label for e in app.expander])


# ── migration ────────────────────────────────────────────────────────────
legacy = os.path.join(TMP, "legacy.json")
with open(legacy, "w", encoding="utf-8") as f:
    json.dump([{"id": "abc12345", "title": "Old Poster Event", "description": "d", "date": "2026-07-28",
                "image": "poster_x.png", "created_at": "2026-07-28T14:17:34"}], f)
config.LEGACY_ANNOUNCEMENTS_JSON = legacy
db.set_now(NOW)
db.init_db()
db.init_db()  # idempotent
old = db.get_event("abc12345")
check("legacy announcement migrated once", old is not None and len(db.list_events()) == 1)
check("migrated event keeps date, is all-day, published", old["start_at"] == "2026-07-28T00:00" and old["all_day"] == 1 and old["status"] == "published")
check("migrated July event is already past", db.is_past(old))

# ── CRUD, validation ─────────────────────────────────────────────────────
check("validation rejects end < start", bool(db.validate(dict(title="x", category="Career", start_at=at(1, 12), end_at=at(1, 10), status="draft"))))
check("validation rejects javascript: link", any("http" in e for e in db.validate(dict(title="x", category="Career", start_at=at(1, 9), end_at=at(1, 10), status="draft", registration_url="javascript:alert(1)"))))
check("validation rejects empty title", any("Title" in e for e in db.validate(dict(title=" ", category="Career", start_at=at(1, 9), end_at=at(1, 10), status="draft"))))

talk = ev(title="FIST Industry Talk", category="Academic Talk", start_at=at(2, 14), end_at=at(2, 16), venue_text="CLC Lecture Hall C1", venue_location_id="msmx2001", registration_url="https://example.com/r", organiser="FIST")
fair = ev(title="Career Fair", start_at=at(4, 9), end_at=at(4, 16), venue_text="Exam Hall", venue_location_id="exam-hall")
xss = ev(title="<script>alert(1)</script> Hack", category="Clubs & Societies", start_at=at(6, 18), end_at=at(6, 20), organiser="<b>IT</b>", venue_text="<img src=x onerror=alert(1)>")
draft = ev(title="Hidden Draft", start_at=at(1, 9), end_at=at(1, 10), status="draft")
check("drafts are not upcoming", draft not in [e["id"] for e in db.upcoming_events(NOW)])
check("hero = soonest upcoming", db.pick_hero(db.upcoming_events(NOW))["id"] == talk)
db.update_event(fair, **{k: db.get_event(fair)[k] for k in db.FIELDS} | {"pinned": 1})
check("pinned event becomes the hero", db.pick_hero(db.upcoming_events(NOW))["id"] == fair)
copy_id = db.duplicate_event(talk)
copy = db.get_event(copy_id)
check("duplicate is an unpinned draft copy", copy["status"] == "draft" and copy["title"] == "Copy of FIST Industry Talk" and not copy["pinned"])
db.delete_event(copy_id)
check("delete removes the event", db.get_event(copy_id) is None)
ics = db.ics(db.get_event(talk))
check("ics has UTC start (14:00 MYT = 06:00Z) and title", "DTSTART:20261112T060000Z" in ics and "SUMMARY:FIST Industry Talk" in ics)

# ── student page ─────────────────────────────────────────────────────────
app = open_page("events")
app.run()
text = page_text(app)
check("student page renders without exceptions", not app.exception, str(app.exception))
check("hero shows the pinned event with countdown", "Career Fair" in text and "Next up · in 4 days" in text)
check("grid counts upcoming minus hero (2)", "Upcoming · 2 events" in text)
check("admin text is HTML-escaped (no raw <script>/<img/<b>)", "<script>alert" not in text and "<img src=x" not in text and "<b>IT</b>" not in text and "&lt;script&gt;" in text)
check("drafts never shown to students", "Hidden Draft" not in text)
check("no past-events section yet beyond migrated one", "Past events · 1 event" in text)

app.session_state["ev_cat"] = "Academic Talk"
app.run()
check("category chip filters the grid", "Upcoming · 1 event" in page_text(app) and "FIST Industry Talk" in page_text(app))
app.session_state["ev_cat"] = "All"
app.session_state["ev_when"] = "This week"
app.run()
check("'This week' keeps only this week's events", "Upcoming · 1 event" in page_text(app))  # talk (12 Nov); hack night is next week

# ── events expire by themselves (fake the date) ──────────────────────────
db.set_now(NOW + dt.timedelta(days=3))  # Fri 13 Nov: the talk (12 Nov) has ended
app = open_page("events")
app.run()
text = page_text(app)
check("after the talk ends it moves to Past events", "Past events · 2 events" in text, text[text.find("Past events"):][:60])
check("hero moves on (talk no longer hero)", "Next up" in text and "FIST Industry Talk" not in text.split("Past events")[0].split("Upcoming")[0])
db.set_now(NOW + dt.timedelta(days=60))
app = open_page("events")
app.run()
text = page_text(app)
check("with nothing upcoming: friendly empty state, no hero", "No upcoming events" in text and "Next up" not in text)
db.set_now(NOW)

# ── admin ────────────────────────────────────────────────────────────────
admin = open_page("admin")
admin.run()
check("admin logged OUT shows the password gate, not the events tab", any(b.label == "Log in" for b in admin.button) and not any("New event" in b.label for b in admin.button))
admin.session_state["admin_authed"] = True
admin.session_state["admin_last_seen"] = 10**12
admin.run()
check("admin logged IN shows the events list", any("New event" in b.label for b in admin.button) and not admin.exception, str(admin.exception))
next(b for b in admin.button if "New event" in b.label).click().run()
next(t for t in admin.text_input if t.label == "Title *").set_value("Created In Admin")
next(b for b in admin.button if "Save event" in b.label).click().run()
created = [e for e in db.list_events() if e["title"] == "Created In Admin"]
check("admin form creates a draft event", len(created) == 1 and created[0]["status"] == "draft", str(admin.exception))

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
