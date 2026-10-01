"""Benachrichtigungs-Engine: E-Mails über SMTP versenden, optional per IMAP ablegen.

Nachrichten werden zuerst in der Datenbank eingereiht (Tabelle notifications) und vom
Worker verschickt. Dadurch blockiert ein langsamer Mailserver keine Anfrage, und
fehlgeschlagene Mails werden mit wachsendem Abstand erneut versucht.
"""

import imaplib
import logging
import smtplib
import ssl
import time
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from sqlalchemy import select

from .config import settings
from .db import Notification, Recording, SessionLocal, User, get_settings, to_local, utcnow
from .security import decrypt

log = logging.getLogger("portal.notify")

MAX_ATTEMPTS = 5
RETRY_DELAYS = [timedelta(minutes=m) for m in (1, 5, 15, 60, 240)]
TIMEOUT = 20


class MailError(Exception):
    pass


# --- Konfiguration -----------------------------------------------------------

def mail_configured(cfg: dict[str, str]) -> bool:
    return bool(cfg.get("smtp_host") and cfg.get("mail_from"))


def _port(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sender(cfg: dict[str, str]) -> str:
    return formataddr((cfg.get("mail_from_name") or settings.brand_name, cfg["mail_from"]))


# --- Verbindungen ------------------------------------------------------------

def _smtp_connect(cfg: dict[str, str]) -> smtplib.SMTP:
    host, port = cfg["smtp_host"], _port(cfg.get("smtp_port"), 587)
    security = cfg.get("smtp_security", "starttls")
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
            server.ehlo()
            if security == "starttls":
                server.starttls(context=context)
                server.ehlo()
        if cfg.get("smtp_user"):
            server.login(cfg["smtp_user"], decrypt(cfg.get("smtp_password_enc")))
        return server
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"SMTP-Server {host}:{port}: {exc}") from exc


def _imap_connect(cfg: dict[str, str]) -> imaplib.IMAP4:
    host, port = cfg.get("imap_host", ""), _port(cfg.get("imap_port"), 993)
    if not host:
        raise MailError("Kein IMAP-Server eingetragen.")
    security = cfg.get("imap_security", "ssl")
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            conn = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=TIMEOUT)
        else:
            conn = imaplib.IMAP4(host, port, timeout=TIMEOUT)
            if security == "starttls":
                conn.starttls(ssl_context=context)
        conn.login(cfg.get("imap_user", ""), decrypt(cfg.get("imap_password_enc")))
        return conn
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(f"IMAP-Server {host}:{port}: {exc}") from exc


# --- Senden ------------------------------------------------------------------

def _build(cfg: dict[str, str], to_addr: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _sender(cfg)
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg["mail_from"].rsplit("@", 1)[-1] or None)
    msg.set_content(body)
    return msg


def _save_to_sent(cfg: dict[str, str], msg: EmailMessage) -> None:
    if cfg.get("imap_save_sent") != "1" or not cfg.get("imap_host"):
        return
    try:
        conn = _imap_connect(cfg)
        try:
            folder = cfg.get("imap_sent_folder") or "Sent"
            conn.append(f'"{folder}"', "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    except (MailError, imaplib.IMAP4.error, OSError) as exc:
        # Versand war erfolgreich, die Ablage ist nur Zusatz
        log.warning("Kopie konnte nicht per IMAP abgelegt werden: %s", exc)


def deliver(cfg: dict[str, str], to_addr: str, subject: str, body: str) -> None:
    if not mail_configured(cfg):
        raise MailError("E-Mail-Versand ist nicht eingerichtet.")
    msg = _build(cfg, to_addr, subject, body)
    server = _smtp_connect(cfg)
    try:
        server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"Senden an {to_addr} fehlgeschlagen: {exc}") from exc
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
    _save_to_sent(cfg, msg)


def test_smtp(cfg: dict[str, str], to_addr: str) -> None:
    deliver(cfg, to_addr, f"Testnachricht – {settings.brand_product}",
            f"Dies ist eine Testnachricht des {settings.brand_product}s der "
            f"{settings.brand_name}.\n\nDer E-Mail-Versand funktioniert.\n")


def test_imap(cfg: dict[str, str]) -> str:
    conn = _imap_connect(cfg)
    try:
        status, data = conn.select("INBOX", readonly=True)
        count = data[0].decode() if status == "OK" and data and data[0] else "?"
        info = f"Anmeldung erfolgreich, {count} Nachricht(en) im Posteingang."
        if cfg.get("imap_save_sent") == "1":
            folder = cfg.get("imap_sent_folder") or "Sent"
            status, _ = conn.select(f'"{folder}"', readonly=True)
            if status != "OK":
                raise MailError(f"Der Ordner „{folder}“ für gesendete Nachrichten existiert nicht.")
        return info
    except imaplib.IMAP4.error as exc:
        raise MailError(f"IMAP: {exc}") from exc
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


# --- Warteschlange -----------------------------------------------------------

def enqueue(db, to_addr: str, subject: str, body: str, kind: str) -> bool:
    """Reiht eine Mail ein. Ohne eingerichteten Versand passiert nichts (False)."""
    if not mail_configured(get_settings(db)):
        return False
    db.add(Notification(kind=kind, to_addr=to_addr, subject=subject, body=body))
    return True


def process_queue() -> int:
    """Verschickt fällige Mails. Läuft im Worker-Thread, gibt die Zahl der gesendeten zurück."""
    sent = 0
    with SessionLocal() as db:
        cfg = get_settings(db)
        due = db.scalars(
            select(Notification).where(Notification.status == "pending",
                                       Notification.next_attempt_at <= utcnow())
            .order_by(Notification.id).limit(50)
        ).all()
        for n in due:
            n.attempts += 1
            try:
                deliver(cfg, n.to_addr, n.subject, n.body)
            except MailError as exc:
                n.error = str(exc)[:1000]
                if n.attempts >= MAX_ATTEMPTS or not mail_configured(cfg):
                    n.status = "failed"
                else:
                    n.next_attempt_at = utcnow() + RETRY_DELAYS[min(n.attempts - 1, len(RETRY_DELAYS) - 1)]
                log.warning("Mail %s an %s: %s", n.id, n.to_addr, exc)
            else:
                n.status, n.error, n.sent_at = "sent", None, utcnow()
                sent += 1
            db.commit()
    return sent


# --- Nachrichtentexte --------------------------------------------------------

def _footer() -> str:
    return (f"\n--\n{settings.brand_product} der {settings.brand_name}\n{settings.portal_base_url}\n")


def invite_text(user: User, link: str) -> tuple[str, str]:
    return (
        f"Einladung zum {settings.brand_product} der {settings.brand_name}",
        f"Guten Tag {user.name},\n\n"
        f"für Sie wurde ein Konto im {settings.brand_product} der {settings.brand_name} angelegt. "
        f"Über den folgenden Link legen Sie Ihr Passwort fest und melden sich an:\n\n{link}\n\n"
        f"Der Link ist {settings.invite_ttl_hours} Stunden gültig und kann nur einmal verwendet werden.\n"
        f"Ihr Benutzername ist Ihre E-Mail-Adresse: {user.email}\n" + _footer(),
    )


def reset_text(user: User, link: str) -> tuple[str, str]:
    return (
        f"Passwort zurücksetzen – {settings.brand_product}",
        f"Guten Tag {user.name},\n\n"
        f"für Ihr Konto wurde das Zurücksetzen des Passworts angefordert. Über diesen Link "
        f"vergeben Sie ein neues Passwort:\n\n{link}\n\n"
        f"Der Link ist {settings.reset_ttl_hours} Stunden gültig. Haben Sie das nicht angefordert, "
        f"können Sie diese Nachricht ignorieren.\n" + _footer(),
    )


def _recording_label(rec: Recording) -> str:
    title = rec.meeting.title if rec.meeting else f"Raum {rec.room}"
    return f"{title}, {to_local(rec.created_at):%d.%m.%Y %H:%M} Uhr"


def _recipients(db, rec: Recording) -> list[str]:
    if rec.meeting and rec.meeting.owner and rec.meeting.owner.active:
        return [rec.meeting.owner.email]
    return list(db.scalars(select(User.email).where(User.is_admin.is_(True), User.active.is_(True))))


def notify_recording(db, rec: Recording, event: str) -> None:
    """event: new_recording | done | failed. Muss vor db.commit() aufgerufen werden."""
    cfg = get_settings(db)
    if cfg.get(f"notify_{event}") != "1":
        return
    link = f"{settings.portal_base_url}/recordings/{rec.id}"
    label = _recording_label(rec)
    if event == "new_recording":
        subject = f"Neue Aufnahme: {label}"
        body = (f"Die Aufnahme „{label}“ ist abgeschlossen und liegt als MP3 vor.\n\n"
                f"Dort können Sie die MP3 herunterladen oder die Transkription in SpeechMind starten:\n{link}\n")
    elif event == "done":
        subject = f"Transkript fertig: {label}"
        body = f"SpeechMind hat die Aufnahme „{label}“ verarbeitet.\n\nProtokoll und Wortlaut:\n{link}\n"
    else:
        subject = f"Transkription fehlgeschlagen: {label}"
        body = (f"Bei der Aufnahme „{label}“ ist ein Fehler aufgetreten:\n\n{rec.error or 'unbekannt'}\n\n"
                f"Details und erneuter Versuch:\n{link}\n")
    for addr in _recipients(db, rec):
        enqueue(db, addr, subject, body + _footer(), event)
