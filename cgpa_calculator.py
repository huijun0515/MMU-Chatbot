import streamlit as st
import uuid

from ui.layout import page_footer, page_header

# ─────────────────────────────────────────────────────────────
#  EXACT MMU GRADE TABLE — per mark, matching CalculateGrades.net
# ─────────────────────────────────────────────────────────────
MMU_GRADE_TABLE = [
    ("A+  (90–100)", 4.00),
    ("A   (80–89)",  4.00),
    ("A-  (79)",     3.93),
    ("A-  (78)",     3.87),
    ("A-  (77)",     3.80),
    ("A-  (76)",     3.73),
    ("A-  (75)",     3.67),
    ("B+  (74)",     3.60),
    ("B+  (73)",     3.53),
    ("B+  (72)",     3.47),
    ("B+  (71)",     3.40),
    ("B+  (70)",     3.33),
    ("B   (69)",     3.27),
    ("B   (68)",     3.20),
    ("B   (67)",     3.13),
    ("B   (66)",     3.07),
    ("B   (65)",     3.00),
    ("B-  (64)",     2.93),
    ("B-  (63)",     2.87),
    ("B-  (62)",     2.80),
    ("B-  (61)",     2.73),
    ("B-  (60)",     2.67),
    ("C+  (59)",     2.59),
    ("C+  (58)",     2.53),
    ("C+  (57)",     2.46),
    ("C+  (56)",     2.40),
    ("C+  (55)",     2.33),
    ("C   (54)",     2.26),
    ("C   (53)",     2.20),
    ("C   (52)",     2.13),
    ("C   (51)",     2.07),
    ("C   (50)",     2.00),
    ("C-  (47–49)",  1.67),
    ("D+  (44–46)",  1.33),
    ("D   (40–43)",  1.00),
    ("F   (0–39)",   0.00),
]

GRADE_LABELS = [g[0] for g in MMU_GRADE_TABLE]
GRADE_POINTS = {g[0]: g[1] for g in MMU_GRADE_TABLE}

def get_honours(cgpa, career):
    if career == "Bachelor's Degree":
        if cgpa >= 3.67: return ("First Class Honours",        "var(--warn-fg)")
        if cgpa >= 3.33: return ("Second Class Upper Honours", "var(--text-2)")
        if cgpa >= 2.67: return ("Second Class Lower Honours", "var(--warn-fg)")
        if cgpa >= 2.00: return ("Third Class Honours",        "var(--text-2)")
        return ("Below Minimum CGPA (2.00)", "var(--bad-fg)")
    else:
        if cgpa >= 3.50: return ("Distinction", "var(--warn-fg)")
        if cgpa >= 3.00: return ("Credit",      "var(--text-2)")
        if cgpa >= 2.00: return ("Pass",        "var(--ok-fg)")
        return ("Below Minimum CGPA (2.00)", "var(--bad-fg)")

def cgpa_color(val):
    if val >= 3.67: return "var(--info-fg)"
    if val >= 3.00: return "var(--ok-fg)"
    if val >= 2.00: return "var(--warn-fg)"
    return "var(--bad-fg)"


def render_cgpa_calculator():

    # Initialize variables in session state to None so boxes are completely empty
    if "prior_cgpa_val" not in st.session_state:
        st.session_state.prior_cgpa_val = None
    if "prior_credits_val" not in st.session_state:
        st.session_state.prior_credits_val = None
    if "subjects" not in st.session_state:
        st.session_state.subjects = [
            {"id": str(uuid.uuid4()), "name": "", "credits": 3, "grade": GRADE_LABELS[0]},
            {"id": str(uuid.uuid4()), "name": "", "credits": 3, "grade": GRADE_LABELS[0]},
        ]

    page_header("CGPA Calculator", "Plan your semester with the official MMU grading scheme.",
                eyebrow="Academic tools")

    # ── Settings ───────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        career = st.selectbox("Programme Level", ["Bachelor's Degree", "Diploma"], key="calc_career")
    with c2:
        tri_type = st.selectbox("Trimester Type", ["Long Trimester (14 weeks)", "Short Trimester (7 weeks)"], key="calc_tri")

    st.markdown("---")

    # ── Main layout: input left, result right ──────────────────
    left, right = st.columns([2.2, 1], gap="large")

    with left:
        st.markdown("#### 🏫 Previous Results *(optional)*")
        st.caption("Enter your existing CGPA and total credits completed **before** this semester.")
        p1, p2 = st.columns(2)
        with p1:
            # Setting value=None makes it blank. format="%.2f" will auto-assign 2 decimals when typed.
            prior_cgpa = st.number_input(
                "Current CGPA", 
                min_value=0.00, 
                max_value=4.00,
                value=st.session_state.prior_cgpa_val,
                step=0.01, 
                format="%.2f",
                placeholder="e.g. 3.12",
                help="Only values between 0.00 and 4.00 are allowed."
            )
            st.session_state.prior_cgpa_val = prior_cgpa

        with p2:
            # Setting value=None makes it blank. step=1 ensures it stays an integer.
            prior_credits = st.number_input(
                "Credits Completed", 
                min_value=0, 
                max_value=120,
                value=st.session_state.prior_credits_val,
                step=1, 
                format="%d",
                placeholder="e.g. 60",
                help="Maximum 120 credits. Whole numbers only."
            )
            st.session_state.prior_credits_val = prior_credits

        st.markdown("---")
        st.markdown("#### 📝 This Semester")

        h1, h2, h3, h4 = st.columns([3, 1, 3, 0.4])
        with h1: st.caption("Course (optional)")
        with h2: st.caption("Credits ✱")
        with h3: st.caption("Grade ✱")

        # Subject rows loop using UNIQUE UUIDs
        to_delete = None
        for i, subj in enumerate(st.session_state.subjects):
            uid = subj["id"]
            
            c1, c2, c3, c4 = st.columns([3, 1, 3, 0.4])
            with c1:
                subj["name"] = st.text_input("Course", value=subj["name"], placeholder="e.g. TCE1111", key=f"n_{uid}", label_visibility="collapsed")
            with c2:
                subj["credits"] = st.number_input("CH", min_value=1, max_value=6, value=subj["credits"], key=f"c_{uid}", label_visibility="collapsed")
            with c3:
                idx = GRADE_LABELS.index(subj["grade"]) if subj["grade"] in GRADE_LABELS else 0
                subj["grade"] = st.selectbox("Grade", GRADE_LABELS, index=idx, key=f"g_{uid}", label_visibility="collapsed")
            with c4:
                if len(st.session_state.subjects) > 1:
                    if st.button("✕", key=f"del_{uid}", help="Remove this subject"):
                        to_delete = i

        if to_delete is not None:
            st.session_state.subjects.pop(to_delete)
            st.rerun()

        ba1, ba2 = st.columns(2)
        with ba1:
            if st.button("➕  Add Course", use_container_width=True):
                st.session_state.subjects.append({"id": str(uuid.uuid4()), "name": "", "credits": 3, "grade": GRADE_LABELS[0]})
                st.rerun()
        with ba2:
            if st.button("🗑️  Reset All", use_container_width=True):
                st.session_state.subjects = [
                    {"id": str(uuid.uuid4()), "name": "", "credits": 3, "grade": GRADE_LABELS[0]},
                    {"id": str(uuid.uuid4()), "name": "", "credits": 3, "grade": GRADE_LABELS[0]},
                ]
                st.session_state.prior_cgpa_val = None
                st.session_state.prior_credits_val = None
                st.rerun()

    # ── Live result panel ──────────────────────────────────────
    with right:
        # Protect math engine against "None" blanks by falling back to 0
        safe_prior_cgpa = prior_cgpa if prior_cgpa is not None else 0.0
        safe_prior_credits = prior_credits if prior_credits is not None else 0

        sem_gp = sum(GRADE_POINTS[s["grade"]] * s["credits"] for s in st.session_state.subjects)
        sem_ch = sum(s["credits"] for s in st.session_state.subjects)
        gpa    = sem_gp / sem_ch if sem_ch > 0 else 0.0

        prior_gp  = safe_prior_cgpa * safe_prior_credits
        cum_gp    = prior_gp + sem_gp
        cum_ch    = safe_prior_credits + sem_ch
        cgpa      = cum_gp / cum_ch if cum_ch > 0 else 0.0

        gpa_col  = cgpa_color(gpa)
        cgpa_col = cgpa_color(cgpa)

        min_gpa_dl = 3.67 if "Bachelor" in career else 3.50
        min_ch_dl  = 12 if "Long" in tri_type else 6
        deans_ok   = gpa >= min_gpa_dl and sem_ch >= min_ch_dl

        st.markdown(f"""
        <div class="res-panel">
            <div class="res-block">
                <div class="res-label">Semester Credits</div>
                <div class="res-value res-small">{sem_ch}</div>
            </div>
            <div class="res-block">
                <div class="res-label">GPA</div>
                <div class="res-value" style="color:{gpa_col};">{gpa:.2f}</div>
            </div>
            <div class="res-block">
                <div class="res-label">Total Credits</div>
                <div class="res-value res-small">{cum_ch}</div>
            </div>
            <div class="res-block">
                <div class="res-label">CGPA</div>
                <div class="res-value" style="color:{cgpa_col};">{cgpa:.2f}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if deans_ok:
            st.markdown("""<div class="deans-badge">⭐ Dean's List Eligible!</div>""", unsafe_allow_html=True)

        if cum_ch > 0:
            label, col = get_honours(cgpa, career)
            st.markdown(f"""<div class="honours" style="background:color-mix(in srgb, {col} 12%, transparent); border:2px solid {col}; color:{col};">🎓 {label}</div>""", unsafe_allow_html=True)

        if gpa < 2.0 and sem_ch > 0:
            st.warning("⚠️ GPA below 2.00 — Probation risk")
        if cgpa < 2.0 and cum_ch > 0:
            st.error("❌ CGPA below 2.00 — Cannot graduate")

    st.markdown("---")

    # ── Grade Reference Table ──────────────────────────────────
    with st.expander("📖 MMU Grading Scheme"):
        rows = ""
        for label, pts in MMU_GRADE_TABLE:
            mark = label.split("(")[-1].replace(")", "").strip() if "(" in label else ""
            grade_clean = label.split("(")[0].strip()
            rows += f"<tr><td>{mark}</td><td><b>{grade_clean}</b></td><td>{pts:.2f}</td></tr>"
        st.markdown(f"""
        <table class="grade-table">
        <thead><tr><th>Marks</th><th>Grade</th><th>Grade Point</th></tr></thead>
        <tbody>{rows}</tbody>
        </table>
        """, unsafe_allow_html=True)
        st.caption("Source: MMU Academic Handbook 2025, §8.1 Scheme of Marks and Grades (PDF page 49) and "
                   "§12.2 Classification of Honours (PDF page 71).")

        st.markdown("---")
        col_b, col_d = st.columns(2)
        with col_b:
            st.markdown("🎓 Bachelor Honours \n| CGPA | Class |\n|------|-------|\n| 3.67–4.00 | First Class |\n| 3.33–3.66 | Second Upper |\n| 2.67–3.32 | Second Lower |\n| 2.00–2.66 | Third Class |")
        with col_d:
            st.markdown("🎓 Diploma Honours \n| CGPA | Class |\n|------|-------|\n| 3.50–4.00 | Distinction |\n| 3.00–3.49 | Credit |\n| 2.00–2.99 | Pass |")
    page_footer()