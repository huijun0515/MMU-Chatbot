"""Sliding-window rate limit per browser session. Every call that costs a Gemini
request (a chat answer, a voice transcription) takes one slot."""

import time

from core import config


def try_acquire(store, now=None):
    """Take a slot. `store` is any dict-like (st.session_state).
    Returns (allowed, seconds_to_wait)."""
    now = time.time() if now is None else now
    window = config.CHAT_RATE_LIMIT_WINDOW_SECONDS
    stamps = [t for t in store.get("rate_limit_calls", []) if now - t < window]
    if len(stamps) >= config.CHAT_RATE_LIMIT_MAX:
        store["rate_limit_calls"] = stamps
        return False, max(1, int(window - (now - stamps[0])) + 1)
    stamps.append(now)
    store["rate_limit_calls"] = stamps
    return True, 0
