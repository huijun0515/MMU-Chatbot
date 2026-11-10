"""
The app database (one SQLite file, config.APP_DB_PATH): events, locations and the
query log, plus one-time migration of the old JSON/JSONL files.

Every storage path comes from core/config.py, so a deployment can mount a
persistent volume and point MMU_STORAGE_DIR (or the individual variables) at it.
"""

import json
import os
import sqlite3
import threading

from core import config
from core.logging_setup import logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Other',
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    all_day INTEGER NOT NULL DEFAULT 0,
    venue_location_id TEXT NOT NULL DEFAULT '',
    venue_text TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    organiser TEXT NOT NULL DEFAULT '',
    registration_url TEXT NOT NULL DEFAULT '',
    poster TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT '',
    building TEXT NOT NULL DEFAULT '',
    floor TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    directions TEXT NOT NULL DEFAULT '',
    landmarks TEXT NOT NULL DEFAULT '',
    opening_hours TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS query_log (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    intent TEXT NOT NULL DEFAULT 'knowledge',
    language TEXT NOT NULL DEFAULT 'en',
    input_mode TEXT NOT NULL DEFAULT 'text',
    voice_edited INTEGER,
    sources TEXT NOT NULL DEFAULT '[]',
    feedback TEXT
);
CREATE INDEX IF NOT EXISTS idx_query_log_ts ON query_log (ts);
"""

LOCATION_COLUMNS = ["id", "code", "name", "aliases", "category", "building", "floor", "description", "directions",
                    "landmarks", "opening_hours", "contact", "source", "verification_status", "notes", "image"]

_lock = threading.Lock()
_ready_for = None  # the db path the schema/migrations have been applied to


def connect():
    os.makedirs(os.path.dirname(config.APP_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(config.APP_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_ready():
    """Create the schema and run the one-time migrations (once per process per database)."""
    global _ready_for
    if _ready_for == config.APP_DB_PATH:
        return
    with _lock:
        if _ready_for == config.APP_DB_PATH:
            return
        conn = connect()
        try:
            with conn:
                conn.executescript(SCHEMA)
                _migrate_locations(conn)
                _migrate_query_log(conn)
                _purge_old_logs(conn)
        finally:
            conn.close()
        _ready_for = config.APP_DB_PATH


def _flag(conn, key):
    return conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone() is not None


def _set_flag(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))


def _migrate_locations(conn):
    if _flag(conn, "migrated_locations_json"):
        return
    path = config.LEGACY_LOCATIONS_JSON
    count = 0
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
            for rec in items:
                values = []
                for col in LOCATION_COLUMNS:
                    v = rec.get(col, "")
                    values.append(json.dumps(v or [], ensure_ascii=False) if col == "aliases" else (v or ""))
                conn.execute(f"INSERT OR IGNORE INTO locations ({','.join(LOCATION_COLUMNS)}) "
                             f"VALUES ({','.join('?' * len(LOCATION_COLUMNS))})", values)
                count += 1
        except (OSError, json.JSONDecodeError, KeyError):
            logger.exception("Could not migrate %s", path)
    _set_flag(conn, "migrated_locations_json", count)
    logger.info("Migrated %d location(s) from JSON into SQLite", count)


def _migrate_query_log(conn):
    if _flag(conn, "migrated_query_log_jsonl"):
        return
    path = config.QUERY_LOG_PATH
    count = 0
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    voice = r.get("voice_edited")
                    conn.execute(
                        "INSERT OR IGNORE INTO query_log (id,ts,question,answer,intent,language,input_mode,voice_edited,sources,feedback)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (r["id"], r.get("timestamp", ""), r.get("question", ""), r.get("answer", ""),
                         r.get("intent", "knowledge"), r.get("language", "en"), r.get("input_mode", "text"),
                         None if voice is None else int(bool(voice)),
                         json.dumps(r.get("sources", []), ensure_ascii=False), r.get("feedback")),
                    )
                    count += 1
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Skipping malformed query-log line during migration")
    _set_flag(conn, "migrated_query_log_jsonl", count)
    logger.info("Migrated %d query-log row(s) from JSONL into SQLite", count)


def _purge_old_logs(conn):
    """Retention: delete query-log rows older than config.QUERY_LOG_RETENTION_DAYS."""
    import datetime as dt
    cutoff = (dt.datetime.now() - dt.timedelta(days=config.QUERY_LOG_RETENTION_DAYS)).isoformat(timespec="seconds")
    cur = conn.execute("DELETE FROM query_log WHERE ts < ?", (cutoff,))
    if cur.rowcount:
        logger.info("Retention: deleted %d query-log row(s) older than %d days", cur.rowcount,
                    config.QUERY_LOG_RETENTION_DAYS)
