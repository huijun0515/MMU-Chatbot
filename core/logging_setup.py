"""
One logger for the whole app, so failures that used to be swallowed by
`except Exception: pass` show up somewhere instead of disappearing.
Writes to stderr (visible in the terminal running `streamlit run`), which is
enough for an FYP demo / grading setting — no log-rotation infra needed.
"""

import logging

logger = logging.getLogger("mmu_assistant")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
