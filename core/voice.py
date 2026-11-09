"""
Voice input: transcribe a short recording with Gemini (English, Bahasa Melayu,
Chinese, or a mix). The transcript is only ever shown for editing — the caller
never sends it automatically, because room codes like "MNCR1001" are easy to mishear.
"""

import base64
import io
import json
import re
import wave

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from core import config
from core.logging_setup import logger

PROMPT = (
    "Transcribe this audio exactly as spoken. The speaker may use English, Bahasa Melayu or Chinese, "
    "or mix them. Write each language in its own script (Chinese in Simplified Chinese characters, no pinyin) and "
    "do NOT translate. Write room codes as letters and digits with no spaces (e.g. MNCR1001). "
    "Output only the transcript, nothing else. If there is no speech, output nothing."
)


class VoiceError(Exception):
    """A problem with a message that is safe and friendly to show the user."""


def wav_duration_seconds(data):
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError):
        return None


def transcribe(data, mime_type="audio/wav"):
    """WAV/audio bytes -> transcript text. Raises VoiceError with a friendly message."""
    if not data:
        raise VoiceError("No recording found. Press the microphone and record again.")
    if len(data) > config.VOICE_MAX_BYTES:
        raise VoiceError("That recording is too large. Please keep it under "
                         f"{config.VOICE_MAX_SECONDS} seconds.")
    seconds = wav_duration_seconds(data)
    if seconds is not None and seconds > config.VOICE_MAX_SECONDS + 0.5:
        raise VoiceError(f"That recording is {seconds:.0f}s long. The limit is {config.VOICE_MAX_SECONDS}s — "
                         "please record a shorter question.")

    api_key = config.get_secret("GEMINI_API_KEY")
    if not api_key:
        raise VoiceError("Voice input is not configured (no API key).")
    llm = ChatGoogleGenerativeAI(model=config.TRANSCRIBE_MODEL, temperature=0, google_api_key=api_key)
    message = HumanMessage(content=[
        {"type": "text", "text": PROMPT},
        {"type": "media", "mime_type": mime_type, "data": base64.b64encode(data).decode()},
    ])
    try:
        text = llm.invoke([message]).text
    except Exception as exc:
        msg = str(exc).lower()
        logger.exception("Transcription failed")
        if "429" in msg or "quota" in msg or "resource_exhausted" in msg:
            raise VoiceError("The speech service is busy right now. Please wait a minute and try again, or type your question.") from exc
        raise VoiceError("Sorry, I couldn't transcribe that. Please try again or type your question.") from exc
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        raise VoiceError("I couldn't hear any speech in that recording. Please try again, closer to the microphone.")
    return text


def read_aloud_html(text):
    """A self-contained button that speaks `text` with the browser's speech synthesis."""
    plain = re.sub(r"[*_`#>]+", "", text)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    payload = json.dumps(plain).replace("</", "<\\/")
    return f"""
<button id="b" style="border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:4px 12px;
 cursor:pointer;font:600 13px sans-serif;color:#0033A0">🔊 Read aloud</button>
<script>
const text = {payload};
const btn = document.getElementById('b');
function lang(t) {{
  if (/[\\u4e00-\\u9fff]/.test(t)) return 'zh-CN';
  if (/\\b(dan|yang|dengan|untuk|adalah|tidak|boleh|saya|anda|di|ke|pada)\\b/i.test(t)) return 'ms-MY';
  return 'en-GB';
}}
btn.onclick = () => {{
  if (!('speechSynthesis' in window)) {{ btn.textContent = 'Not supported in this browser'; return; }}
  if (speechSynthesis.speaking) {{ speechSynthesis.cancel(); btn.textContent = '🔊 Read aloud'; return; }}
  const u = new SpeechSynthesisUtterance(text); u.lang = lang(text);
  u.onend = () => btn.textContent = '🔊 Read aloud';
  btn.textContent = '⏹ Stop'; speechSynthesis.speak(u);
}};
</script>"""
