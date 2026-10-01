"""Raumliste für die Zugriffsregeln in Prosody (prosody/mod_portal_access*.lua).

Das Portal schreibt alle Portal-Räume und die Einstellung "Räume ohne Anmeldung" als JSON in
einen mit Prosody geteilten Ordner. Prosody liest die Datei bei jeder Raumanfrage neu ein,
sobald sie sich geändert hat; ein Neustart ist nicht nötig.
"""

import json
import logging
import os
import tempfile

from sqlalchemy import select

from .config import settings
from .db import Meeting, get_settings

log = logging.getLogger("portal.access")


def sync(db) -> bool:
    """Schreibt die aktuelle Raumliste. False, wenn der Ordner nicht eingebunden ist (z. B. Entwicklung)."""
    target = settings.portal_rooms_file
    if not target.parent.is_dir():
        return False
    rooms = sorted(r.lower() for r in db.scalars(select(Meeting.room)))
    data = {"anonymous": get_settings(db).get("allow_anonymous") == "1", "rooms": rooms}
    text = json.dumps(data, ensure_ascii=False, indent=1)
    try:
        if target.exists() and target.read_text(encoding="utf-8") == text:
            return True
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".rooms.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except OSError as exc:
        log.warning("Raumliste %s nicht geschrieben: %s", target, exc)
        return False
    return True
