"""
Analytics over the query log, for the admin Insights tab. Pure pandas — no Streamlit.
"""

import re

import pandas as pd

from core import config, query_log


def load_frame():
    rows = query_log.load_all()
    cols = ["id", "timestamp", "question", "answer", "intent", "language", "input_mode", "voice_edited", "sources", "feedback"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["date"] = df["timestamp"].dt.date
    df["unanswered"] = df["answer"].str.lower().str.contains(config.NO_ANSWER_MARKER.lower(), regex=False, na=False)
    return df


def _norm(q):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (q or "").lower())).strip()


def summarize(df, days=None):
    """A dict of small DataFrames/numbers for the dashboard."""
    if days and not df.empty:
        since = pd.Timestamp.now() - pd.Timedelta(days=days)
        df = df[df["timestamp"] >= since]
    out = {"total": len(df)}
    if df.empty:
        return out
    out["per_day"] = df.groupby("date").size().rename("questions").to_frame()
    out["intent"] = df["intent"].value_counts().rename_axis("intent").to_frame("questions")
    out["language"] = df["language"].value_counts().rename_axis("language").to_frame("questions")
    out["input_mode"] = df["input_mode"].value_counts().rename_axis("input").to_frame("questions")

    knowledge = df[df["intent"] == "knowledge"].copy()
    knowledge["q"] = knowledge["question"].map(_norm)
    top = (knowledge.groupby("q").agg(times=("q", "size"), example=("question", "first"),
                                      unanswered=("unanswered", "sum"))
           .sort_values("times", ascending=False).head(15).reset_index(drop=True))
    out["top_questions"] = top[["example", "times", "unanswered"]]

    gaps = knowledge[knowledge["unanswered"]]
    out["gaps"] = (gaps.groupby("q").agg(times=("q", "size"), example=("question", "first"),
                                         last_asked=("timestamp", "max"))
                   .sort_values("times", ascending=False).reset_index(drop=True)[["example", "times", "last_asked"]])
    out["unanswered_rate"] = float(knowledge["unanswered"].mean()) if len(knowledge) else 0.0

    rated = df[df["feedback"].notna()]
    out["rated"] = len(rated)
    out["thumbs_up"] = int((rated["feedback"] == "up").sum())
    out["thumbs_down"] = int((rated["feedback"] == "down").sum())
    out["up_rate"] = out["thumbs_up"] / len(rated) if len(rated) else None
    return out


def export_csv(df):
    cols = ["id", "timestamp", "question", "answer", "intent", "language", "input_mode", "voice_edited", "feedback", "unanswered"]
    return df[[c for c in cols if c in df.columns]].to_csv(index=False).encode("utf-8-sig")
