"""
JSONL query logging: one line per question asked, used both for analytics
and as raw material for building/expanding eval/goldset.json later.

Feedback (👍/👎) is cheap to capture, so it's optional per entry and updated
in place by rewriting the file — fine at the scale of an FYP demo.
"""

import json
import os
import uuid

from core import config
from core.logging_setup import logger


def log_interaction(question, answer, sources, timestamp):
    """Append one Q&A record. Returns its id so feedback can reference it."""
    os.makedirs(os.path.dirname(config.QUERY_LOG_PATH), exist_ok=True)
    entry_id = str(uuid.uuid4())[:8]
    record = {
        "id": entry_id,
        "timestamp": timestamp,
        "question": question,
        "answer": answer,
        "sources": sources,
        "feedback": None,
    }
    try:
        with open(config.QUERY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed to write query log entry")
    return entry_id


def record_feedback(entry_id, value):
    """Set feedback ("up"/"down") on a previously logged entry, by id."""
    if not os.path.exists(config.QUERY_LOG_PATH):
        return
    try:
        with open(config.QUERY_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        logger.exception("Failed to read query log for feedback update")
        return

    changed = False
    for i, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("id") == entry_id:
            record["feedback"] = value
            lines[i] = json.dumps(record, ensure_ascii=False) + "\n"
            changed = True
            break

    if changed:
        try:
            with open(config.QUERY_LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError:
            logger.exception("Failed to persist query log feedback update")


def load_all():
    """Return every logged record, for analytics or evaluate.py."""
    if not os.path.exists(config.QUERY_LOG_PATH):
        return []
    records = []
    with open(config.QUERY_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed query log line")
    return records
