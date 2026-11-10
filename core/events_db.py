"""
Campus events in SQLite (data/app.db). No Streamlit imports: used by the student
page, the admin panel, the assistant and evaluate.py alike.

All times are Malaysia time (config.TIMEZONE), stored as naive ISO strings
("2026-11-12T14:00") so comparisons and sorting are plain string/datetime ops.
Past events are never deleted: "past" is computed from end < now.
"""

import datetime as dt
import json
import os
import uuid
from zoneinfo import ZoneInfo

from core import config, db as appdb
from core.logging_setup import logger

FIELDS = ["title", "category", "start_at", "end_at", "all_day", "venue_location_id", "venue_text",
          "description", "organiser", "registration_url", "poster", "status", "pinned"]

_now_override = None


def now():
    """Current Malaysia time as a naive datetime. Tests can fake it with set_now()."""
    if _now_override is not None:
        return _now_override
    return dt.datetime.now(ZoneInfo(config.TIMEZONE)).replace(tzinfo=None, microsecond=0)


def set_now(value):
    """Freeze 'now' (a naive datetime) — or pass None to use the real clock."""
    global _now_override
    _now_override = value


def parse(value):
    return dt.datetime.fromisoformat(value)


def _connect():
    return appdb.connect()


def init_db():
    """Create the schema and, once, import the old announcements.json."""
    appdb.ensure_ready()
    conn = _connect()
    try:
        with conn:
            done = conn.execute("SELECT value FROM meta WHERE key='legacy_announcements_imported'").fetchone()
            if done:
                return
            count = _import_legacy_announcements(conn)
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('legacy_announcements_imported', ?)", (str(count),))
    finally:
        conn.close()


def _import_legacy_announcements(conn):
    path = config.LEGACY_ANNOUNCEMENTS_JSON
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read %s for migration", path)
        return 0
    count = 0
    for it in items:
        day = it.get("date") or it.get("created_at", "")[:10]
        if not day:
            continue
        stamp = it.get("created_at") or now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT OR IGNORE INTO events (id,title,category,start_at,end_at,all_day,description,poster,status,pinned,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (it.get("id") or uuid.uuid4().hex[:8], it.get("title", "Untitled"), "Other",
             f"{day}T00:00", f"{day}T23:59", 1,  # the old format had a date only, no time
             it.get("description", ""), it.get("image", ""), "published", 0, stamp, stamp),
        )
        count += 1
    logger.info("Migrated %d announcement(s) into the events table", count)
    return count


# ── validation ────────────────────────────────────────────────────────────
def validate(fields):
    """Return a list of problems (empty = OK)."""
    errors = []
    if not (fields.get("title") or "").strip():
        errors.append("Title is required.")
    if fields.get("category") not in config.EVENT_CATEGORIES:
        errors.append("Pick a category.")
    try:
        if parse(fields["end_at"]) < parse(fields["start_at"]):
            errors.append("The end must not be before the start.")
    except (KeyError, ValueError):
        errors.append("Start and end date/time are required.")
    url = (fields.get("registration_url") or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        errors.append("Registration link must start with http:// or https://.")
    if fields.get("status") not in ("draft", "published"):
        errors.append("Status must be draft or published.")
    return errors


# ── CRUD ──────────────────────────────────────────────────────────────────
def _clean(fields):
    out = {k: fields.get(k, "") for k in FIELDS}
    for k in ("title", "venue_location_id", "venue_text", "description", "organiser", "registration_url"):
        out[k] = (out[k] or "").strip()
    out["all_day"] = int(bool(out["all_day"]))
    out["pinned"] = int(bool(out["pinned"]))
    out["poster"] = out["poster"] or ""
    return out


def _run(sql, args=()):
    conn = _connect()
    try:
        with conn:
            return conn.execute(sql, args)
    finally:
        conn.close()


def _query(sql, args=()):
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def create_event(**fields):
    errors = validate(fields)
    if errors:
        raise ValueError("; ".join(errors))
    row = _clean(fields)
    event_id = uuid.uuid4().hex[:8]
    stamp = now().isoformat(timespec="seconds")
    _run(
        f"INSERT INTO events (id,{','.join(FIELDS)},created_at,updated_at) VALUES (?,{','.join('?' * len(FIELDS))},?,?)",
        [event_id, *[row[k] for k in FIELDS], stamp, stamp],
    )
    return event_id


def update_event(event_id, **fields):
    errors = validate(fields)
    if errors:
        raise ValueError("; ".join(errors))
    row = _clean(fields)
    _run(
        f"UPDATE events SET {','.join(k + '=?' for k in FIELDS)}, updated_at=? WHERE id=?",
        [*[row[k] for k in FIELDS], now().isoformat(timespec="seconds"), event_id],
    )


def get_event(event_id):
    rows = _query("SELECT * FROM events WHERE id=?", (event_id,))
    return rows[0] if rows else None


def delete_event(event_id):
    _run("DELETE FROM events WHERE id=?", (event_id,))


def duplicate_event(event_id):
    """Copy as a DRAFT (unpinned) so the admin can adjust the dates first.
    The copy shares the poster file; delete_event callers must check for that."""
    src = get_event(event_id)
    if not src:
        return None
    copy = {k: src[k] for k in FIELDS}
    copy.update(title=f"Copy of {src['title']}", status="draft", pinned=0)
    return create_event(**copy)


def poster_in_use_elsewhere(poster, except_id):
    if not poster:
        return False
    return bool(_query("SELECT 1 FROM events WHERE poster=? AND id<>? LIMIT 1", (poster, except_id)))


def list_events(status=None):
    if status:
        return _query("SELECT * FROM events WHERE status=? ORDER BY start_at", (status,))
    return _query("SELECT * FROM events ORDER BY start_at")


# ── views over the data ───────────────────────────────────────────────────
def is_past(event, at=None):
    return parse(event["end_at"]) < (at or now())


def upcoming_events(at=None):
    """Published events that have not ended yet, soonest first."""
    at = at or now()
    return sorted((e for e in list_events("published") if not is_past(e, at)), key=lambda e: e["start_at"])


def past_events(at=None):
    """Published events that have ended, newest first."""
    at = at or now()
    return sorted((e for e in list_events("published") if is_past(e, at)), key=lambda e: e["start_at"], reverse=True)


def pick_hero(upcoming):
    """Pinned events first, otherwise the soonest."""
    pinned = [e for e in upcoming if e["pinned"]]
    return (pinned or upcoming or [None])[0]


def week_bounds(at):
    monday = (at - dt.timedelta(days=at.weekday())).replace(hour=0, minute=0, second=0)
    return monday, monday + dt.timedelta(days=7)


def month_bounds(at):
    first = at.replace(day=1, hour=0, minute=0, second=0)
    nxt = (first + dt.timedelta(days=32)).replace(day=1)
    return first, nxt


def overlaps(event, start, end):
    return parse(event["start_at"]) < end and parse(event["end_at"]) >= start


# ── presentation helpers ──────────────────────────────────────────────────
def countdown_label(event, at=None):
    at = at or now()
    start, end = parse(event["start_at"]), parse(event["end_at"])
    if start <= at <= end:
        return "Happening now"
    days = (start.date() - at.date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return f"In {days} days"


def format_date(event):
    d = parse(event["start_at"])
    return f"{d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}"


def format_time(event):
    if event["all_day"]:
        return "All day"
    s, e = parse(event["start_at"]), parse(event["end_at"])
    f = lambda d: d.strftime("%I:%M %p").lstrip("0")
    span = f"{f(s)} – {f(e)}"
    return span if s.date() == e.date() else f"{span} (ends {e.day} {e.strftime('%b')})"


def ics(event):
    """An iCalendar (.ics) file for one event. Times are converted to UTC."""
    tz = ZoneInfo(config.TIMEZONE)
    utc = ZoneInfo("UTC")
    stamp = lambda v: parse(v).replace(tzinfo=tz).astimezone(utc).strftime("%Y%m%dT%H%M%SZ")
    esc = lambda t: (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MMU Campus Assistant//Events//EN", "BEGIN:VEVENT",
             f"UID:{event['id']}@mmu-campus-assistant", f"DTSTAMP:{stamp(now().isoformat())}",
             f"DTSTART:{stamp(event['start_at'])}", f"DTEND:{stamp(event['end_at'])}",
             f"SUMMARY:{esc(event['title'])}"]
    if event["venue_text"]:
        lines.append(f"LOCATION:{esc(event['venue_text'])}")
    if event["description"]:
        lines.append(f"DESCRIPTION:{esc(event['description'])}")
    if event["registration_url"]:
        lines.append(f"URL:{event['registration_url']}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"
