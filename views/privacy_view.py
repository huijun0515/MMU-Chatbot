"""Privacy & data notice (PDPA-style plain-language page)."""

import streamlit as st

from core import config
from ui.layout import page_footer, page_header


def render_privacy_page():
    page_header("Privacy & data notice", "What this assistant records, why, and for how long.",
                eyebrow="MMU Campus Assistant")
    st.markdown(f"""
**What is logged when you ask a question**

- the question text, the answer, which documents were used, the time, and whether the
  question was typed, picked from a suggestion, or spoken;
- your 👍 / 👎 feedback, if you give it.

**What is not logged**

- no names, student IDs, e-mail addresses or account details — there is no login for students;
- anything in a question that looks like a student ID or a phone number is masked
  (e.g. `[ID]`, `[PHONE]`) *before* it is stored;
- voice recordings are sent to the speech service for transcription and are not kept.

**Why**

The log is used only to improve the assistant: to find questions it could not answer
(knowledge gaps), to measure how often answers are correct, and for the evaluation chapter
of this final-year project.

**Retention**

Query logs are kept for {config.QUERY_LOG_RETENTION_DAYS} days and then deleted automatically.
Events and campus locations are reference data and are kept while the service runs.

**Third parties**

Answers and transcriptions are generated with Google Gemini; the text of your question
(after masking) is sent to that service. Document search runs locally.

**Contact**

Questions about this notice or the data: {config.PRIVACY_CONTACT}.

*This is an unofficial student project and not an MMU service. It is not a substitute for
information from the Student Service Centre or your faculty.*
""")
    page_footer()
