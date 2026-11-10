"""
Campus Events — student page and admin panel.

Student page: hero for the next event, category chips + All/This week/This month,
a uniform card grid, collapsed past events, and a detail dialog (a bottom sheet
on phones). Data lives in SQLite (core/events_db.py); the assistant reads the
same table (core/event_context.py).

Everything an admin types is escaped before it is put into HTML.
"""

import base64
import datetime as dt
import html
import io
import os

import streamlit as st
from PIL import Image

from core import config, events_db as db
from core.logging_setup import logger
from core.posters import PosterError, delete_poster, poster_path, save_poster
from locations import get_location, list_locations
from ui.layout import page_footer, page_header
from ui.styles import CATEGORY_COLOURS

esc = html.escape




# ── small helpers ─────────────────────────────────────────────────────────
@st.cache_resource
def _init_db_once():
    db.init_db()
    return True


@st.cache_data(show_spinner=False)
def _poster_uri(path, mtime, width):
    """A downscaled data: URI for one poster file (re-cached when the file changes)."""
    try:
        img = Image.open(path).convert("RGB")
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        logger.exception("Could not read poster %s", path)
        return None


def _poster_style(event, width=700):
    """CSS background for a poster; falls back to a category colour (never a broken image)."""
    path = poster_path(event["poster"])
    uri = _poster_uri(path, os.path.getmtime(path), width) if path else None
    if uri:
        return f"background-image:url('{uri}');", True
    return f"background:{CATEGORY_COLOURS.get(event['category'], CATEGORY_COLOURS['Other'])};", False


def _venue(event):
    return event["venue_text"] or ""


def _go_to_place(location_id):
    loc = get_location(location_id)
    if loc:
        st.session_state.places_query = loc["name"]
        st.session_state.current_page = "Places"


def _known_location(event):
    return get_location(event["venue_location_id"]) if event["venue_location_id"] else None


def _short_title(event):
    return esc(event["title"].split(":")[0][:28])


# ── student page ──────────────────────────────────────────────────────────
@st.dialog("Event details", width="large")
def _event_dialog(event_id):
    event = db.get_event(event_id)
    if not event or event["status"] != "published":
        st.info("This event is no longer available.")
        return
    style, has_img = _poster_style(event, 1200)
    inner = "" if has_img else f"<b>{esc(event['title'])}</b>"
    st.markdown(f"<div class='ev-dlg-poster' style=\"{style}\">{inner}</div>", unsafe_allow_html=True)
    past = db.is_past(event)
    st.markdown(f"<span class='chip'>{esc(event['category'])}</span> "
                + (f"<span class='badge badge-bad'>{db.countdown_label(event)}</span>"
                   if not past else "<span class='badge badge-muted'>Ended</span>"),
                unsafe_allow_html=True)
    st.markdown(f"<div class='dlg-title'>{esc(event['title'])}</div>",
                unsafe_allow_html=True)
    venue = _venue(event)
    st.markdown(
        "<div class='ev-dlg-box'>"
        f"<b>📅 {db.format_date(event)}</b><br><span class='dlg-text'>{db.format_time(event)}</span>"
        + (f"<hr class='dlg-sep'><b>📍 {esc(venue)}</b>" if venue else "")
        + "</div>", unsafe_allow_html=True)
    loc = _known_location(event)
    if loc and st.button("Where is this?", key=f"dlg_where_{event_id}", type="tertiary"):
        _go_to_place(event["venue_location_id"])
        st.rerun()
    if event["description"]:
        st.markdown(f"<div class='dlg-text'>{esc(event['description']).replace(chr(10), '<br>')}</div>",
                    unsafe_allow_html=True)
    if event["organiser"]:
        st.markdown(f"<div class='dlg-muted'>Organised by <b>{esc(event['organiser'])}</b></div>",
                    unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Add to calendar", db.ics(event), file_name=f"{event['title'][:40]}.ics".replace(" ", "_"),
                           mime="text/calendar", key=f"dlg_ics_{event_id}", use_container_width=True)
    with c2:
        if event["registration_url"] and not past:
            st.link_button("Register", event["registration_url"], type="primary", use_container_width=True)


def _render_hero(event, now):
    style, has_img = _poster_style(event, 1200)
    with st.container(key="ev_hero"):
        left, right = st.columns([1, 1])
        with left:
            inner = "" if has_img else f"<span>{esc(event['title'])}</span>"
            st.markdown(f"<div class='ev-hero-poster' style=\"{style}\">{inner}</div>", unsafe_allow_html=True)
        with right:
            venue = _venue(event)
            rows = [f"<div class='ev-hero-row'>📅 {db.format_date(event)}</div>",
                    f"<div class='ev-hero-row'>🕒 {db.format_time(event)}</div>"]
            if venue:
                rows.append(f"<div class='ev-hero-row'>📍 {esc(venue)}</div>")
            desc = esc(event["description"][:220]) + ("…" if len(event["description"]) > 220 else "")
            organiser = f" Organised by {esc(event['organiser'])}." if event["organiser"] else ""
            st.markdown(
                "<div class='ev-hero-text'>"
                f"<span class='ev-badge-red'>Next up · {db.countdown_label(event, now).lower()}</span>"
                f"<span class='ev-badge-blue'>{esc(event['category'])}</span>"
                f"<h2>{esc(event['title'])}</h2>{''.join(rows)}"
                f"<div class='ev-hero-desc'>{desc}{organiser}</div></div>", unsafe_allow_html=True)
            b1, b2, b3 = st.columns([1, 1.3, 1])
            with b1:
                if event["registration_url"]:
                    st.link_button("Register", event["registration_url"], type="primary")
            with b2:
                st.download_button("Add to calendar", db.ics(event), file_name="event.ics", mime="text/calendar",
                                   key="hero_ics")
            with b3:
                if _known_location(event):
                    st.button("Where is this?", key="hero_where", type="tertiary",
                              on_click=_go_to_place, args=(event["venue_location_id"],))


def _card_html(event, past=False):
    style, has_img = _poster_style(event)
    start = db.parse(event["start_at"])
    when = f"{start.strftime('%a')} · {db.format_time(event)}"
    venue = _venue(event)
    inner = "" if has_img else f"<b>{esc(event['title'])}</b>"
    return (
        f"<div class='ev-card{' ev-past' if past else ''}'>"
        f"<div class='ev-poster' style=\"{style}\">"
        f"<div class='ev-date'><b>{start.day}</b><span>{start.strftime('%b').upper()}</span></div>{inner}</div>"
        "<div class='ev-body'>"
        f"<span class='chip'>{esc(event['category'])}</span>"
        f"<div class='ev-title'>{esc(event['title'])}</div>"
        f"<div class='ev-meta'>🕒 {esc(when)}</div>"
        f"<div class='ev-meta'>📍 {esc(venue) if venue else '&nbsp;'}</div></div></div>"
        "<div class='ev-orgline'></div>"
    )


def _render_grid(events, prefix, past=False):
    for i in range(0, len(events), 3):
        cols = st.columns(3, gap="medium")
        for col, event in zip(cols, events[i:i + 3]):
            with col, st.container(key=f"evc-{prefix}-{event['id']}"):
                st.markdown(_card_html(event, past), unsafe_allow_html=True)
                org, more = st.columns([3, 1.2])
                org.markdown(f"<div class='ev-org'>{esc(event['organiser']) or '&nbsp;'}</div>", unsafe_allow_html=True)
                with more:
                    if st.button("Details", key=f"{prefix}_{event['id']}", type="tertiary"):
                        _event_dialog(event["id"])


def _matches_search(event, q):
    hay = " ".join([event["title"], event["venue_text"], event["organiser"], event["description"],
                    event["category"]]).lower()
    return q.lower() in hay


def render_events_page():
    _init_db_once()
    now = db.now()

    head, search = st.columns([3, 1.4])
    with head:
        page_header("Events", "Talks, career fairs, sports and club activities happening on campus.",
                    eyebrow="MMU Melaka · Campus Life")
    with search:
        query = st.text_input("Search", placeholder="🔎 Search events, venues, organisers", key="ev_search",
                              label_visibility="collapsed").strip()

    upcoming = db.upcoming_events(now)
    past = db.past_events(now)

    if not upcoming and not past:
        st.markdown("<div class='empty'>🗓️ No upcoming events — check back soon.</div>", unsafe_allow_html=True)
        page_footer()
        return

    hero = None if query else db.pick_hero(upcoming)
    if hero:
        _render_hero(hero, now)

    category = st.pills("Category", ["All"] + config.EVENT_CATEGORIES, default="All", key="ev_cat",
                        label_visibility="collapsed") or "All"
    when = st.segmented_control("When", ["All upcoming", "This week", "This month"], default="All upcoming",
                                key="ev_when", label_visibility="collapsed") or "All upcoming"

    grid = [e for e in upcoming if not (hero and e["id"] == hero["id"])]
    if category != "All":
        grid = [e for e in grid if e["category"] == category]
    if when == "This week":
        s, e_ = db.week_bounds(now)
        grid = [e for e in grid if db.overlaps(e, s, e_)]
    elif when == "This month":
        s, e_ = db.month_bounds(now)
        grid = [e for e in grid if db.overlaps(e, s, e_)]
    if query:
        grid = [e for e in grid if _matches_search(e, query)]

    st.markdown(f"#### Upcoming · {len(grid)} event{'s' if len(grid) != 1 else ''}")
    if grid:
        _render_grid(grid, "evdet")
    elif upcoming:
        st.markdown("<div class='empty'>No events match your filters.</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='empty'>🗓️ No upcoming events — check back soon.</div>", unsafe_allow_html=True)

    shown_past = [e for e in past if not query or _matches_search(e, query)]
    if shown_past:
        with st.expander(f"Past events · {len(shown_past)} event{'s' if len(shown_past) != 1 else ''} "
                         "· moved here automatically after they end", expanded=False):
            st.caption("Shown greyed out, newest first.")
            _render_grid(shown_past[:config.PAST_EVENTS_LIMIT], "evpast", past=True)
    st.caption("All times are Malaysia time (UTC+8). Event details are provided by organisers; check with them for changes.")
    page_footer()


# ── admin ─────────────────────────────────────────────────────────────────
@st.dialog("Delete this event?")
def _confirm_delete(event_id):
    event = db.get_event(event_id)
    if not event:
        st.info("Already deleted.")
        return
    st.write(f"**{event['title']}** will be removed permanently.")
    c1, c2 = st.columns(2)
    if c1.button("Delete", type="primary", key=f"yes_del_{event_id}", use_container_width=True):
        db.delete_event(event_id)
        if not db.poster_in_use_elsewhere(event["poster"], event_id):
            delete_poster(event["poster"])
        st.rerun()
    if c2.button("Cancel", key=f"no_del_{event_id}", use_container_width=True):
        st.rerun()


def _location_options():
    options = {"": "— none —"}
    for loc in list_locations():
        options[loc["id"]] = f"{loc['name']}" + (f" ({loc['code']})" if loc.get("code") and loc["code"] != loc["name"] else "")
    return options


def _event_form(event):
    """Create/edit form. `event` is None for a new event."""
    new = event is None
    base = event or {"title": "", "category": config.EVENT_CATEGORIES[0], "all_day": 0, "venue_location_id": "",
                     "venue_text": "", "description": "", "organiser": "", "registration_url": "", "poster": "",
                     "status": "draft", "pinned": 0,
                     "start_at": db.now().replace(minute=0, second=0).isoformat(timespec="minutes"),
                     "end_at": (db.now().replace(minute=0, second=0) + dt.timedelta(hours=2)).isoformat(timespec="minutes")}
    start, end = db.parse(base["start_at"]), db.parse(base["end_at"])
    options = _location_options()
    ids = list(options)

    with st.form(f"event_form_{'new' if new else base['id']}"):
        title = st.text_input("Title *", value=base["title"])
        c1, c2 = st.columns(2)
        category = c1.selectbox("Category", config.EVENT_CATEGORIES, index=config.EVENT_CATEGORIES.index(base["category"]))
        status = c2.radio("Status", ["draft", "published"], index=["draft", "published"].index(base["status"]), horizontal=True)
        all_day = st.checkbox("All day (no specific time)", value=bool(base["all_day"]))
        d1, d2, d3, d4 = st.columns(4)
        start_d = d1.date_input("Start date", value=start.date())
        start_t = d2.time_input("Start time", value=start.time())
        end_d = d3.date_input("End date", value=end.date())
        end_t = d4.time_input("End time", value=end.time())
        v1, v2 = st.columns(2)
        venue_id = v1.selectbox("Venue (from Places)", ids, format_func=options.get,
                                index=ids.index(base["venue_location_id"]) if base["venue_location_id"] in ids else 0)
        venue_text = v2.text_input("Venue text (shown to students)", value=base["venue_text"],
                                   help="Leave blank to use the Places name.")
        organiser = st.text_input("Organiser", value=base["organiser"])
        url = st.text_input("Registration link", value=base["registration_url"], placeholder="https://…")
        description = st.text_area("Description", value=base["description"])
        poster_file = st.file_uploader("Poster image (PNG/JPEG/WEBP — resized to 1200 px wide)", type=["png", "jpg", "jpeg", "webp"])
        remove_poster = st.checkbox("Remove current poster", value=False) if base["poster"] else False
        pinned = st.checkbox("📌 Pin (feature in the hero)", value=bool(base["pinned"]))
        submitted = st.form_submit_button("💾 Save event", type="primary")
    if st.button("Cancel", key="ev_cancel"):
        st.session_state.ev_edit = None
        st.rerun()
    if not submitted:
        return

    if all_day:
        start_dt, end_dt = dt.datetime.combine(start_d, dt.time(0, 0)), dt.datetime.combine(end_d, dt.time(23, 59))
    else:
        start_dt, end_dt = dt.datetime.combine(start_d, start_t), dt.datetime.combine(end_d, end_t)
    if venue_id and not venue_text.strip():
        venue_text = options[venue_id].split(" (")[0]

    poster = "" if remove_poster else base["poster"]
    new_poster = None
    if poster_file is not None:
        try:
            new_poster = save_poster(poster_file.getvalue())
        except PosterError as exc:
            st.error(str(exc))
            return
        poster = new_poster

    fields = dict(title=title, category=category, start_at=start_dt.isoformat(timespec="minutes"),
                  end_at=end_dt.isoformat(timespec="minutes"), all_day=all_day, venue_location_id=venue_id,
                  venue_text=venue_text, description=description, organiser=organiser, registration_url=url,
                  poster=poster, status=status, pinned=pinned)
    problems = db.validate(fields)
    if problems:
        if new_poster:
            delete_poster(new_poster)
        for p in problems:
            st.error(p)
        return
    if new:
        db.create_event(**fields)
    else:
        db.update_event(base["id"], **fields)
        if base["poster"] and base["poster"] != poster and not db.poster_in_use_elsewhere(base["poster"], base["id"]):
            delete_poster(base["poster"])
    st.session_state.ev_edit = None
    st.session_state.ev_flash = f"Saved “{title.strip()}” ({status})."
    st.rerun()


def render_admin_events():
    _init_db_once()
    st.session_state.setdefault("ev_edit", None)
    if st.session_state.get("ev_flash"):
        st.success(st.session_state.pop("ev_flash"))

    if st.session_state.ev_edit is not None:
        event = None if st.session_state.ev_edit == "new" else db.get_event(st.session_state.ev_edit)
        st.subheader("➕ New event" if event is None else f"✏️ Edit: {event['title']}")
        _event_form(event)
        return

    top1, top2 = st.columns([4, 1])
    top1.subheader("🗂️ Events")
    if top2.button("➕ New event", type="primary", use_container_width=True):
        st.session_state.ev_edit = "new"
        st.rerun()

    events = sorted(db.list_events(), key=lambda e: e["start_at"], reverse=True)
    if not events:
        st.info("No events yet.")
        return
    now = db.now()
    for e in events:
        state = "draft" if e["status"] == "draft" else ("ended" if db.is_past(e, now) else "published")
        c = st.columns([5, 2.2, 1.2, 0.8, 0.8, 0.8, 0.8])
        c[0].markdown(f"**{esc(e['title'])}**" + ("  📌" if e["pinned"] else ""))
        c[1].caption(f"{db.format_date(e)} · {e['category']}")
        c[2].caption({"draft": "📝 Draft", "ended": "⏹️ Ended", "published": "✅ Live"}[state])
        if c[3].button("✏️", key=f"ed_{e['id']}", help="Edit"):
            st.session_state.ev_edit = e["id"]
            st.rerun()
        if c[4].button("📄", key=f"dup_{e['id']}", help="Duplicate (as a draft)"):
            db.duplicate_event(e["id"])
            st.rerun()
        if c[5].button("📌", key=f"pin_{e['id']}", help="Pin / unpin"):
            fields = {k: e[k] for k in db.FIELDS}
            fields["pinned"] = 0 if e["pinned"] else 1
            db.update_event(e["id"], **fields)
            st.rerun()
        if c[6].button("🗑️", key=f"del_{e['id']}", help="Delete"):
            _confirm_delete(e["id"])
