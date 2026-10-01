"""Besprechungen planen: Termin, Teilnehmende, Kalendereinladungen per E-Mail."""

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from . import ics, mailtpl, notify
from .config import settings
from .db import LOCAL_TZ, Invitee, Meeting, User, get_settings, to_local, utcnow

EMAIL_RE = re.compile(r"^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
DURATIONS = [15, 30, 45, 60, 90, 120, 180, 240, 480]


def name_from_email(email: str) -> str:
    return " ".join(p.capitalize() for p in re.split(r"[._\-+]+", email.split("@")[0]) if p) or email


def parse_emails(text: str) -> tuple[list[str], list[str]]:
    """Trennt Eingabe (Komma, Semikolon, Leerzeichen, Zeilen) in (gültige, ungültige) Adressen."""
    seen, good, bad = set(), [], []
    for part in re.split(r"[,;\s]+", text or ""):
        part = part.strip().strip("<>").lower()
        if not part or part in seen:
            continue
        seen.add(part)
        (good if EMAIL_RE.match(part) else bad).append(part)
    return good, bad


def parse_local(value: str) -> datetime | None:
    """'2026-10-08T10:00' (Ortszeit aus dem Formular) -> naive UTC."""
    try:
        local = datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None
    if local.tzinfo is None:
        local = local.replace(tzinfo=LOCAL_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def local_input(value: datetime | None) -> str:
    return to_local(value).strftime("%Y-%m-%dT%H:%M") if value else ""


def join_link(meeting: Meeting) -> str:
    return f"{settings.meet_base_url}/{meeting.room}"


def when(meeting: Meeting) -> dict[str, str]:
    start, end = to_local(meeting.starts_at), to_local(meeting.ends_at)
    minutes = meeting.duration_minutes or 60
    dauer = f"{minutes} Minuten" if minutes < 120 or minutes % 60 else f"{minutes // 60} Stunden"
    return {
        "datum": f"{WEEKDAYS[start.weekday()]}, {start:%d.%m.%Y}",
        "uhrzeit": f"{start:%H:%M}–{end:%H:%M} Uhr",
        "dauer": dauer,
    }


def ensure_uid(meeting: Meeting) -> None:
    if not meeting.ics_uid:
        host = urlparse(settings.portal_base_url).hostname or "portal"
        meeting.ics_uid = f"{uuid.uuid4().hex}@{host}"


def _calendar(meeting: Meeting, method: str, attendees: list[tuple[str, str]], organizer: User | None) -> str:
    link = join_link(meeting)
    text = f"Einwahl: {link}"
    if meeting.description:
        text += "\n\n" + meeting.description
    text += "\n\nTeilnahme im Browser, ohne Installation."
    return ics.build(
        method=method, uid=meeting.ics_uid, sequence=meeting.ics_sequence or 0,
        start=meeting.starts_at, minutes=meeting.duration_minutes or 60, title=meeting.title,
        description=text, location=link, url=link,
        organizer=(organizer.name, organizer.email) if organizer else None,
        attendees=attendees, cancelled=method == "CANCEL",
    )


def calendar_file(meeting: Meeting) -> str:
    """ICS zum Herunterladen (für den eigenen Kalender oder zum Weiterleiten)."""
    attendees = [(i.name, i.email) for i in meeting.invitees]
    return _calendar(meeting, "PUBLISH", attendees, meeting.owner)


def send(db, meeting: Meeting, invitees: list[Invitee], kind: str, organizer: User,
         copy_to_organizer: bool = False) -> tuple[int, bool]:
    """kind: invite | update | cancel. Gibt (Anzahl eingereihter Mails, Mailversand eingerichtet) zurück.

    Jede Person bekommt eine eigene Mail; im Kalendereintrag steht nur sie selbst als Teilnehmende,
    damit Adressen nicht an Dritte gehen.
    """
    cfg = get_settings(db)
    if not notify.mail_configured(cfg) or meeting.starts_at is None:
        return 0, notify.mail_configured(cfg)
    ensure_uid(meeting)
    method = "CANCEL" if kind == "cancel" else "REQUEST"
    filename = "absage.ics" if kind == "cancel" else "einladung.ics"
    base = {**when(meeting), "titel": meeting.title, "link": join_link(meeting),
            "beschreibung": meeting.description or "", "organisator": organizer.name,
            "organisator_email": organizer.email}
    count = 0
    for inv in invitees:
        subject, body = mailtpl.render(db, f"meeting_{kind}", {**base, "name": inv.name or inv.email}, cfg)
        ics_text = _calendar(meeting, method, [(inv.name, inv.email)], organizer)
        if notify.enqueue(db, inv.email, subject, body, f"meeting_{kind}", cfg, reply_to=organizer.email,
                          attachments=[{"filename": filename, "content": ics_text, "calendar_method": method}]):
            inv.invited_at = utcnow()
            count += 1
    if copy_to_organizer:
        subject, body = mailtpl.render(db, f"meeting_{kind}", {**base, "name": organizer.name}, cfg)
        own = _calendar(meeting, "CANCEL" if kind == "cancel" else "PUBLISH",
                        [(i.name, i.email) for i in meeting.invitees], organizer)
        notify.enqueue(db, organizer.email, "[Kopie] " + subject, body, f"meeting_{kind}", cfg,
                       attachments=[{"filename": filename, "content": own,
                                     "calendar_method": "CANCEL" if kind == "cancel" else "PUBLISH"}])
    return count, True


def add_invitees(db, meeting: Meeting, emails: list[str]) -> list[Invitee]:
    """Legt neue Teilnehmende an (bereits vorhandene werden übersprungen)."""
    existing = {i.email for i in meeting.invitees}
    users = {u.email: u for u in db.scalars(select(User).where(User.email.in_(emails)))} if emails else {}
    added = []
    for email in emails:
        if email in existing:
            continue
        inv = Invitee(email=email, name=users[email].name if email in users else name_from_email(email))
        meeting.invitees.append(inv)
        added.append(inv)
    return added


def is_upcoming(meeting: Meeting) -> bool:
    return bool(meeting.starts_at and not meeting.cancelled_at and meeting.ends_at > utcnow())
