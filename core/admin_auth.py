"""
Admin login logic (no Streamlit imports, so it is unit-testable).

  * constant-time password comparison (hmac.compare_digest)
  * lockout: MAX_FAILED_ATTEMPTS failures from one client lock that client out for
    LOCKOUT_SECONDS. Failures are tracked in memory per client key (IP address when
    the host exposes it) so reloading the page does not reset the counter.
  * idle timeout: a login expires after IDLE_TIMEOUT_SECONDS without activity.
"""

import hmac
import threading
import time

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60
IDLE_TIMEOUT_SECONDS = 30 * 60

_failures = {}  # client key -> {"count": int, "locked_until": float}
_lock = threading.Lock()


def passwords_match(supplied, correct):
    return hmac.compare_digest((supplied or "").encode("utf-8"), (correct or "").encode("utf-8"))


def seconds_locked(key, now=None):
    now = time.time() if now is None else now
    with _lock:
        rec = _failures.get(key)
        if rec and rec["locked_until"] > now:
            return int(rec["locked_until"] - now) + 1
        return 0


def register_failure(key, now=None):
    now = time.time() if now is None else now
    with _lock:
        rec = _failures.setdefault(key, {"count": 0, "locked_until": 0.0})
        if rec["locked_until"] and rec["locked_until"] <= now:  # an old lockout has expired: start over
            rec["count"], rec["locked_until"] = 0, 0.0
        rec["count"] += 1
        if rec["count"] >= MAX_FAILED_ATTEMPTS:
            rec["locked_until"] = now + LOCKOUT_SECONDS
            rec["count"] = 0
        return MAX_FAILED_ATTEMPTS - rec["count"] if not rec["locked_until"] else 0


def register_success(key):
    with _lock:
        _failures.pop(key, None)


def attempt(supplied, correct, key, now=None):
    """Returns (ok, message). Message is user-safe."""
    wait = seconds_locked(key, now)
    if wait:
        return False, f"Too many failed attempts. Try again in {wait // 60 + (1 if wait % 60 else 0)} minute(s)."
    if passwords_match(supplied, correct):
        register_success(key)
        return True, ""
    left = register_failure(key, now)
    if left == 0:
        return False, f"Too many failed attempts. Locked for {LOCKOUT_SECONDS // 60} minutes."
    return False, f"Wrong password. {left} attempt(s) left before a {LOCKOUT_SECONDS // 60}-minute lock."


def session_expired(last_seen, now=None):
    now = time.time() if now is None else now
    return last_seen is None or (now - last_seen) > IDLE_TIMEOUT_SECONDS
