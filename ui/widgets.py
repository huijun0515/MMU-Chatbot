"""Small self-contained HTML widgets rendered with st.iframe."""

import json
import re


def answer_actions_html(text, tts=True):
    """'Copy' and (optionally) 'Read aloud' buttons for one answer."""
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    plain = re.sub(r"[*_`#>]+", "", plain)
    payload = json.dumps(plain).replace("</", "<\\/")
    tts_button = "<button id='r'>🔊 Read aloud</button>" if tts else ""
    return f"""
<style>
button {{ border:1px solid #cbd5e1; background:#fff; border-radius:8px; padding:4px 12px; margin-right:8px;
          cursor:pointer; font:600 13px sans-serif; color:#0033A0; }}
@media (prefers-color-scheme: dark) {{ button {{ background:#1A2235; color:#9DBBFF; border-color:#2A3447; }} }}
</style>
<button id='c'>📋 Copy</button>{tts_button}
<script>
const text = {payload};
const c = document.getElementById('c');
c.onclick = async () => {{
  try {{ await navigator.clipboard.writeText(text); }}
  catch (e) {{
    const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy'); ta.remove();
  }}
  c.textContent = '✓ Copied'; setTimeout(() => c.textContent = '📋 Copy', 1500);
}};
const r = document.getElementById('r');
if (r) {{
  const lang = t => /[\\u4e00-\\u9fff]/.test(t) ? 'zh-CN'
    : /\\b(dan|yang|dengan|untuk|adalah|tidak|boleh|saya|anda|di|ke|pada)\\b/i.test(t) ? 'ms-MY' : 'en-GB';
  r.onclick = () => {{
    if (!('speechSynthesis' in window)) {{ r.textContent = 'Not supported here'; return; }}
    if (speechSynthesis.speaking) {{ speechSynthesis.cancel(); r.textContent = '🔊 Read aloud'; return; }}
    const u = new SpeechSynthesisUtterance(text); u.lang = lang(text);
    u.onend = () => r.textContent = '🔊 Read aloud';
    r.textContent = '⏹ Stop'; speechSynthesis.speak(u);
  }};
}}
</script>"""
