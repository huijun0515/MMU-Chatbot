"""Repository for campus locations (SQLite). Records are plain dicts; `aliases` is a list."""

import json

from core import db

_TEXT_COLUMNS = [c for c in db.LOCATION_COLUMNS if c not in ("id", "aliases")]


def _to_record(row):
    rec = dict(row)
    try:
        rec["aliases"] = json.loads(rec.get("aliases") or "[]")
    except json.JSONDecodeError:
        rec["aliases"] = []
    return rec


def _values(rec):
    out = [rec["id"], json.dumps(rec.get("aliases") or [], ensure_ascii=False)]
    out += [(rec.get(c) or "") for c in _TEXT_COLUMNS]
    return out


_ORDER = ["id", "aliases"] + _TEXT_COLUMNS
_UPSERT = (f"INSERT OR REPLACE INTO locations ({','.join(_ORDER)}) VALUES ({','.join('?' * len(_ORDER))})")


def all_locations():
    db.ensure_ready()
    conn = db.connect()
    try:
        return [_to_record(r) for r in conn.execute("SELECT * FROM locations ORDER BY lower(name)")]
    finally:
        conn.close()


def get(loc_id):
    db.ensure_ready()
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM locations WHERE id=?", (loc_id,)).fetchone()
        return _to_record(row) if row else None
    finally:
        conn.close()


def upsert_many(records):
    db.ensure_ready()
    conn = db.connect()
    try:
        with conn:
            conn.executemany(_UPSERT, [_values(r) for r in records])
    finally:
        conn.close()


def upsert(rec):
    upsert_many([rec])


def delete(loc_id):
    db.ensure_ready()
    conn = db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM locations WHERE id=?", (loc_id,))
    finally:
        conn.close()
