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
import time
import streamlit as st
from langchain_core.documents import Document

from vector_store import get_vector_db

LOCATIONS_DIR = "./locations"
LOCATIONS_JSON = os.path.join(LOCATIONS_DIR, "locations.json")

CATEGORIES = ["Classroom", "Lecture Hall", "Lab", "Office", "Facility", "Landmark", "Other"]

# A few placeholder records so the feature works out of the box.
# ⚠️ Replace these with your real MMU data (and add photos) via the Admin panel.
SEED = [
    {
        "id": "library", "name": "Main Library", "aliases": ["Library", "Perpustakaan"],
        "category": "Facility", "building": "Library Building", "floor": "Ground–Level 3",
        "description": "The central campus library with study zones, discussion rooms and computer labs.",
        "directions": "From the main entrance lobby, head straight past the admin counter; the library is the large glass building on your left.",
        "landmarks": "Next to the student cafeteria; opposite the main lecture blocks.",
        "image": "",
    },
    {
        "id": "finance-office", "name": "Finance Office", "aliases": ["Bursary", "Fees Office"],
        "category": "Office", "building": "Administration Building", "floor": "Level 1",
        "description": "Handles fee payments, financial aid and billing enquiries.",
        "directions": "Enter the Administration Building main door, take the stairs or lift to Level 1, turn right; the Finance Office is the second door.",
        "landmarks": "Beside the Student Services Centre.",
        "image": "",
    },
    {
        "id": "ssc", "name": "Student Services Centre", "aliases": ["SSC"],
        "category": "Office", "building": "Administration Building", "floor": "Ground Level",
        "description": "One-stop centre for student matters: registration, letters, ID cards and general enquiries.",
        "directions": "On the ground floor of the Administration Building, immediately to the left of the main entrance.",
        "landmarks": "Below the Finance Office; near the covered walkway.",
        "image": "",
    },
]


# ──────────────────────────────────────────────────────────────
#  Storage
# ──────────────────────────────────────────────────────────────
def _ensure_dir():
    os.makedirs(LOCATIONS_DIR, exist_ok=True)


def _load():
    _ensure_dir()
    if not os.path.exists(LOCATIONS_JSON):
        _save(SEED)
        return list(SEED)
    try:
        with open(LOCATIONS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(items):
    _ensure_dir()
    with open(LOCATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


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
def _to_document(rec):
    aliases = ", ".join(rec.get("aliases", []) or [])
    parts = [f"Campus location: {rec.get('name','')}"]
    if aliases:
        parts.append(f" (also known as: {aliases})")
    parts.append(f".\nCategory: {rec.get('category','')}.")
    parts.append(f"\nBuilding / block: {rec.get('building','')}.")
    parts.append(f"\nFloor: {rec.get('floor','')}.")
    if rec.get("description"):
        parts.append(f"\nDescription: {rec['description']}")
    if rec.get("directions"):
        parts.append(f"\nHow to get there: {rec['directions']}")
    if rec.get("landmarks"):
        parts.append(f"\nNearby landmarks: {rec['landmarks']}")
    text = "".join(parts)

    meta = {
        "type": "location",
        "loc_id": rec["id"],
        "name": rec.get("name", ""),
        "building": rec.get("building", ""),
        "floor": rec.get("floor", ""),
        "image": rec.get("image", ""),
        "source_file": "Campus Directory",
    }
    return Document(page_content=text, metadata=meta)


def _add_with_retry(vector_db, docs):
    while True:
        try:
            vector_db.add_documents(docs)
            return
        except Exception as e:
            m = str(e).lower()
            if "429" in m or "resource_exhausted" in m or "quota" in m:
                time.sleep(45)
            else:
                raise


def _delete_from_vectordb(vector_db, loc_id):
    try:
        vector_db._collection.delete(where={"loc_id": loc_id})
    except Exception:
        pass


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
    _add_with_retry(vdb, [_to_document(rec)])


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
    docs = [_to_document(r) for r in _load()]
    if docs:
        _add_with_retry(vdb, docs)
    return len(docs)


# ──────────────────────────────────────────────────────────────
#  Chat helper (#8): find a location card in retrieved context
# ──────────────────────────────────────────────────────────────
def location_card_from_context(context_docs):
    """Return {name, building, floor, image_path} for the top location doc, or None."""
    for doc in context_docs or []:
        md = getattr(doc, "metadata", {}) or {}
        if md.get("type") == "location":
            return {
                "name": md.get("name", ""),
                "building": md.get("building", ""),
                "floor": md.get("floor", ""),
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
        st.markdown(f"<span class='loc-meta'>{rec.get('category','')}</span>", unsafe_allow_html=True)
        st.markdown(f"<div class='loc-title'>{rec.get('name','')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='loc-sub'>🏢 {rec.get('building','')} · {rec.get('floor','')}</div>",
                    unsafe_allow_html=True)
        if rec.get("description"):
            st.markdown(f"<div class='loc-desc'>{rec['description']}</div>", unsafe_allow_html=True)
        if rec.get("directions"):
            with st.expander("🧭 How to get there"):
                st.write(rec["directions"])
                if rec.get("landmarks"):
                    st.caption(f"📍 Nearby: {rec['landmarks']}")


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
        cats = ["All"] + CATEGORIES
        cat = st.selectbox("Category", cats)

    def _match(rec):
        if cat != "All" and rec.get("category") != cat:
            return False
        if query:
            hay = " ".join([
                rec.get("name", ""), rec.get("building", ""),
                " ".join(rec.get("aliases", []) or []), rec.get("description", ""),
            ]).lower()
            if query.lower() not in hay:
                return False
        return True

    filtered = [r for r in items if _match(r)]
    if not filtered:
        st.info("No places match your search.")
        return

    cols_per_row = 3
    for i in range(0, len(filtered), cols_per_row):
        row = filtered[i:i + cols_per_row]
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