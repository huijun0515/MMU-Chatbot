"""
Announcements / Campus Events feature.

Student side : a poster gallery of upcoming activities.
Admin side   : publish a poster (image + title + description + date) and delete old ones.

Everything is stored on disk so it survives restarts:
  ./announcements/announcements.json   <- list of announcement records
  ./announcements/<image files>        <- the uploaded posters
"""

import os
import json
import uuid
import datetime
import streamlit as st

ANNOUNCE_DIR = "./announcements"
ANNOUNCE_JSON = os.path.join(ANNOUNCE_DIR, "announcements.json")


# ──────────────────────────────────────────────────────────────
#  Storage helpers
# ──────────────────────────────────────────────────────────────
def _ensure_dir():
    os.makedirs(ANNOUNCE_DIR, exist_ok=True)


def _load():
    if not os.path.exists(ANNOUNCE_JSON):
        return []
    try:
        with open(ANNOUNCE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(items):
    _ensure_dir()
    with open(ANNOUNCE_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def list_announcements():
    """Newest event date first."""
    items = _load()
    return sorted(items, key=lambda x: x.get("date", ""), reverse=True)


def add_announcement(title, description, date_str, image_file):
    _ensure_dir()
    item_id = str(uuid.uuid4())[:8]

    image_name = ""
    if image_file is not None:
        ext = os.path.splitext(image_file.name)[1].lower() or ".png"
        image_name = f"poster_{item_id}{ext}"
        with open(os.path.join(ANNOUNCE_DIR, image_name), "wb") as f:
            f.write(image_file.getbuffer())

    items = _load()
    items.append({
        "id": item_id,
        "title": title.strip(),
        "description": description.strip(),
        "date": date_str,
        "image": image_name,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    _save(items)
    return item_id


def delete_announcement(item_id):
    items = _load()
    keep = []
    for it in items:
        if it.get("id") == item_id:
            img = it.get("image")
            if img:
                p = os.path.join(ANNOUNCE_DIR, img)
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        else:
            keep.append(it)
    _save(keep)


def _pretty_date(d):
    try:
        return datetime.datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return d


# ──────────────────────────────────────────────────────────────
#  Student-facing gallery
# ──────────────────────────────────────────────────────────────
_ANN_CSS = """
<style>
.ann-meta {
    display:inline-block; background:#EEF3FF; color:#0033A0;
    font-size:.72rem; font-weight:700; padding:3px 10px;
    border-radius:999px; margin:6px 0 8px;
}
.ann-title { font-size:1.05rem; font-weight:700; color:#0f172a; line-height:1.3; margin-bottom:6px; }
.ann-desc  { font-size:.85rem; color:#475569; line-height:1.5; }
.ann-empty {
    text-align:center; padding:60px 20px; color:#64748b;
    border:2px dashed #cbd5e1; border-radius:16px; background:#f8fafc;
}
</style>
"""


def _render_card(item):
    with st.container(border=True):
        img = item.get("image")
        if img:
            img_path = os.path.join(ANNOUNCE_DIR, img)
            if os.path.exists(img_path):
                st.image(img_path, use_container_width=True)
        st.markdown(f"<span class='ann-meta'>📅 {_pretty_date(item.get('date',''))}</span>",
                    unsafe_allow_html=True)
        st.markdown(f"<div class='ann-title'>{item.get('title','')}</div>",
                    unsafe_allow_html=True)
        if item.get("description"):
            st.markdown(f"<div class='ann-desc'>{item.get('description')}</div>",
                        unsafe_allow_html=True)


def render_announcements_page():
    st.markdown(_ANN_CSS, unsafe_allow_html=True)
    st.markdown("<h1 style='text-align:center;color:#0033A0;'>📢 Campus Announcements</h1>",
                unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;'>What's happening around Multimedia University.</p>",
                unsafe_allow_html=True)
    st.markdown("---")

    items = list_announcements()
    if not items:
        st.markdown(
            "<div class='ann-empty'>🗓️ No announcements yet.<br>"
            "Check back soon for upcoming events and activities!</div>",
            unsafe_allow_html=True,
        )
        return

    cols_per_row = 3
    for i in range(0, len(items), cols_per_row):
        row = items[i:i + cols_per_row]
        cols = st.columns(cols_per_row, gap="large")
        for col, item in zip(cols, row):
            with col:
                _render_card(item)


# ──────────────────────────────────────────────────────────────
#  Admin management (called from the Admin panel)
# ──────────────────────────────────────────────────────────────
def render_admin_announcements():
    st.subheader("➕ Publish a New Announcement")

    with st.form("new_announcement", clear_on_submit=True):
        title = st.text_input("Title *", placeholder="e.g. FIST Tech Fair 2026")
        description = st.text_area("Description", placeholder="Short details students should know…")
        c1, c2 = st.columns(2)
        with c1:
            event_date = st.date_input("Event date *", value=datetime.date.today())
        with c2:
            image_file = st.file_uploader("Poster image", type=["png", "jpg", "jpeg", "webp"])
        submitted = st.form_submit_button("📢 Publish", type="primary")

    if submitted:
        if not title.strip():
            st.error("Please enter a title.")
        else:
            add_announcement(title, description, event_date.isoformat(), image_file)
            st.success(f"✅ Published '{title.strip()}'.")
            st.rerun()

    st.divider()
    st.subheader("🗂️ Published Announcements")

    items = list_announcements()
    if not items:
        st.info("No announcements published yet.")
        return

    for it in items:
        c1, c2, c3 = st.columns([5, 2, 1])
        c1.write(f"**{it.get('title','(untitled)')}**")
        c2.write(f"📅 {_pretty_date(it.get('date',''))}")
        if c3.button("🗑️", key=f"del_ann_{it['id']}", help="Delete this announcement"):
            delete_announcement(it["id"])
            st.success("Deleted.")
            st.rerun()