"""
Smoke test: every page renders with no exception, logged out AND logged in
(admin), on an isolated copy of the app database.

    python eval/smoke_pages.py
"""

import os
import shutil
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp()
if os.path.exists("data/app.db"):
    shutil.copy("data/app.db", os.path.join(TMP, "app.db"))
os.environ["APP_DB_PATH"] = os.path.join(TMP, "app.db")
os.environ["EVENT_POSTERS_DIR"] = os.path.join(TMP, "posters")

from streamlit.testing.v1 import AppTest  # noqa: E402
from app_pages import PAGE_SPECS  # noqa: E402

failures = []
for page in [p for p in PAGE_SPECS if p != "home"]:
    for authed in (False, True):
        if authed and page != "admin":
            continue
        os.environ["SMOKE_PAGE"] = page
        at = AppTest.from_file("eval/_page_harness.py", default_timeout=120)
        if authed:
            at.session_state["admin_authed"] = True
            at.session_state["admin_last_seen"] = 10**12
        at.run()
        errors = [e.value for e in at.error] if hasattr(at, "error") else []
        friendly = [e for e in errors if "Something went wrong" in e]
        status = "ok  "
        if at.exception or friendly:
            status = "FAIL"
            failures.append(f"{page} authed={authed}: {at.exception or friendly}")
        print(f"{status} {page:<11} authed={authed}  elements={len(at.main.children)}")

print("\nALL PAGES RENDER" if not failures else "\n" + "\n".join(failures))
sys.exit(1 if failures else 0)
