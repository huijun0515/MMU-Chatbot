"""
Parse data/Location File.xlsx into location records (no Streamlit, no DB).

Columns: Location | Block/Building | Floor | Directions | Name | Category |
Also known as | Opening hours | Contact | Source | Verification status | Notes.
Empty cells stay empty — nothing is ever filled in or guessed.
"""

import re

import openpyxl

COLUMNS = [
    "Location", "Block/Building", "Floor", "Directions", "Name", "Category",
    "Also known as", "Opening hours", "Contact", "Source", "Verification status", "Notes",
]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "location"


def _cell(value):
    return "" if value is None else str(value).strip()


def clean_aliases(raw):
    """'Old code: UX01; MCMR0001 (2014/15 code); Ext. Exam Hall = MCAR0001 (2014/15 code)'
    -> ['UX01', 'MCMR0001', 'Ext. Exam Hall', 'MCAR0001']. Bare codes, no annotations."""
    out = []
    for part in raw.split(";"):
        part = re.sub(r"^\s*old code\s*:\s*", "", part, flags=re.I)
        part = re.sub(r"\s*\([^)]*\bcode\b[^)]*\)", "", part, flags=re.I)   # "(2014/15 code)", "(old block code)"
        part = re.sub(r"\s*\([^)]*\.\.\.[^)]*\)", "", part)                 # "(MA...)"
        part = re.sub(r"\s+in room codes\s*$", "", part, flags=re.I)
        for piece in re.split(r"=|/", part):                                 # "Ext. Exam Hall = MCAR0001", "A / B"
            piece = piece.strip()
            m = re.match(r"^([A-Z0-9]{2,8})\s*\((.+)\)$", piece)             # "NICE (Network and ...)"
            if m:
                out += [m.group(1), piece]
            elif piece:
                out.append(piece)
    return out


def row_to_record(row):
    cells = dict(zip(COLUMNS, [_cell(c) for c in row]))
    code = cells["Location"]
    name = cells["Name"] or code
    seen = {slug(name), slug(code)}
    aliases = []
    for a in clean_aliases(cells["Also known as"]):
        if slug(a) not in seen:
            seen.add(slug(a))
            aliases.append(a)
    return {
        "id": slug(code),
        "code": code,
        "name": name,
        "aliases": aliases,
        "category": cells["Category"],
        "building": cells["Block/Building"],
        "floor": cells["Floor"],
        "description": "",
        "directions": cells["Directions"],
        "landmarks": "",
        "opening_hours": cells["Opening hours"],
        "contact": cells["Contact"],
        "source": cells["Source"],
        "verification_status": cells["Verification status"],
        "notes": cells["Notes"],
        "image": "",
    }


def read_locations_xlsx(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))
    header = [_cell(c) for c in rows[0][: len(COLUMNS)]]
    if header != COLUMNS:
        raise ValueError(f"Unexpected columns in {path}: {header}")
    return [row_to_record(r) for r in rows[1:] if r and _cell(r[0])]


def write_locations_xlsx(records):
    """The current location data as an Excel workbook (same 12 columns as the import file); returns bytes."""
    import io

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(COLUMNS)
    for r in records:
        ws.append([r.get("code") or r.get("id", ""), r.get("building", ""), r.get("floor", ""), r.get("directions", ""),
                   r.get("name", ""), r.get("category", ""), "; ".join(r.get("aliases") or []),
                   r.get("opening_hours", ""), r.get("contact", ""), r.get("source", ""),
                   r.get("verification_status", ""), r.get("notes", "")])
    for col, width in zip("ABCDEFGHIJKL", (16, 22, 16, 40, 28, 14, 26, 18, 22, 30, 26, 40)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
