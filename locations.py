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

import io
import os
import re

import pandas as pd
import streamlit as st
from langchain_core.documents import Document

from core import config, locations_repo as repo
from core.vector_store import get_vector_db, embed_with_retry
from core.logging_setup import logger
from core.location_import import read_locations_xlsx, write_locations_xlsx
from core.posters import PosterError, save_poster
from ui.layout import page_footer, page_header

LOCATIONS_DIR = config.LOCATIONS_DIR

PLACES_PAGE_LIMIT = 60
CATEGORIES = ["Classroom", "Lecture Hall", "Tutorial Room", "Lab", "Office", "Faculty", "Facility",
              "Building", "Hostel", "Landmark", "Other"]

# The three invented placeholder records this project used to ship with. The
# Excel file now has real versions of them, so any copy left in locations.json is dropped on import.
LEGACY_SEED_IDS = {"library", "finance-office", "ssc"}

# Verification status -> (badge label, badge style, sentence the assistant is told)
_STATUS_STYLES = {
    "official": ("Official", "ok", "Official MMU source."),
    "partial": ("Official (partial)", "ok", "Official MMU source, but only partly documented."),
    "unverified": ("Unverified", "warn",
                   "UNVERIFIED: taken from an older unofficial list (2014/15). "
                   "This room information may have changed or be outdated."),
    "conflict": ("Conflict - check on site", "bad",
                 "CONFLICT: sources disagree about where this is. It must be checked on site."),
    "original": ("Original file", "info",
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
    return _STATUS_STYLES[key][2] if key else ""


def status_badge_html(status):
    key = _status_key(status)
    if not key:
        return ""
    label, kind, _ = _STATUS_STYLES[key]
    return f"<span class='badge badge-{kind}'>{label}</span>"


# ──────────────────────────────────────────────────────────────
#  Storage (SQLite via core/locations_repo.py)
# ──────────────────────────────────────────────────────────────
def _ensure_dir():
    os.makedirs(LOCATIONS_DIR, exist_ok=True)


def import_from_excel(path=None):
    """
    Upsert every row of the Excel file (by room code / id — re-importing never
    duplicates) and return the full list. Records that are not in the file
    (e.g. added in the admin panel) are kept, apart from the legacy placeholder
    seed records. Does NOT touch the vector DB; call resync_all() afterwards.
    """
    imported = read_locations_xlsx(path or config.LOCATIONS_XLSX)
    existing = {r["id"]: r for r in repo.all_locations()}
    for loc_id in LEGACY_SEED_IDS:
        if loc_id in existing:
            repo.delete(loc_id)
    for rec in imported:
        old = existing.get(rec["id"])
        if old and old.get("image"):
            rec["image"] = old["image"]  # keep a photo added in the admin panel
    repo.upsert_many(imported)
    return repo.all_locations()


def list_locations():
    locations = repo.all_locations()
    if not locations and os.path.exists(config.LOCATIONS_XLSX):  # fresh install: bootstrap from the Excel file
        locations = import_from_excel()
    return locations


def get_location(loc_id):
    return repo.get(loc_id)


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
    if image_file is not None:  # validated, resized and re-encoded (raises PosterError for bad files)
        rec["image"] = save_poster(image_file.getvalue(), directory=LOCATIONS_DIR, name=f"{rec['id']}.jpg",
                                   max_width=config.LOCATION_IMAGE_MAX_WIDTH)

    repo.upsert(rec)

    vdb = get_vector_db()
    _delete_from_vectordb(vdb, rec["id"])
    embed_with_retry(vdb, [location_to_document(rec)])


def delete_location(loc_id):
    rec = repo.get(loc_id)
    if rec and rec.get("image"):
        p = os.path.join(LOCATIONS_DIR, rec["image"])
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    repo.delete(loc_id)
    _delete_from_vectordb(get_vector_db(), loc_id)


def resync_all():
    """Wipe all location docs from the vector store and re-add from JSON."""
    vdb = get_vector_db()
    try:
        vdb._collection.delete(where={"type": "location"})
    except Exception:
        pass
    docs = [location_to_document(r) for r in repo.all_locations()]
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
#  Student-facing directory page (Places)
# ──────────────────────────────────────────────────────────────
STATUS_FILTERS = {
    "All": None,
    "Official": ("official", "partial"),
    "Unverified (older list)": ("unverified",),
    "Conflict - check on site": ("conflict",),
    "From original file": ("original",),
}


@st.cache_data(show_spinner=False)
def _campus_map_png(path, mtime, zoom=1.6):
    """The official campus map PDF rendered to PNG bytes (cached per file version)."""
    try:
        import pymupdf
        doc = pymupdf.open(path)
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png")
    except Exception:
        logger.exception("Could not render the campus map %s", path)
        return None


def _match(rec, q):
    q = q.lower().strip()
    if not q:
        return True
    hay = " ".join([rec.get("code", ""), rec.get("name", ""), rec.get("building", ""),
                    " ".join(rec.get("aliases", []) or []), rec.get("description", "")]).lower()
    return q in hay or q.replace(" ", "") in hay.replace(" ", "")


def _ask_question(rec):
    return f"Where is {rec.get('name') or rec.get('code')}?"


@st.dialog("Place details", width="large")
def _place_dialog(loc_id):
    rec = get_location(loc_id)
    if not rec:
        st.info("This place is no longer in the directory.")
        return
    p = image_path(rec.get("image", ""))
    if p:
        st.image(p, use_container_width=True)
    st.markdown(f"<span class='chip'>{_esc(rec.get('category', ''))}</span>"
                + status_badge_html(rec.get("verification_status")), unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:1.4rem;font-weight:800'>{_esc(rec.get('name', ''))}</div>", unsafe_allow_html=True)
    if rec.get("code") and rec["code"] != rec.get("name"):
        st.caption(f"Room code: {rec['code']}" + (f" · also: {', '.join(rec['aliases'])}" if rec.get("aliases") else ""))
    rows = [("🏢 Building", rec.get("building")), ("🧭 Floor", rec.get("floor")),
            ("🕒 Opening hours", rec.get("opening_hours")), ("📞 Contact", rec.get("contact"))]
    for label, value in rows:
        if value:
            st.markdown(f"**{label}:** {_esc(value)}")
    if rec.get("directions"):
        st.markdown(f"**How to get there:** {_esc(rec['directions'])}")
    if rec.get("notes"):
        st.info(rec["notes"])
    if rec.get("source"):
        st.caption(f"Source: {rec['source']}")
    if st.button("Ask the assistant about this place", type="primary", icon=":material/forum:",
                 key=f"ask_{loc_id}", use_container_width=True):
        from ui import nav
        nav.switch("assistant", quick_query=_ask_question(rec))


def _esc(text):
    import html
    return html.escape(str(text or ""))


def _place_row(rec, key):
    c1, c2, c3 = st.columns([5, 2.2, 1.1], vertical_alignment="center")
    sub = " · ".join(x for x in (rec.get("category"), rec.get("floor")) if x)
    code = rec.get("code", "")
    with c1:
        st.markdown(
            f"<div class='loc-name'>{_esc(rec.get('name', ''))}"
            + (f" <span class='loc-code'>{_esc(code)}</span>" if code and code != rec.get("name") else "")
            + f"</div><div class='loc-sub'>{_esc(sub)}</div>", unsafe_allow_html=True)
    with c2:
        st.markdown(status_badge_html(rec.get("verification_status")) or "&nbsp;", unsafe_allow_html=True)
    with c3:
        if st.button("Details", key=f"pl_{key}", type="tertiary"):
            _place_dialog(rec["id"])


def render_directory_page():
    page_header("Places", "Find classrooms, labs, offices and facilities around the Melaka campus.",
                eyebrow="Campus directory")

    map_path = os.path.join(config.DATA_DIR, "Melaka campus map.pdf")
    if os.path.exists(map_path):
        with st.expander("Official campus map (Melaka)", expanded=True, icon=":material/map:"):
            png = _campus_map_png(map_path, os.path.getmtime(map_path))
            if png:
                st.image(png, use_container_width=True)
            with open(map_path, "rb") as fh:
                st.download_button("Download map (PDF)", fh.read(), file_name="MMU Melaka campus map.pdf",
                                   mime="application/pdf", icon=":material/download:")

    items = list_locations()
    if not items:
        st.markdown("<div class='empty'>🗺️ No locations added yet.</div>", unsafe_allow_html=True)
        page_footer()
        return

    st.session_state.setdefault("places_query", "")
    query = st.text_input("Search", key="places_query", placeholder="Room code, name, old code or alias — e.g. MNCR1001, Unix Lab, FBLR0006A",
                          icon=":material/search:")
    f1, f2, f3 = st.columns(3)
    buildings = sorted({r.get("building", "") for r in items if r.get("building")})
    categories = sorted({r.get("category", "") for r in items if r.get("category")})
    building = f1.selectbox("Building", ["All"] + buildings)
    category = f2.selectbox("Category", ["All"] + categories)
    status = f3.selectbox("Verification", list(STATUS_FILTERS))

    wanted = STATUS_FILTERS[status]
    filtered = [
        r for r in items
        if _match(r, query)
        and (building == "All" or r.get("building") == building)
        and (category == "All" or r.get("category") == category)
        and (wanted is None or _status_key(r.get("verification_status")) in wanted)
    ]
    if not filtered:
        st.info("No places match your search. Try the room code, the building, or a shorter word.")
        page_footer()
        return

    st.caption(f"{len(filtered)} place{'s' if len(filtered) != 1 else ''}"
               + (f" — showing the first {PLACES_PAGE_LIMIT}; narrow the search to see the rest"
                  if len(filtered) > PLACES_PAGE_LIMIT else ""))
    shown = filtered[:PLACES_PAGE_LIMIT]
    groups = {}
    for r in shown:
        groups.setdefault(r.get("building") or "Other", []).append(r)
    for bname in sorted(groups):
        st.markdown(f"#### 🏢 {_esc(bname)} <span class='muted'>· {len(groups[bname])}</span>", unsafe_allow_html=True)
        for r in sorted(groups[bname], key=lambda x: (x.get("name") or "").lower()):
            _place_row(r, r["id"])
    page_footer()


# ──────────────────────────────────────────────────────────────
#  Admin management (called from the Admin panel)
# ──────────────────────────────────────────────────────────────
STATUS_VALUES = ["Official source", "Official source (partial)", "Unverified - old unofficial list",
                 "CONFLICT - check on site", "From your original file"]
_EDIT_COLUMNS = ["code", "name", "category", "building", "floor", "directions", "opening_hours", "contact",
                 "verification_status", "notes"]


@st.dialog("Delete this place?")
def _confirm_delete_location(loc_id):
    rec = get_location(loc_id)
    if not rec:
        st.info("Already deleted.")
        return
    st.write(f"**{rec.get('name', '')}** ({rec.get('code') or rec['id']}) will be removed from the directory and the assistant.")
    c1, c2 = st.columns(2)
    if c1.button("Delete", type="primary", key=f"yes_loc_{loc_id}", use_container_width=True):
        delete_location(loc_id)
        st.cache_resource.clear()
        st.rerun()
    if c2.button("Cancel", key=f"no_loc_{loc_id}", use_container_width=True):
        st.rerun()


def _admin_import_export():
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Import from Excel**")
        if os.path.exists(config.LOCATIONS_XLSX):
            st.caption(f"Project file: `{config.LOCATIONS_XLSX}`")
            if st.button("Re-import the project file", icon=":material/upload_file:"):
                with st.spinner("Importing and re-syncing…"):
                    total = len(import_from_excel())
                    n = resync_all()
                st.cache_resource.clear()
                st.success(f"Imported — {total} locations on file, {n} synced to the assistant.")
        up = st.file_uploader("…or upload a different Excel file (.xlsx, 12 columns)", type=["xlsx"], key="loc_xlsx_up")
        if up is not None and st.button("Import uploaded file", key="loc_xlsx_go"):
            if up.size > 5 * 1024 * 1024:
                st.error("That file is larger than 5 MB.")
            else:
                try:
                    records = read_locations_xlsx(io.BytesIO(up.getvalue()))
                except Exception:
                    logger.exception("Uploaded Excel could not be read")
                    st.error("That file could not be read. Use the layout of the exported/project Excel file.")
                else:
                    repo.upsert_many(records)
                    resync_all()
                    st.cache_resource.clear()
                    st.success(f"Imported {len(records)} rows.")
    with c2:
        st.markdown("**Download current data**")
        st.caption("Everything currently in the directory, in the same Excel layout (edit, then re-import).")
        st.download_button("Download as Excel", write_locations_xlsx(list_locations()),
                           file_name="Location File (current).xlsx", icon=":material/download:",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if st.button("Re-sync all to the assistant", icon=":material/sync:"):
            with st.spinner("Re-syncing…"):
                n = resync_all()
            st.cache_resource.clear()
            st.success(f"Re-synced {n} location(s).")


def _admin_table():
    items = list_locations()
    if not items:
        st.info("No locations yet.")
        return
    q = st.text_input("Filter the table", placeholder="code, name or building", key="loc_table_filter")
    rows = [r for r in items if _match(r, q)]
    st.caption(f"{len(rows)} of {len(items)} shown — double-click a cell to edit, then press **Save changes**.")
    original = {r["id"]: {c: r.get(c, "") or "" for c in _EDIT_COLUMNS} for r in rows}
    frame = pd.DataFrame([{"id": r["id"], **original[r["id"]]} for r in rows]).set_index("id")
    edited = st.data_editor(
        frame, key="loc_editor", use_container_width=True, height=420, num_rows="fixed",
        disabled=["code"],
        column_config={
            "category": st.column_config.SelectboxColumn("category", options=CATEGORIES),
            "verification_status": st.column_config.SelectboxColumn("status", options=STATUS_VALUES),
        },
    )
    changed = [i for i in edited.index if edited.loc[i].fillna("").astype(str).to_dict() != original[i]]
    if st.button(f"Save changes ({len(changed)})", type="primary", disabled=not changed, icon=":material/save:"):
        for loc_id in changed:
            rec = get_location(loc_id)
            rec.update({c: str(edited.loc[loc_id, c] or "").strip() for c in _EDIT_COLUMNS})
            upsert_location(rec)
        st.cache_resource.clear()
        st.success(f"Saved {len(changed)} place(s) and synced them to the assistant.")
        st.rerun()

    st.markdown("**Delete a place**")
    d1, d2 = st.columns([4, 1], vertical_alignment="bottom")
    pick = d1.selectbox("Place", [r["id"] for r in items], key="loc_delete_pick",
                        format_func=lambda i: next((f"{r['name']} ({r.get('code') or i})" for r in items if r["id"] == i), i))
    if d2.button("Delete…", key="loc_delete_go", use_container_width=True):
        _confirm_delete_location(pick)


def _admin_add_form():
    st.caption("If a location with the same room code or name exists, it will be updated.")
    with st.form("new_location", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Name *", placeholder="e.g. FIST Unix Lab")
            code = st.text_input("Room code", placeholder="e.g. MNCR1001")
            category = st.selectbox("Category", CATEGORIES)
            building = st.text_input("Building / Block", placeholder="e.g. FIST building")
            floor = st.text_input("Floor", placeholder="e.g. Level 1")
        with c2:
            aliases = st.text_input("Also known as (comma-separated)", placeholder="e.g. UX01, Unix Lab")
            image_file = st.file_uploader("Photo (PNG/JPEG/WEBP)", type=["png", "jpg", "jpeg", "webp"])
            status = st.selectbox("Verification status", STATUS_VALUES, index=4)
        description = st.text_area("Description", placeholder="What is this place?")
        directions = st.text_area("How to get there", placeholder="Step-by-step from a known landmark…")
        landmarks = st.text_input("Nearby landmarks", placeholder="e.g. opposite the cafeteria")
        submitted = st.form_submit_button("Save location", type="primary")

    if submitted:
        if not name.strip():
            st.error("Please enter a name.")
            return
        rec = {"id": _slug(code or name), "code": code.strip(), "name": name.strip(),
               "aliases": [a.strip() for a in aliases.split(",") if a.strip()], "category": category,
               "building": building.strip(), "floor": floor.strip(), "description": description.strip(),
               "directions": directions.strip(), "landmarks": landmarks.strip(), "verification_status": status,
               "image": ""}
        existing = get_location(rec["id"])
        if existing:
            rec = {**existing, **{k: v for k, v in rec.items() if v not in ("", [])}}
        try:
            with st.spinner("Saving and syncing to the assistant…"):
                upsert_location(rec, image_file)
        except PosterError as exc:
            st.error(str(exc))
            return
        st.cache_resource.clear()
        st.success(f"Saved '{name.strip()}' and synced it to the assistant.")
        st.rerun()


def render_admin_locations():
    sub_table, sub_io, sub_add = st.tabs(["Edit table", "Import / export", "Add a place"])
    with sub_table:
        _admin_table()
    with sub_io:
        _admin_import_export()
    with sub_add:
        _admin_add_form()
