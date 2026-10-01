"""Chatprotokolle aus Portal-Räumen.

Prosody (mod_portal_access_muc) schreibt Gruppen-Chatnachrichten tageweise nach
<PORTAL_CHAT_DIR>/<raum>/<JJJJ-MM-TT>.jsonl (UTC). Beim Erzeugen der MP3 einer Aufnahme
übernimmt das Portal die Nachrichten aus dem Aufnahmezeitraum in die Aufnahme. Rohdateien
werden nach RETENTION_HOURS gelöscht: Chat ohne Aufnahme wird also nicht dauerhaft gespeichert.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger("portal.chat")

RETENTION_HOURS = 48
MARGIN_SECONDS = 30  # Jibri startet und beendet die Aufnahme mit wenigen Sekunden Versatz


def prepare_dir() -> None:
    """Ordner anlegen und für Prosody (eigener Benutzer im Container) beschreibbar machen."""
    root = settings.portal_chat_dir
    try:
        if root.parent.is_dir() or root.is_dir():
            root.mkdir(exist_ok=True)
            os.chmod(root, 0o1777)
    except OSError as exc:
        log.warning("Chat-Ordner %s nicht vorbereitet: %s", root, exc)


def collect(room: str, start: float, end: float) -> list[dict]:
    """Nachrichten eines Raums zwischen start und end (Unix-Zeit), chronologisch."""
    folder = settings.portal_chat_dir / room.lower()
    if not folder.is_dir() or "/" in room:
        return []
    messages = []
    day = datetime.fromtimestamp(start - MARGIN_SECONDS, timezone.utc).date()
    last = datetime.fromtimestamp(end + MARGIN_SECONDS, timezone.utc).date()
    while day <= last:
        path = folder / f"{day.isoformat()}.jsonl"
        if path.exists():
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        item = json.loads(line)
                        ts = float(item["ts"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    if start - MARGIN_SECONDS <= ts <= end + MARGIN_SECONDS:
                        messages.append({
                            "time": datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None).isoformat(),
                            "name": str(item.get("name") or "Teilnehmer:in")[:120],
                            "text": str(item.get("text") or "")[:4000],
                        })
        day += timedelta(days=1)
    messages.sort(key=lambda m: m["time"])
    return messages


def for_video(room: str, video: Path, duration: int | None) -> list[dict]:
    """Nachrichten während einer Aufnahme: Ende = letzte Änderung der Videodatei, Beginn = Ende - Dauer."""
    try:
        end = video.stat().st_mtime
    except OSError:
        return []
    start = end - (duration or 0)
    return collect(room, start, end)


def prune() -> int:
    """Rohdateien älter als RETENTION_HOURS löschen. Gibt die Anzahl gelöschter Dateien zurück."""
    root = settings.portal_chat_dir
    if not root.is_dir():
        return 0
    limit = time.time() - RETENTION_HOURS * 3600
    removed = 0
    for path in root.glob("*/*.jsonl"):
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
                removed += 1
        except OSError:
            continue
    for folder in root.iterdir():
        try:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            continue
    return removed


def as_text(messages: list[dict], to_local) -> str:
    lines = []
    for m in messages:
        when = to_local(datetime.fromisoformat(m["time"]))
        lines.append(f"[{when:%d.%m.%Y %H:%M:%S}] {m['name']}: {m['text']}")
    return "\n".join(lines) + "\n"
