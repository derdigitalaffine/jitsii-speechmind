"""Content-Security-Policy ohne 'unsafe-inline' für Skripte.

- Inline-<script>-Blöcke in den Vorlagen bekommen beim Laden der Vorlage automatisch eine Nonce
  (Jinja-Erweiterung, arbeitet nur auf dem Vorlagen-Quelltext – Benutzereingaben werden nie verändert,
  eingeschleuste Skripte bleiben also blockiert).
- Kurze Inline-Handler (onchange="this.form.submit()" …) werden über ihren Hash freigegeben
  ('unsafe-hashes'); die Liste entsteht beim Start aus den Vorlagen.
"""

import base64
import contextvars
import hashlib
import re
import secrets
from pathlib import Path

from jinja2.ext import Extension

_nonce: contextvars.ContextVar[str] = contextvars.ContextVar("csp_nonce", default="")

# <script …> ohne src – nur am Zeilenanfang oder direkt nach einem Jinja-Tag, damit Zeichenketten in
# JavaScript (z. B. erzeugter Einbettungscode) unberührt bleiben
_INLINE_SCRIPT = re.compile(r"(^[ \t]*|%\}[ \t]*)<script(?![^>]*\bsrc=)(?![^>]*\bnonce=)(?=[\s>])", re.M)
_HANDLER = re.compile(r"\son[a-z]+=\"([^\"{}]*)\"")


def new_nonce() -> str:
    value = secrets.token_urlsafe(18)
    _nonce.set(value)
    return value


def current_nonce() -> str:
    return _nonce.get()


class NonceExtension(Extension):
    def preprocess(self, source, name, filename=None):
        return _INLINE_SCRIPT.sub(lambda m: m.group(1) + '<script nonce="{{ csp_nonce() }}"', source)


def handler_hashes(template_dir: Path) -> list[str]:
    found = set()
    for path in template_dir.rglob("*.html"):
        for m in _HANDLER.finditer(path.read_text(encoding="utf-8")):
            digest = hashlib.sha256(m.group(1).encode()).digest()
            found.add("'sha256-" + base64.b64encode(digest).decode() + "'")
    return sorted(found)
