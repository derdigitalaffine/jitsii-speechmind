"""Antworten auf Besprechungseinladungen (Zusage, Absage, Vorbehalt) aus dem IMAP-Postfach lesen.

Kalenderprogramme schicken Antworten als iTIP-Nachricht (METHOD:REPLY bzw. COUNTER) an den
Organisator des Termins. Ist die Auswertung eingeschaltet, ist das die Absenderadresse des Portals
(siehe planning.organizer_identity). Der Worker ruft poll() regelmäßig auf.

Es werden nur neue Nachrichten gelesen (gemerkt über die IMAP-UID), ohne sie zu verändern.
Erkannte Antworten werden als gelesen markiert und auf Wunsch in einen Ordner verschoben;
alle anderen Mails im Postfach bleiben unberührt.
"""

import email
import imaplib
import logging
import re
from datetime import timedelta
from email import policy

import icalendar
from sqlalchemy import select

from . import mailtpl, notify
from .config import settings
from .db import Invitee, Meeting, SessionLocal, get_settings, set_setting, to_local, utcnow

log = logging.getLogger("portal.rsvp")

PARTSTATS = {"ACCEPTED": "accepted", "DECLINED": "declined", "TENTATIVE": "tentative",
             "DELEGATED": "delegated"}
FIRST_RUN_DAYS = 14
MAX_PER_RUN = 200


# --- Nachricht auswerten ------------------------------------------------------

def _calendar_parts(msg) -> list[bytes]:
    parts = []
    for part in msg.walk():
        ctype = part.get_content_type()
        filename = (part.get_filename() or "").lower()
        if ctype in ("text/calendar", "application/ics") or filename.endswith(".ics"):
            data = part.get_payload(decode=True)
            if data:
                parts.append(data)
    return parts


def _mailto(value) -> str:
    return re.sub(r"^mailto:", "", str(value or ""), flags=re.I).strip().lower()


def parse_message(raw: bytes) -> list[dict]:
    """Liefert alle Antworten in einer Mail: [{uid, sequence, email, status, comment, proposed}]."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = _mailto(email.utils.parseaddr(str(msg.get("From", "")))[1])
    replies = []
    for data in _calendar_parts(msg):
        try:
            cal = icalendar.Calendar.from_ical(data)
        except ValueError as exc:
            log.info("Kalenderteil nicht lesbar: %s", exc)
            continue
        method = str(cal.get("METHOD", "")).upper()
        if method not in ("REPLY", "COUNTER"):
            continue
        for ev in cal.walk("VEVENT"):
            uid = str(ev.get("UID", "")).strip()
            attendees = ev.get("ATTENDEE")
            attendees = attendees if isinstance(attendees, list) else ([attendees] if attendees else [])
            comment = str(ev.get("COMMENT", "") or "").strip()
            sequence = int(ev.get("SEQUENCE", 0) or 0)
            proposed = None
            if method == "COUNTER" and ev.get("DTSTART"):
                proposed = ev.decoded("DTSTART")
            if not attendees and sender:
                attendees = [icalendar.vCalAddress(f"mailto:{sender}")]
            for att in attendees:
                partstat = str(att.params.get("PARTSTAT", "")).upper() if hasattr(att, "params") else ""
                status = "counter" if method == "COUNTER" else PARTSTATS.get(partstat)
                if not uid or not status:
                    continue
                replies.append({"uid": uid, "sequence": sequence, "email": _mailto(att),
                                "name": str(att.params.get("CN", "")) if hasattr(att, "params") else "",
                                "status": status, "comment": comment, "proposed": proposed})
    return replies


def _proposed_text(value) -> str:
    try:
        if getattr(value, "tzinfo", None) is not None:
            value = value.astimezone(to_local(utcnow()).tzinfo)
        return value.strftime("%d.%m.%Y, %H:%M Uhr")
    except (AttributeError, ValueError):
        return str(value)


def apply_reply(db, reply: dict) -> str | None:
    """Speichert eine Antwort. Gibt eine Beschreibung zurück oder None, wenn sie nicht passt."""
    meeting = db.scalar(select(Meeting).where(Meeting.ics_uid == reply["uid"]))
    if meeting is None:
        return None
    if reply["sequence"] < (meeting.ics_sequence or 0):
        log.info("Veraltete Antwort von %s zu %s ignoriert", reply["email"], meeting.title)
        return "veraltet"
    inv = next((i for i in meeting.invitees if i.email == reply["email"]), None)
    if inv is None:
        # Weitergeleitete Einladung: die antwortende Person wird mit aufgenommen
        inv = Invitee(email=reply["email"], name=reply["name"] or reply["email"])
        meeting.invitees.append(inv)
    comment = reply["comment"]
    if reply["status"] == "counter" and reply["proposed"]:
        comment = f"Vorschlag: {_proposed_text(reply['proposed'])}" + (f" – {comment}" if comment else "")
    inv.rsvp_status, inv.rsvp_at, inv.rsvp_comment = reply["status"], utcnow(), comment or None
    db.flush()
    notify_organizer(db, meeting, inv)
    return f"{inv.email}: {reply['status']} ({meeting.title})"


def notify_organizer(db, meeting: Meeting, inv: Invitee) -> None:
    from . import planning  # vermeidet Importzyklus
    cfg = get_settings(db)
    owner = meeting.owner
    if cfg.get("notify_rsvp") != "1" or owner is None or not owner.active or meeting.starts_at is None:
        return
    subject, body = mailtpl.render(db, "meeting_rsvp", {
        **planning.when(meeting), "name": owner.name, "titel": meeting.title,
        "teilnehmer": f"{inv.name} <{inv.email}>" if inv.name and inv.name != inv.email else inv.email,
        "antwort": planning.RSVP_LABELS.get(inv.rsvp_status, inv.rsvp_status),
        "kommentar": inv.rsvp_comment or "", "stand": planning.rsvp_text(meeting),
        "link": f"{settings.portal_base_url}/meetings/{meeting.id}#termin",
    }, cfg)
    notify.enqueue(db, owner.email, subject, body, "meeting_rsvp", cfg)


# --- IMAP-Abruf ----------------------------------------------------------------

def _uidvalidity(conn) -> str:
    _, data = conn.response("UIDVALIDITY")
    return (data[0].decode() if data and data[0] else "")


def poll(force: bool = False) -> str:
    """Neue Nachrichten abrufen und Antworten verbuchen. Gibt eine kurze Zusammenfassung zurück."""
    with SessionLocal() as db:
        cfg = get_settings(db)
    if cfg.get("imap_rsvp") != "1" and not force:
        return "Auswertung ist ausgeschaltet."
    folder = cfg.get("imap_rsvp_folder") or "INBOX"
    move_to = (cfg.get("imap_rsvp_move") or "").strip()
    found = []
    conn = notify._imap_connect(cfg)
    try:
        status, _ = conn.select(f'"{folder}"')
        if status != "OK":
            raise notify.MailError(f"Der Ordner „{folder}“ existiert nicht.")
        validity = _uidvalidity(conn)
        last_uid = int(cfg.get("imap_rsvp_last_uid") or 0) if cfg.get("imap_rsvp_uidvalidity") == validity else 0
        if last_uid:
            status, data = conn.uid("search", None, f"UID {last_uid + 1}:*")
        else:
            since = (utcnow() - timedelta(days=FIRST_RUN_DAYS)).strftime("%d-%b-%Y")
            status, data = conn.uid("search", None, f"SINCE {since}")
        uids = sorted(int(u) for u in (data[0].split() if status == "OK" and data and data[0] else [])
                      if int(u) > last_uid)[:MAX_PER_RUN]
        handled = []
        for uid in uids:
            status, fetched = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((part[1] for part in fetched or [] if isinstance(part, tuple)), None)
            if status != "OK" or raw is None:
                continue
            replies = parse_message(raw)
            if replies:
                with SessionLocal() as db:
                    results = [apply_reply(db, r) for r in replies]
                    db.commit()
                if any(results):
                    # Auch veraltete Antworten gelten als erledigt (werden markiert/verschoben),
                    # zählen aber nicht als verbucht
                    found += [r for r in results if r and r != "veraltet"]
                    handled.append(uid)
        for uid in handled:
            conn.uid("store", str(uid), "+FLAGS", "(\\Seen)")
            if move_to:
                status, _ = conn.uid("MOVE", str(uid), f'"{move_to}"')
                if status != "OK":
                    if conn.uid("copy", str(uid), f'"{move_to}"')[0] == "OK":
                        conn.uid("store", str(uid), "+FLAGS", "(\\Deleted)")
        if handled and move_to:
            try:
                conn.expunge()
            except imaplib.IMAP4.error:
                pass
        with SessionLocal() as db:
            if uids:
                set_setting(db, "imap_rsvp_last_uid", str(max(uids)))
            set_setting(db, "imap_rsvp_uidvalidity", validity)
            set_setting(db, "imap_rsvp_last_check", utcnow().isoformat(timespec="seconds"))
            set_setting(db, "imap_rsvp_last_error", "")
            db.commit()
    except (imaplib.IMAP4.error, OSError) as exc:
        raise notify.MailError(f"IMAP: {exc}") from exc
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    if found:
        log.info("%d Antwort(en) verbucht: %s", len(found), "; ".join(found))
    return f"{len(uids)} neue Nachricht(en) geprüft, {len(found)} Antwort(en) verbucht."


def poll_safely() -> None:
    """Für den Worker: Fehler nur protokollieren und in den Einstellungen vermerken."""
    try:
        poll()
    except notify.MailError as exc:
        log.warning("Abruf der Antworten fehlgeschlagen: %s", exc)
        with SessionLocal() as db:
            set_setting(db, "imap_rsvp_last_error", str(exc)[:500])
            set_setting(db, "imap_rsvp_last_check", utcnow().isoformat(timespec="seconds"))
            db.commit()
