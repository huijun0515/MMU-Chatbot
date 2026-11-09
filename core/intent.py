"""
Cheap, deterministic message-intent check — layer 1 of the "show sources?" gate.

A message is `chitchat` only if the WHOLE normalized message is made of the
social phrases in config.CHITCHAT_PATTERNS (greetings, thanks, goodbyes, "who
are you"). Anything else is `knowledge`. Misclassifying chit-chat as knowledge is
harmless: layer 2 (the relevance threshold in core/rag_chain.py) still keeps
sources off the screen when nothing relevant was retrieved.
"""

import re

from core import config

_APOSTROPHES_RE = re.compile(r"['’`]")
_PUNCT_RE = re.compile(r"[^\w\s]")  # \w is Unicode-aware, so CJK text survives

_COMBINED = "|".join(f"(?:{p})" for p in config.CHITCHAT_PATTERNS)
# One or more social phrases back to back: "hi how are you", "你好谢谢".
_CHITCHAT_RE = re.compile(rf"(?:(?:{_COMBINED})\s*)+")


def _normalize(text):
    text = _APOSTROPHES_RE.sub("", text.lower())  # "what's" -> "whats"
    return " ".join(_PUNCT_RE.sub(" ", text).split())


def classify_intent(text):
    """Return "chitchat" or "knowledge"."""
    if not config.INTENT_GATE_ENABLED:
        return "knowledge"
    norm = _normalize(text)
    if not norm:  # only emoji / punctuation
        return "chitchat"
    if len(norm) <= config.CHITCHAT_MAX_CHARS and _CHITCHAT_RE.fullmatch(norm):
        return "chitchat"
    return "knowledge"
