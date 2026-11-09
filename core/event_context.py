"""
Assistant integration for campus events.

Events expire, so they are NOT in the vector store: when a question is about
events/activities this module reads the database directly and returns ONE
structured passage tagged "Campus Events", with today's date in it. Only
published events that have not ended are ever listed, so a past event can
never be presented as upcoming.
"""

import datetime as dt
import re

from langchain_core.documents import Document

from core import config, events_db as db

# Unambiguous event wording.
_STRONG = re.compile(
    r"\b(events?|activit(?:y|ies)|happening|what'?s on|what is on|going on|talks|seminars?|webinars?|"
    r"career fairs?|job fairs?|futsal|hack ?night|showcase|cv clinic|campus life)\b", re.I)
# Words that only mean "event" when the user also talks about time
# ("Where is the Mechanical Workshop?" is a location question, not an event one).
_WEAK = re.compile(r"\b(workshops?|fairs?|talk|competitions?|tournaments?|sports?|clubs?|societ(?:y|ies))\b", re.I)
_TIME = re.compile(r"\b(today|tonight|tomorrow|this week|next week|this weekend|this month|next month|upcoming|"
                   r"coming up|soon|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)

_CATEGORY_WORDS = [
    ("Career", r"career|job|internship|cv|interview"),
    ("Sports", r"sports?|futsal|football|tournament|cup|badminton|basketball"),
    ("Academic Talk", r"talks?|seminars?|webinars?|lectures?|academic|showcase|research"),
    ("Clubs & Societies", r"clubs?|societ(?:y|ies)|hack ?night"),
    ("Faculty", r"faculty"),
]
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]
_MAX_LISTED = 8


def is_event_question(text):
    text = text or ""
    return bool(_STRONG.search(text) or (_WEAK.search(text) and _TIME.search(text)))


def _category(text):
    for name, pattern in _CATEGORY_WORDS:
        if re.search(rf"\b({pattern})\b", text, re.I):
            return name
    return None


def parse_range(text, at):
    """(start, end, label) for the date range the question asks about, or None."""
    t = text.lower()
    day = at.replace(hour=0, minute=0, second=0)
    one = dt.timedelta(days=1)
    if "tomorrow" in t:
        return day + one, day + 2 * one, "tomorrow"
    if re.search(r"\b(today|tonight)\b", t):
        return day, day + one, "today"
    if "this weekend" in t:
        sat = db.week_bounds(at)[0] + dt.timedelta(days=5)
        return sat, sat + 2 * one, "this weekend"
    if "next week" in t:
        s, e = db.week_bounds(at)
        return s + 7 * one, e + 7 * one, "next week"
    if "this week" in t:
        s, e = db.week_bounds(at)
        return s, e, "this week"
    if "next month" in t:
        s, e = db.month_bounds(at)
        return e, db.month_bounds(e)[1], "next month"
    if "this month" in t:
        s, e = db.month_bounds(at)
        return s, e, "this month"
    for name in _MONTHS:  # "20 nov", "20 november", "november 20"
        short = name[:3]
        m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{name}|{short})\b|\b(?:{name}|{short})\s+(\d{{1,2}})\b", t)
        if m:
            d, month = int(m.group(1) or m.group(2)), _MONTHS.index(name) + 1
            try:
                target = dt.datetime(at.year if (month, d) >= (at.month, at.day) else at.year + 1, month, d)
            except ValueError:
                continue
            return target, target + one, f"{d} {name.title()}"
    for i, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}\b", t):
            target = day + dt.timedelta(days=(i - at.weekday()) % 7)
            return target, target + one, f"{name.title()} {target.day} {target.strftime('%B')}"
    return None


def _describe(event, at):
    parts = [f"{event['title']} — {db.format_date(event)}, {db.format_time(event)} ({db.countdown_label(event, at)}).",
             f"Category: {event['category']}."]
    if event["venue_text"]:
        parts.append(f"Venue: {event['venue_text']}.")
    if event["organiser"]:
        parts.append(f"Organiser: {event['organiser']}.")
    if event["registration_url"]:
        parts.append(f"Register: {event['registration_url']}")
    if event["description"]:
        parts.append(f"Details: {event['description']}")
    return " ".join(parts)


def events_document(question, at=None):
    """The 'Campus Events' passage for an event question, or None if it isn't one."""
    if not is_event_question(question):
        return None
    db.init_db()
    at = at or db.now()
    span = parse_range(question, at)
    category = _category(question)

    upcoming = db.upcoming_events(at)
    matches = [e for e in upcoming if (not category or e["category"] == category)]
    if span:
        in_range = [e for e in matches if db.overlaps(e, span[0], span[1])]
        scope = span[2]
    else:
        in_range, scope = matches, "the coming weeks"
    outside = [e for e in matches if e not in in_range][:3] if span else []

    head = (f"Today is {at.strftime('%A')}, {at.day} {at.strftime('%B %Y')} (Malaysia time). "
            f"Campus events calendar — UPCOMING published events for {scope}"
            + (f", category {category}" if category else "") + ". Past events are never listed.")
    lines = [head]
    if in_range:
        lines += [f"{i}. {_describe(e, at)}" for i, e in enumerate(in_range[:_MAX_LISTED], 1)]
    else:
        lines.append(f"No upcoming published events were found for {scope}"
                     + (f" in category {category}" if category else "") + ".")
    if outside:
        lines.append("Next upcoming events OUTSIDE the requested range (say so if you mention them):")
        lines += [f"- {_describe(e, at)}" for e in outside]

    return Document(
        page_content="\n".join(lines),
        metadata={"type": "event", "source_file": "Campus Events", "page": "N/A"},
    )
