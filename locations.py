"""
Structured Campus Location knowledge base  —  the "hybrid KB" core.

Each location (classroom, lab, office, facility, landmark) is a structured
record. Every record is turned into a rich text document and embedded into the
SAME Chroma vector store as the handbook PDFs, so one semantic search covers
both official regulations and campus navigation. That is the hybrid design.

Storage (survives restarts):
  ./locations/locations.json   <- the structured records
  ./locations/<image files>    <- one optional photo per location

Public pieces used elsewhere:
  render_directory_page()          -> student-facing "Places" browser
  render_admin_locations()         -> admin add/edit/delete + sync
  location_card_from_context(docs) -> pulls a location card (name+image) out of
                                      retrieved context, for showing in chat (#8)
"""

import os
import re
import json
import streamlit as st
from langchain_core.documents import Document

from core import config
from core.vector_store import get_vector_db, embed_with_retry
from core.logging_setup import logger
from core.location_import import read_locations_xlsx

LOCATIONS_DIR = config.LOCATIONS_DIR
LOCATIONS_JSON = os.path.join(LOCATIONS_DIR, "locations.json")

PLACES_PAGE_LIMIT = 60
CATEGORIES = ["Classroom", "Lecture Hall", "Tutorial Room", "Lab", "Office", "Faculty", "Facility",
              "Building", "Hostel", "Landmark", "Other"]

# The three invented placeholder records this project used to ship with. The
# Excel file now has real versions of them, so any copy left in locations.json is dropped on import.
LEGACY_SEED_IDS = {"library", "finance-office", "ssc"}

# Verification status -> (badge label, colours, sentence the assistant is told)
_STATUS_STYLES = {
    "official": ("Official", "#166534", "#dcfce7",
                 "Official MMU source."),
    "partial": ("Official (partial)", "#166534", "#dcfce7",
                "Official MMU source, but only partly documented."),
    "unverified": ("Unverified", "#854d0e", "#fef9c3",
                   "UNVERIFIED: taken from an older unofficial list (2014/15). "
                   "This room information may have changed or be outdated."),
    "conflict": ("Conflict - check on site", "#991b1b", "#fee2e2",
                 "CONFLICT: sources disagree about where this is. "
                 "It must be checked on site."),
    "original": ("Original file", "#1e40af", "#dbeafe",
                 "From the project's original location list (not independently verified)."),
}


def _status_key(status):
    s = (status or "").lower()
    if s.startswith("official source (partial"):
        return "partial"
    if s.startswith("official"):
        return "official"
    if s.startswith("unverified"):
        return "unverified"
    if s.startswith("conflict"):
        return "conflict"
    if s.startswith("from your original") or s.startswith("original"):
        return "original"
    return None


def status_sentence(status):
    key = _status_key(status)
    return _STATUS_STYLES[key][3] if key else ""


def status_badge_html(status):
    key = _status_key(status)
    if not key:
        return ""
    label, fg, bg, _ = _STATUS_STYLES[key]
    return (f"<span style='display:inline-block;background:{bg};color:{fg};font-size:.7rem;"
            f"font-weight:700;padding:2px 9px;border-radius:999px;margin:0 6px 6px 0;'>{label}</span>")


# ──────────────────────────────────────────────────────────────
#  Storage
# ──────────────────────────────────────────────────────────────
def _ensure_dir():
    os.makedirs(LOCATIONS_DIR, exist_ok=True)


def _load():
    _ensure_dir()
    if not os.path.exists(LOCATIONS_JSON):
        return import_from_excel() if os.path.exists(config.LOCATIONS_XLSX) else []
    try:
        with open(LOCATIONS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load %s — locations list will appear empty", LOCATIONS_JSON)
        return []


def _save(items):
    _ensure_dir()
    with open(LOCATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def import_from_excel(path=None):
    """
    Upsert every row of the Excel file into locations.json (by room code /
    id — re-importing never duplicates) and return the full list. Records
    that are not in the file (e.g. added in the admin panel) are kept, apart
    from the legacy placeholder seed records. Does NOT touch the vector DB;
    call resync_all() afterwards.
    """
    imported = read_locations_xlsx(path or config.LOCATIONS_XLSX)
    existing = {}
    if os.path.exists(LOCATIONS_JSON):
        try:
            with open(LOCATIONS_JSON, "r", encoding="utf-8") as f:
                existing = {r["id"]: r for r in json.load(f)}
        except (OSError, json.JSONDecodeError):
            logger.exception("Could not read %s before import", LOCATIONS_JSON)
    for loc_id in LEGACY_SEED_IDS:
        existing.pop(loc_id, None)
    for rec in imported:
        old = existing.get(rec["id"])
        if old and old.get("image"):
            rec["image"] = old["image"]  # keep a photo added in the admin panel
        existing[rec["id"]] = rec
    items = list(existing.values())
    _save(items)
    return items


def list_locations():
    return sorted(_load(), key=lambda x: x.get("name", "").lower())


def get_location(loc_id):
    return next((x for x in _load() if x.get("id") == loc_id), None)


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "location"


def image_path(image_name):
    if not image_name:
        return None
    p = os.path.join(LOCATIONS_DIR, image_name)
    return p if os.path.exists(p) else None


# ──────────────────────────────────────────────────────────────
#  Vector-store sync (the hybrid part)
# ──────────────────────────────────────────────────────────────
def location_to_document(rec):
    """Build the Document a location record is embedded as. Public: also
    used by core/retrieval.py to inject an exact-match location into context.
    Empty fields are omitted, never filled in. The verification status is part
    of the text so the model sees it and can qualify its answer."""
    aliases = ", ".join(rec.get("aliases", []) or [])
    name = rec.get("name", "")
    head = f"Campus location: {name}"
    if aliases:
        head += f" (also known as: {aliases})"
    lines = [head + "."]
    code = rec.get("code", "")
    if code and code != name:
        lines.append(f"Room code: {code}.")
    for label, key in (("Category", "category"), ("Building / block", "building"), ("Floor", "floor"),
                       ("Opening hours", "opening_hours"), ("Contact", "contact"),
                       ("Description", "description"), ("How to get there", "directions"),
                       ("Nearby landmarks", "landmarks"), ("Notes", "notes")):
        if rec.get(key):
            lines.append(f"{label}: {rec[key]}")
    sentence = status_sentence(rec.get("verification_status"))
    if sentence:
        lines.append(f"Information status: {sentence}")
    text = "\n".join(lines)

    meta = {
        "type": "location",
        "loc_id": rec["id"],
        "name": name,
        "building": rec.get("building", ""),
        "floor": rec.get("floor", ""),
        "image": rec.get("image", ""),
        "status": rec.get("verification_status", ""),
        "opening_hours": rec.get("opening_hours", ""),
        "contact": rec.get("contact", ""),
        "source_file": "Campus Directory",
    }
    return Document(page_content=text, metadata=meta)


def _delete_from_vectordb(vector_db, loc_id):
    try:
        vector_db._collection.delete(where={"loc_id": loc_id})
    except Exception:
        logger.exception("Failed to delete location '%s' from the vector store", loc_id)


def upsert_location(rec, image_file=None):
    """Create or update one location, then sync it into the vector store."""
    _ensure_dir()
    if image_file is not None:
        ext = os.path.splitext(image_file.name)[1].lower() or ".png"
        fname = f"{rec['id']}{ext}"
        with open(os.path.join(LOCATIONS_DIR, fname), "wb") as f:
            f.write(image_file.getbuffer())
        rec["image"] = fname

    items = [x for x in _load() if x.get("id") != rec["id"]]
    items.append(rec)
    _save(items)

    vdb = get_vector_db()
    _delete_from_vectordb(vdb, rec["id"])
    embed_with_retry(vdb, [location_to_document(rec)])


def delete_location(loc_id):
    items = _load()
    rec = next((x for x in items if x.get("id") == loc_id), None)
    if rec and rec.get("image"):
        p = os.path.join(LOCATIONS_DIR, rec["image"])
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    _save([x for x in items if x.get("id") != loc_id])
    _delete_from_vectordb(get_vector_db(), loc_id)


def resync_all():
    """Wipe all location docs from the vector store and re-add from JSON."""
    vdb = get_vector_db()
    try:
        vdb._collection.delete(where={"type": "location"})
    except Exception:
        pass
    docs = [location_to_document(r) for r in _load()]
    if docs:
        embed_with_retry(vdb, docs)
    return len(docs)


# ──────────────────────────────────────────────────────────────
#  Chat helper (#8): find a location card in retrieved context
# ──────────────────────────────────────────────────────────────
def location_card_from_context(context_docs):
    """Card data (name, building, floor, status, hours, contact, image) for the top location doc, or None."""
    for doc in context_docs or []:
        md = getattr(doc, "metadata", {}) or {}
        if md.get("type") == "location":
            return {
                "name": md.get("name", ""),
                "building": md.get("building", ""),
                "floor": md.get("floor", ""),
                "status": md.get("status", ""),
                "opening_hours": md.get("opening_hours", ""),
                "contact": md.get("contact", ""),
                "image_path": image_path(md.get("image", "")),
            }
    return None


# ──────────────────────────────────────────────────────────────
#  Student-facing directory page
# ──────────────────────────────────────────────────────────────
_DIR_CSS = """
<style>
.loc-meta { display:inline-block; background:#EEF3FF; color:#0033A0;
    font-size:.72rem; font-weight:700; padding:3px 10px; border-radius:999px; margin:6px 0 8px; }
.loc-title { font-size:1.05rem; font-weight:700; color:#0f172a; margin-bottom:2px; }
.loc-sub { font-size:.8rem; color:#64748b; margin-bottom:6px; }
.loc-desc { font-size:.85rem; color:#475569; line-height:1.5; }
.loc-empty { text-align:center; padding:60px 20px; color:#64748b;
    border:2px dashed #cbd5e1; border-radius:16px; background:#f8fafc; }
</style>
"""


def _render_loc_card(rec):
    with st.container(border=True):
        p = image_path(rec.get("image", ""))
        if p:
            st.image(p, use_container_width=True)
        st.markdown(f"<span class='loc-meta'>{rec.get('category','')}</span>"
                    + status_badge_html(rec.get("verification_status")), unsafe_allow_html=True)
        st.markdown(f"<div class='loc-title'>{rec.get('name','')}</div>", unsafe_allow_html=True)
        where = " · ".join(x for x in (rec.get("building"), rec.get("floor")) if x)
        if where:
            st.markdown(f"<div class='loc-sub'>🏢 {where}</div>", unsafe_allow_html=True)
        if rec.get("opening_hours"):
            st.markdown(f"<div class='loc-sub'>🕒 {rec['opening_hours']}</div>", unsafe_allow_html=True)
        if rec.get("contact"):
            st.markdown(f"<div class='loc-sub'>📞 {rec['contact']}</div>", unsafe_allow_html=True)
        if rec.get("description"):
            st.markdown(f"<div class='loc-desc'>{rec['description']}</div>", unsafe_allow_html=True)
        if rec.get("directions") or rec.get("notes"):
            with st.expander("🧭 Details"):
                if rec.get("directions"):
                    st.write(rec["directions"])
                if rec.get("landmarks"):
                    st.caption(f"📍 Nearby: {rec['landmarks']}")
                if rec.get("notes"):
                    st.caption(f"ℹ️ {rec['notes']}")


def render_directory_page():
    st.markdown(_DIR_CSS, unsafe_allow_html=True)
    st.markdown("<h1 style='text-align:center;color:#0033A0;'>📍 Campus Directory</h1>",
                unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;'>Find classrooms, offices and facilities around campus.</p>",
                unsafe_allow_html=True)
    st.markdown("---")

    items = list_locations()
    if not items:
        st.markdown("<div class='loc-empty'>🗺️ No locations added yet.</div>", unsafe_allow_html=True)
        return

    c1, c2 = st.columns([2, 1])
    with c1:
        query = st.text_input("🔎 Search", placeholder="e.g. library, finance, BR1024")
    with c2:
        cats = ["All"] + sorted({r.get("category", "") for r in items if r.get("category")})
        cat = st.selectbox("Category", cats)

    def _match(rec):
        if cat != "All" and rec.get("category") != cat:
            return False
        if query:
            hay = " ".join([
                rec.get("name", ""), rec.get("code", ""), rec.get("building", ""),
                " ".join(rec.get("aliases", []) or []), rec.get("description", ""),
            ]).lower()
            if query.lower() not in hay:
                return False
        return True

    filtered = [r for r in items if _match(r)]
    if not filtered:
        st.info("No places match your search.")
        return

    shown = filtered[:PLACES_PAGE_LIMIT]
    if len(filtered) > len(shown):
        st.caption(f"Showing {len(shown)} of {len(filtered)} places — search or pick a category to narrow down.")
    cols_per_row = 3
    for i in range(0, len(shown), cols_per_row):
        row = shown[i:i + cols_per_row]
        cols = st.columns(cols_per_row, gap="large")
        for col, rec in zip(cols, row):
            with col:
                _render_loc_card(rec)


# ──────────────────────────────────────────────────────────────
#  Admin management (called from the Admin panel)
# ──────────────────────────────────────────────────────────────
def render_admin_locations():
    st.subheader("➕ Add / Update a Location")
    st.caption("If a location with the same name exists, it will be updated.")

    with st.form("new_location", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Name *", placeholder="e.g. BR1024")
            category = st.selectbox("Category", CATEGORIES)
            building = st.text_input("Building / Block", placeholder="e.g. Business Building (BR)")
            floor = st.text_input("Floor", placeholder="e.g. Level 1")
        with c2:
            aliases = st.text_input("Also known as (comma-separated)",
                                    placeholder="e.g. Business Room 1024, Lecture Hall BR1024")
            image_file = st.file_uploader("Photo", type=["png", "jpg", "jpeg", "webp"])
        description = st.text_area("Description", placeholder="What is this place?")
        directions = st.text_area("How to get there", placeholder="Step-by-step from a known landmark…")
        landmarks = st.text_input("Nearby landmarks", placeholder="e.g. opposite the cafeteria")
        submitted = st.form_submit_button("💾 Save Location", type="primary")

    if submitted:
        if not name.strip():
            st.error("Please enter a name.")
        else:
            rec = {
                "id": _slug(name),
                "name": name.strip(),
                "aliases": [a.strip() for a in aliases.split(",") if a.strip()],
                "category": category,
                "building": building.strip(),
                "floor": floor.strip(),
                "description": description.strip(),
                "directions": directions.strip(),
                "landmarks": landmarks.strip(),
                "image": "",
            }
            existing = get_location(rec["id"])
            if existing and not image_file:
                rec["image"] = existing.get("image", "")  # keep old photo on edit
            with st.spinner("Saving and syncing to the assistant…"):
                upsert_location(rec, image_file)
            st.cache_resource.clear()
            st.success(f"✅ Saved '{name.strip()}' and synced to the knowledge base.")
            st.rerun()

    st.divider()

    if os.path.exists(config.LOCATIONS_XLSX):
        st.caption(f"Source file: `{config.LOCATIONS_XLSX}`")
        if st.button("📥 Re-import from Excel", help="Upsert every row of the Excel file, then re-sync the assistant"):
            with st.spinner("Importing and re-syncing…"):
                total = len(import_from_excel())
                n = resync_all()
            st.cache_resource.clear()
            st.success(f"Imported — {total} locations on file, {n} synced to the assistant.")

    top1, top2 = st.columns([3, 1])
    with top1:
        st.subheader("🗂️ Saved Locations")
    with top2:
        if st.button("🔄 Re-sync all", help="Rebuild all location entries in the assistant"):
            with st.spinner("Re-syncing…"):
                n = resync_all()
            st.cache_resource.clear()
            st.success(f"Re-synced {n} location(s).")

    items = list_locations()
    if not items:
        st.info("No locations yet.")
        return

    for rec in items:
        with st.expander(f"📍 {rec.get('name','')}  ·  {rec.get('category','')}"):
            st.write(f"**Building:** {rec.get('building','') or '—'}  |  **Floor:** {rec.get('floor','') or '—'}")
            if rec.get("description"):
                st.write(rec["description"])
            if rec.get("directions"):
                st.caption(f"🧭 {rec['directions']}")
            p = image_path(rec.get("image", ""))
            if p:
                st.image(p, width=220)
            if st.button("🗑️ Delete", key=f"del_loc_{rec['id']}"):
                delete_location(rec["id"])
                st.cache_resource.clear()
                st.success(f"Deleted '{rec.get('name','')}'.")
                st.rerun()