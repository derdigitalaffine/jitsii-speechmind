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


# Outlook-Betreffzeilen von Antworten (deutsch/englisch), falls keine iCalendar-Daten mitkommen
_SUBJECT_STATUS = [
    ("counter", r"neue\s+zeit\s+vorgeschlagen|vorgeschlagene\s+neue\s+zeit|new\s+time\s+proposed"),
    ("tentative", r"mit\s+vorbehalt(?:\s+(?:angenommen|zugesagt))?|vorl[äa]ufig(?:\s+(?:angenommen|zugesagt))?"
                  r"|tentative(?:ly\s+accepted)?"),
    ("accepted", r"zugesagt|angenommen|akzeptiert|accepted"),
    ("declined", r"abgesagt|abgelehnt|declined"),
]
_SUBJECT_RE = re.compile(r"^\s*(?:(?:aw|re|wg|fw|fwd)\s*:\s*)*(" + "|".join(f"(?P<{k}>{p})" for k, p in _SUBJECT_STATUS)
                         + r")\s*:\s*(?P<rest>.*)$", re.I | re.S)
# Outlook-Nachrichtenklassen im TNEF-Anhang (winmail.dat)
_TNEF_CLASSES = {b"IPM.Schedule.Meeting.Resp.Pos": "accepted", b"IPM.Schedule.Meeting.Resp.Neg": "declined",
                 b"IPM.Schedule.Meeting.Resp.Tent": "tentative"}
# Termine aus iCalendar tragen die UID in der Outlook-GlobalObjectId hinter „vCal-Uid“
_VCAL_UID_RE = re.compile(rb"vCal-Uid\x01\x00\x00\x00([\x21-\x7e]{4,255})\x00")


def _subject_status(subject: str) -> tuple[str | None, str]:
    m = _SUBJECT_RE.match(subject or "")
    if not m:
        return None, ""
    status = next(k for k, _ in _SUBJECT_STATUS if m.group(k))
    return status, " ".join(m.group("rest").split())


def _tnef_parts(msg) -> list[bytes]:
    parts = []
    for part in msg.walk():
        if part.get_content_type() == "application/ms-tnef" or (part.get_filename() or "").lower() == "winmail.dat":
            data = part.get_payload(decode=True)
            if data:
                parts.append(data)
    return parts


def _tnef_reply(data: bytes) -> tuple[str | None, str | None]:
    """(Status, UID) aus einem winmail.dat einer Outlook-Antwort, soweit enthalten."""
    status = next((v for k, v in _TNEF_CLASSES.items() if k in data), None)
    m = _VCAL_UID_RE.search(data)
    return status, (m.group(1).decode("ascii") if m else None)


def _parse(raw: bytes) -> tuple[list[dict], dict]:
    """Antworten und Diagnoseangaben einer Mail."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = _mailto(email.utils.parseaddr(str(msg.get("From", "")))[1])
    subject = " ".join(str(msg.get("Subject", "")).split())
    info = {"sender": sender, "subject": subject, "date": str(msg.get("Date", "")), "kind": "none",
            "methods": []}
    replies = []
    cal_parts = _calendar_parts(msg)
    if cal_parts:
        info["kind"] = "calendar"
    for data in cal_parts:
        try:
            cal = icalendar.Calendar.from_ical(data)
        except ValueError as exc:
            log.info("Kalenderteil nicht lesbar: %s", exc)
            info["methods"].append("unlesbar")
            continue
        method = str(cal.get("METHOD", "")).upper()
        info["methods"].append(method or "ohne METHOD")
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
                replies.append({"uid": uid, "sequence": sequence, "email": _mailto(att), "sender": sender,
                                "name": str(att.params.get("CN", "")) if hasattr(att, "params") else "",
                                "status": status, "comment": comment, "proposed": proposed, "title": ""})
    if replies:
        return replies, info
    # Ersatz: Outlook/Exchange schickt Antworten mitunter ohne iCalendar (winmail.dat oder nur Text).
    # Dann zählen Nachrichtenklasse bzw. Betreff („Zugesagt: …“), zugeordnet über den Absender.
    subj_status, title = _subject_status(subject)
    tnef_status, tnef_uid = None, None
    tnef = _tnef_parts(msg)
    if tnef:
        info["kind"] = "tnef"
        for data in tnef:
            st, uid = _tnef_reply(data)
            tnef_status, tnef_uid = tnef_status or st, tnef_uid or uid
    status = tnef_status or subj_status
    if status and sender and (subj_status or tnef_status) and (title or tnef_uid):
        if info["kind"] == "none":
            info["kind"] = "subject"
        replies.append({"uid": tnef_uid, "sequence": None, "email": sender, "sender": sender, "name": "",
                        "status": status, "comment": "", "proposed": None, "title": title})
    return replies, info


def parse_message(raw: bytes) -> list[dict]:
    """Liefert alle Antworten in einer Mail: [{uid, sequence, email, status, comment, proposed, title}]."""
    return _parse(raw)[0]


def _proposed_text(value) -> str:
    try:
        if getattr(value, "tzinfo", None) is not None:
            value = value.astimezone(to_local(utcnow()).tzinfo)
        return value.strftime("%d.%m.%Y, %H:%M Uhr")
    except (AttributeError, ValueError):
        return str(value)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", (text or "").lower()).split())


def match(db, reply: dict) -> tuple[Meeting | None, Invitee | None, str]:
    """Besprechung und eingeladene Person zu einer Antwort. Dritter Wert: Grund, falls nichts passt."""
    if reply.get("uid"):
        meeting = db.scalar(select(Meeting).where(Meeting.ics_uid == reply["uid"]))
        if meeting is None:
            return None, None, "Termin-UID gehört zu keiner Besprechung des Portals"
    else:
        # Ohne UID: Besprechung, zu der der Absender eingeladen ist und deren Titel im Betreff steht
        title = _norm(reply.get("title", ""))
        candidates = [i.meeting for i in db.scalars(select(Invitee).where(Invitee.email == reply["sender"]))
                      if i.meeting is not None and i.meeting.cancelled_at is None and i.meeting.starts_at
                      and _norm(i.meeting.title) and _norm(i.meeting.title) in title]
        if not candidates:
            return None, None, "keine Besprechung mit diesem Titel, zu der der Absender eingeladen ist"
        now = utcnow()
        upcoming = [m for m in candidates if m.starts_at >= now - timedelta(hours=12)]
        # längster passender Titel zuerst (genauester Treffer), dann der nächste Termin
        meeting = sorted(upcoming or candidates,
                         key=lambda m: (-len(_norm(m.title)), abs((m.starts_at - now).total_seconds())))[0]
    inv = (next((i for i in meeting.invitees if i.email == reply["email"]), None)
           or next((i for i in meeting.invitees if i.email == reply.get("sender")), None))
    if inv is None and reply.get("name"):
        inv = next((i for i in meeting.invitees if i.name and i.name.lower() == reply["name"].lower()), None)
    return meeting, inv, ""


def apply_reply(db, reply: dict) -> str | None:
    """Speichert eine Antwort. Gibt eine Beschreibung zurück oder None, wenn sie nicht passt."""
    meeting, inv, _ = match(db, reply)
    if meeting is None:
        return None
    if reply["sequence"] is not None and reply["sequence"] < (meeting.ics_sequence or 0):
        log.info("Veraltete Antwort von %s zu %s ignoriert", reply["email"], meeting.title)
        return "veraltet"
    if inv is None:
        # Weitergeleitete Einladung: die antwortende Person wird mit aufgenommen
        inv = Invitee(email=reply["email"], name=reply["name"] or reply["email"])
        meeting.invitees.append(inv)
    comment = reply["comment"]
    if reply["status"] == "counter" and reply["proposed"]:
        comment = f"Vorschlag: {_proposed_text(reply['proposed'])}" + (f" – {comment}" if comment else "")
    if inv.rsvp_status == reply["status"] and (inv.rsvp_comment or "") == (comment or ""):
        return f"{inv.email}: {reply['status']} ({meeting.title}, unverändert)"
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


def poll(force: bool = False, rescan: bool = False) -> str:
    """Neue Nachrichten abrufen und Antworten verbuchen. Gibt eine kurze Zusammenfassung zurück.

    rescan: die Nachrichten der letzten Tage erneut prüfen (z. B. nach einer Korrektur der Einstellungen).
    """
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
        if rescan:
            last_uid = 0
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
                    found += [r for r in results if r and r != "veraltet" and not r.endswith("unverändert)")]
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
                set_setting(db, "imap_rsvp_last_uid", str(max([*uids, int(cfg.get("imap_rsvp_last_uid") or 0)])
                                                          if rescan else max(uids)))
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


def inspect_mailbox(limit: int = 25) -> list[dict]:
    """Diagnose: die neuesten Nachrichten im Antwort-Ordner und ob bzw. warum sie erkannt werden.

    Liest nur (BODY.PEEK), verändert nichts im Postfach und nichts in der Datenbank.
    """
    with SessionLocal() as db:
        cfg = get_settings(db)
    folder = cfg.get("imap_rsvp_folder") or "INBOX"
    rows = []
    conn = notify._imap_connect(cfg)
    try:
        status, _ = conn.select(f'"{folder}"', readonly=True)
        if status != "OK":
            raise notify.MailError(f"Der Ordner „{folder}“ existiert nicht.")
        status, data = conn.uid("search", None, "ALL")
        uids = sorted(int(u) for u in (data[0].split() if status == "OK" and data and data[0] else []))[-limit:]
        last_uid = int(cfg.get("imap_rsvp_last_uid") or 0)
        for uid in reversed(uids):
            status, fetched = conn.uid("fetch", str(uid), "(FLAGS BODY.PEEK[])")
            raw = next((part[1] for part in fetched or [] if isinstance(part, tuple)), None)
            if status != "OK" or raw is None:
                continue
            replies, info = _parse(raw)
            row = {"uid": uid, "sender": info["sender"], "subject": info["subject"], "date": info["date"],
                   "kind": info["kind"], "checked": uid <= last_uid, "ok": False, "result": ""}
            if not replies:
                if info["kind"] == "calendar":
                    methods = ", ".join(info["methods"])
                    row["result"] = (f"Kalenderdaten, aber keine Antwort (METHOD {methods})"
                                     + (" – vermutlich eine Einladung, keine Zu-/Absage" if "REQUEST" in methods else ""))
                elif info["kind"] == "tnef":
                    row["result"] = "Outlook-Format (winmail.dat) ohne erkennbare Antwort"
                else:
                    row["result"] = "keine Termin-Antwort (weder Kalenderdaten noch „Zugesagt:“/„Abgelehnt:“ im Betreff)"
            else:
                with SessionLocal() as db:
                    texts = []
                    for r in replies:
                        meeting, inv, reason = match(db, r)
                        label = {"accepted": "Zusage", "declined": "Absage", "tentative": "Mit Vorbehalt",
                                 "counter": "Neuer Zeitvorschlag", "delegated": "Delegiert"}.get(r["status"], r["status"])
                        how = {"calendar": "iCalendar", "tnef": "winmail.dat", "subject": "Betreff"}.get(info["kind"], "")
                        if meeting is None:
                            texts.append(f"{label} ({how}) von {r['email']}, aber {reason}")
                        else:
                            row["ok"] = True
                            who = inv.email if inv else f"{r['email']} (nicht eingeladen – wird ergänzt)"
                            texts.append(f"{label} ({how}) von {who} zu „{meeting.title}“")
                    db.rollback()
                row["result"] = "; ".join(texts)
            rows.append(row)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise notify.MailError(f"IMAP: {exc}") from exc
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return rows


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
