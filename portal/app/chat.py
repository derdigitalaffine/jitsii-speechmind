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


def _entries(room: str, first_day, last_day) -> list[dict]:
    folder = settings.portal_chat_dir / room.lower()
    if not folder.is_dir() or "/" in room:
        return []
    entries = []
    day = first_day
    while day <= last_day:
        path = folder / f"{day.isoformat()}.jsonl"
        if path.exists():
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        item = json.loads(line)
                        item["ts"] = float(item["ts"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    entries.append(item)
        day += timedelta(days=1)
    entries.sort(key=lambda e: e["ts"])
    return entries


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None).isoformat()


def collect(room: str, start: float, end: float) -> list[dict]:
    """Chatnachrichten eines Raums zwischen start und end (Unix-Zeit), chronologisch."""
    lo, hi = start - MARGIN_SECONDS, end + MARGIN_SECONDS
    return [{"time": _iso(e["ts"]), "name": str(e.get("name") or "Teilnehmer:in")[:120],
             "text": str(e.get("text") or "")[:4000]}
            for e in _entries(room, datetime.fromtimestamp(lo, timezone.utc).date(),
                              datetime.fromtimestamp(hi, timezone.utc).date())
            if e.get("kind") is None and e.get("text") and lo <= e["ts"] <= hi]


def collect_polls(room: str, start: float, end: float) -> list[dict]:
    """Umfragen, die während der Aufnahme gestellt oder beantwortet wurden, mit Endstand.

    Eine Stimme kann geändert werden: es zählt die letzte je Person (bis Aufnahmeende).
    """
    lo, hi = start - MARGIN_SECONDS, end + MARGIN_SECONDS
    entries = _entries(room, datetime.fromtimestamp(lo, timezone.utc).date() - timedelta(days=1),
                       datetime.fromtimestamp(hi, timezone.utc).date())
    polls: dict[str, dict] = {}
    for e in entries:
        if e.get("kind") != "poll" or e["ts"] > hi or not e.get("pollId"):
            continue
        pid = str(e["pollId"])
        if e.get("type") == "new-poll":
            polls[pid] = {"id": pid, "question": str(e.get("question") or "")[:1000],
                          "name": str(e.get("name") or "")[:120], "time": _iso(e["ts"]),
                          "answers": [str(a)[:500] for a in e.get("answers") or []],
                          "votes": {}, "active": lo <= e["ts"]}
        elif e.get("type") == "answer-poll" and pid in polls:
            voter = str(e.get("voterId") or e.get("name") or "")
            polls[pid]["votes"][voter] = {"name": str(e.get("name") or "Teilnehmer:in")[:120],
                                          "votes": [bool(v) for v in e.get("votes") or []], "time": _iso(e["ts"])}
            if e["ts"] >= lo:
                polls[pid]["active"] = True
    result = []
    for poll in polls.values():
        if not poll.pop("active"):
            continue
        options = [{"label": label, "count": 0, "voters": []} for label in poll["answers"]]
        for vote in poll["votes"].values():
            for i, chosen in enumerate(vote["votes"][:len(options)]):
                if chosen:
                    options[i]["count"] += 1
                    options[i]["voters"].append(vote["name"])
        result.append({"id": poll["id"], "question": poll["question"], "name": poll["name"], "time": poll["time"],
                       "options": options, "voters": len(poll["votes"])})
    return sorted(result, key=lambda p: p["time"])


def _window(video: Path, duration: int | None) -> tuple[float, float] | None:
    """Aufnahmezeitraum: Ende = letzte Änderung der Videodatei, Beginn = Ende - Dauer."""
    try:
        end = video.stat().st_mtime
    except OSError:
        return None
    return end - (duration or 0), end


def for_video(room: str, video: Path, duration: int | None) -> list[dict]:
    window = _window(video, duration)
    return collect(room, *window) if window else []


def polls_for_video(room: str, video: Path, duration: int | None) -> list[dict]:
    window = _window(video, duration)
    return collect_polls(room, *window) if window else []


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


def polls_as_text(polls: list[dict], to_local) -> str:
    lines = []
    for p in polls:
        when = to_local(datetime.fromisoformat(p["time"]))
        lines.append(f"Umfrage [{when:%d.%m.%Y %H:%M}]{' von ' + p['name'] if p.get('name') else ''}: {p['question']}")
        for o in p["options"]:
            who = f" ({', '.join(o['voters'])})" if o["voters"] else ""
            lines.append(f"  - {o['label']}: {o['count']}{who}")
        lines.append(f"  Teilgenommen: {p['voters']}")
        lines.append("")
    return "\n".join(lines)
