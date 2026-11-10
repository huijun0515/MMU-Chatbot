"""
Query log (SQLite table `query_log`): one row per question asked — used for
analytics (admin Insights), feedback, and as raw material for the gold set.

Privacy: student-ID-like numbers and phone numbers are masked BEFORE anything is
stored (see scrub), no names/IDs are collected, and rows older than
config.QUERY_LOG_RETENTION_DAYS are deleted automatically (core/db.py).
"""

import json
import re
import uuid

from core import db
from core.logging_setup import logger

# MMU student IDs are 10 digits; Malaysian phone numbers look like 012-345 6789 / +60123456789.
# Room codes (MNCR1001) contain letters, so they are untouched.
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?6?0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4})(?!\w)")
_ID_RE = re.compile(r"(?<![\w.])\d{9,12}(?![\w.])")


def scrub(text):
    text = _PHONE_RE.sub("[PHONE]", text or "")
    return _ID_RE.sub("[ID]", text)


def log_interaction(question, answer, sources, timestamp, intent="knowledge", input_mode="text",
                    voice_edited=None, language="en"):
    """Store one Q&A row. Returns its id so feedback can reference it.

    `sources` is what was actually shown to the user (empty for chit-chat and
    ungrounded answers); `intent` is "chitchat" or "knowledge".
    """
    entry_id = str(uuid.uuid4())[:8]
    try:
        db.ensure_ready()
        conn = db.connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO query_log (id,ts,question,answer,intent,language,input_mode,voice_edited,sources)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (entry_id, timestamp, scrub(question), scrub(answer), intent, language, input_mode,
                     None if voice_edited is None else int(bool(voice_edited)),
                     json.dumps(sources, ensure_ascii=False)),
                )
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to write query log entry")
    return entry_id


def record_feedback(entry_id, value):
    """Set feedback ("up"/"down") on a previously logged entry, by id."""
    try:
        db.ensure_ready()
        conn = db.connect()
        try:
            with conn:
                conn.execute("UPDATE query_log SET feedback=? WHERE id=?", (value, entry_id))
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to persist feedback")


def load_all():
    """Every logged row as a dict (oldest first), for analytics or evaluate.py."""
    db.ensure_ready()
    conn = db.connect()
    try:
        rows = []
        for r in conn.execute("SELECT * FROM query_log ORDER BY ts"):
            d = dict(r)
            d["sources"] = json.loads(d.get("sources") or "[]")
            d["voice_edited"] = None if d["voice_edited"] is None else bool(d["voice_edited"])
            d["timestamp"] = d.pop("ts")
            rows.append(d)
        return rows
    finally:
        conn.close()
