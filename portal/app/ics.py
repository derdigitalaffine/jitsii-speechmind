"""Kalendereinladungen im iCalendar-Format (RFC 5545), kompatibel mit Outlook, Thunderbird, Apple und Google.

Ohne Fremdbibliothek: Escaping und Zeilenfaltung (75 Oktette) sind hier umgesetzt.
Zeiten werden in UTC geschrieben; jeder Kalender rechnet sie in die eigene Zeitzone um.
"""

from datetime import datetime, timedelta

from .db import utcnow

PRODID = "-//Videokonferenzserver//Portal//DE"


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,") \
        .replace("\r\n", "\n").replace("\n", "\\n")


def _param(text: str) -> str:
    """Parameterwert (z. B. CN) in Anführungszeichen, ohne verbotene Zeichen."""
    return '"' + (text or "").replace('"', "'").replace("\n", " ") + '"'


def _fold(line: str) -> str:
    """Zeilen auf höchstens 75 Oktette falten, ohne UTF-8-Zeichen zu zerteilen."""
    out, chunk, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(chunk)
            chunk, size = "", 0
        chunk += ch
        size += n
    out.append(chunk)
    return "\r\n ".join(out)


def _dt(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def build(*, method: str, uid: str, sequence: int, start: datetime, minutes: int, title: str,
          description: str, location: str, url: str, organizer: tuple[str, str] | None,
          attendees: list[tuple[str, str]], cancelled: bool = False, alarm_minutes: int = 15) -> str:
    """Erzeugt eine VCALENDAR-Datei. start: naive UTC. method: REQUEST | CANCEL | PUBLISH."""
    end = start + timedelta(minutes=minutes)
    lines = [
        "BEGIN:VCALENDAR",
        f"PRODID:{PRODID}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SEQUENCE:{sequence}",
        f"DTSTAMP:{_dt(utcnow())}",
        f"DTSTART:{_dt(start)}",
        f"DTEND:{_dt(end)}",
        f"SUMMARY:{_esc(title)}",
        f"DESCRIPTION:{_esc(description)}",
        f"LOCATION:{_esc(location)}",
        f"URL:{url}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        "TRANSP:OPAQUE",
        "CLASS:PUBLIC",
        f"X-MICROSOFT-CDO-BUSYSTATUS:{'FREE' if cancelled else 'BUSY'}",
        "X-MICROSOFT-CDO-INTENDEDSTATUS:BUSY",
    ]
    if organizer and organizer[1]:
        lines.append(f"ORGANIZER;CN={_param(organizer[0])}:mailto:{organizer[1]}")
    for name, email in attendees:
        lines.append(f"ATTENDEE;CN={_param(name or email)};CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;"
                     f"PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{email}")
    if not cancelled and alarm_minutes:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(title)}",
                  f"TRIGGER:-PT{alarm_minutes}M", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
