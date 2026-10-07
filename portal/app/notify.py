"""Benachrichtigungs-Engine: E-Mails über SMTP versenden, optional per IMAP ablegen.

Nachrichten werden zuerst in der Datenbank eingereiht (Tabelle notifications) und vom
Worker verschickt. Dadurch blockiert ein langsamer Mailserver keine Anfrage, und
fehlgeschlagene Mails werden mit wachsendem Abstand erneut versucht.
"""

import html
import imaplib
import re
import json
import logging
import smtplib
import ssl
import time
from datetime import timedelta
import base64
from email.message import EmailMessage, Message
from email.utils import formataddr, formatdate, make_msgid

from sqlalchemy import func, select

from . import branding, mailtpl
from .config import settings
from .db import Notification, Recording, SessionLocal, User, get_settings, to_local, utcnow
from .security import decrypt

log = logging.getLogger("portal.notify")

MAX_ATTEMPTS = 5
RETRY_DELAYS = [timedelta(minutes=m) for m in (1, 5, 15, 60, 240)]
TIMEOUT = 20


def _b() -> dict:
    return branding.load()


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
    return formataddr((cfg.get("mail_from_name") or branding.load()["name"], cfg["mail_from"]))


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

def _build(cfg: dict[str, str], to_addr: str, subject: str, body: str,
           attachments: list[dict] | None = None, reply_to: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _sender(cfg)
    msg["To"] = to_addr
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg["mail_from"].rsplit("@", 1)[-1] or None)
    msg.set_content(body)
    frame = mail_frame(cfg)
    msg.add_alternative(text_to_html(body, frame), subtype="html")
    if frame and frame.get("logo"):
        # Logo als eingebettetes Bild (cid:) – wird ohne Nachladen aus dem Netz angezeigt
        html_part = msg.get_payload()[-1]
        data, sub_type = frame["logo"]
        html_part.add_related(data, maintype="image", subtype=sub_type, cid=f"<{frame['cid']}>", disposition="inline",
                              filename=f"logo.{sub_type}")
    for att in attachments or []:
        method = att.get("calendar_method")
        if method:
            # Kalenderteil als dritte Alternative: daraus macht Outlook die Besprechungsanfrage
            # (Annehmen/Ablehnen). Wichtig: byte-genau mit CRLF-Zeilenenden (RFC 5545); als Text
            # übergeben würde die Mail-Bibliothek sie in LF umwandeln, und Outlook verwirft die Einladung.
            # Kopfzeilen wörtlich wie bei Outlook/Google (method=REQUEST ohne Anführungszeichen):
            # dafür ein einfaches Message-Objekt, dessen Kopfzeilen nicht neu formatiert werden.
            part = Message()
            part["Content-Type"] = f'text/calendar; charset="UTF-8"; method={method}'
            part["Content-Transfer-Encoding"] = "base64"
            part.set_payload(base64.encodebytes(att["content"].encode("utf-8")).decode("ascii"))
            msg.attach(part)
    for att in attachments or []:
        if att.get("calendar_method"):
            msg.add_attachment(att["content"].encode("utf-8"), maintype="application", subtype="ics",
                               filename=att["filename"])
        else:
            maintype, _, subtype = (att.get("mime") or "application/octet-stream").partition("/")
            # Binäre Anhänge (z. B. PDF) liegen base64-kodiert in der Warteschlange
            data = base64.b64decode(att["content_b64"]) if att.get("content_b64") else att["content"].encode("utf-8")
            msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=att["filename"])
    return msg


_URL = re.compile(r"(https?://[^\s<>\"]+)")


def _abs(url: str) -> str:
    return settings.portal_base_url.rstrip("/") + url if url.startswith("/") else url


def mail_frame(cfg: dict[str, str]) -> dict | None:
    """Erscheinungsbild der HTML-Mails (Design & Branding › E-Mails): Farbe, Logo, Name, Fußzeile. None = schlicht."""
    if cfg.get("ui_mail_frame", "1") != "1":
        return None
    from . import branding
    b = branding.build(cfg)
    frame = {"color": b["primary"], "name": b["name"], "footer": b["footer_text"] or f"© {b['name']}",
             "imprint": _abs(b["imprint_url"]), "privacy": _abs(b["privacy_url"]), "logo": None, "cid": "logo@portal"}
    for key in ("ui_logo", "ui_favicon_auto"):
        name, _url = branding._file(cfg, key) if b["custom"] else (None, "")
        ext = (name or "").rsplit(".", 1)[-1].lower()
        if name and ext in ("png", "jpg", "jpeg", "gif"):
            try:
                frame["logo"] = ((branding.BRAND_DIR / name).read_bytes(), "jpeg" if ext == "jpg" else ext)
            except OSError:
                continue
            break
    return frame


def text_to_html(text: str, frame: dict | None = None) -> str:
    """HTML-Fassung des Mailtexts: Absätze, anklickbare Links; mit frame im Rahmen der Organisation
    (Kopfzeile mit Logo und Name in der Hauptfarbe, Fußzeile mit Impressum/Datenschutz). Tabellenlayout mit
    Inline-Stilen, weil viele Mailprogramme kein CSS kennen."""
    escaped = html.escape(text)
    linked = _URL.sub(lambda m: f'<a href="{m.group(1)}" style="color:{(frame or {}).get("color", "#0b57d0")}">{m.group(1)}</a>', escaped)
    paragraphs = "".join(f'<p style="margin:0 0 14px">{p.replace(chr(10), "<br>")}</p>' for p in linked.split("\n\n") if p.strip())
    font = "font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1f2328"
    if not frame:
        return f'<!doctype html><html><body style="{font}">{paragraphs}</body></html>'
    color, name = frame["color"], html.escape(frame["name"])
    from .branding import on_color
    fg = on_color(color)
    logo = (f'<img src="cid:{frame["cid"]}" alt="" height="36" style="height:36px;max-width:180px;vertical-align:middle;'
            f'margin-right:10px;border:0">' if frame.get("logo") else "")
    links = " · ".join(f'<a href="{html.escape(u)}" style="color:#57606a">{label}</a>'
                       for label, u in (("Impressum", frame.get("imprint")), ("Datenschutz", frame.get("privacy"))) if u)
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'</head><body style="margin:0;padding:0;background:#f3f4f6;{font}">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6"><tr><td align="center" style="padding:24px 12px">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e5e7eb">'
            f'<tr><td style="background:{color};color:{fg};padding:14px 20px;font-size:16px;font-weight:600">{logo}{name}</td></tr>'
            f'<tr><td style="padding:22px 20px 8px">{paragraphs}</td></tr>'
            f'<tr><td style="padding:12px 20px 18px;border-top:1px solid #e5e7eb;color:#57606a;font-size:12px">'
            f'{html.escape(frame["footer"])}{"<br>" + links if links else ""}</td></tr>'
            f'</table></td></tr></table></body></html>')


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


def deliver(cfg: dict[str, str], to_addr: str, subject: str, body: str,
            attachments: list[dict] | None = None, reply_to: str | None = None) -> None:
    if not mail_configured(cfg):
        raise MailError("E-Mail-Versand ist nicht eingerichtet.")
    msg = _build(cfg, to_addr, subject, body, attachments, reply_to)
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
    deliver(cfg, to_addr, f"Testnachricht – {_b()['product']}",
            f"Dies ist eine Testnachricht des {_b()['product']}s der "
            f"{_b()['name']}.\n\nDer E-Mail-Versand funktioniert.\n")


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

def enqueue(db, to_addr: str, subject: str, body: str, kind: str, cfg: dict[str, str] | None = None,
            *, attachments: list[dict] | None = None, reply_to: str | None = None,
            per_hour: int | None = None) -> bool:
    """Reiht eine Mail ein. Ohne eingerichteten Versand passiert nichts (False).

    attachments: [{"filename": "einladung.ics", "content": "...", "calendar_method": "REQUEST"}]
    Ein Anhang mit calendar_method wird zusätzlich als Kalenderteil eingebettet, damit Outlook
    die Mail als Besprechungsanfrage (Annehmen/Ablehnen) anzeigt.
    """
    if not mail_configured(cfg or get_settings(db)):
        return False
    if per_hour is not None and _recent(db, to_addr, kind) >= per_hour:
        # Von außen ausgelöste Mails (Eingangsbestätigungen) an dieselbe Adresse begrenzen – sonst ließe sich
        # das Portal mit fremder Adresse und eigenem Text als Spam-Schleuder missbrauchen
        log.warning("Mail an %s (%s) übersprungen: Höchstzahl pro Stunde erreicht", to_addr, kind)
        return False
    db.add(Notification(kind=kind, to_addr=to_addr, subject=subject, body=body, reply_to=reply_to,
                        attachments_json=json.dumps(attachments, ensure_ascii=False) if attachments else None))
    _copy_to_substitute(db, to_addr, subject, body, kind, attachments, reply_to)
    return True


def _copy_to_substitute(db, to_addr, subject, body, kind, attachments, reply_to) -> None:
    """Arbeitsbezogene Benachrichtigungen an eine heute abwesende Person gehen in Kopie an ihre Vertretung."""
    from . import absence
    if kind not in absence.FORWARD_KINDS:
        return
    hit = absence.substitutes_for_addresses(db, [to_addr]).get((to_addr or "").strip().lower())
    if hit is None:
        return
    sub_email, name = hit
    note = f"Sie erhalten diese Nachricht als Vertretung für {name}.\n\n"
    db.add(Notification(kind=f"{kind[:28]}_vt", to_addr=sub_email, subject=f"[Vertretung für {name}] {subject}"[:255],
                        body=note + body, reply_to=reply_to,
                        attachments_json=json.dumps(attachments, ensure_ascii=False) if attachments else None))


def _recent(db, to_addr: str, kind: str) -> int:
    since = utcnow() - timedelta(hours=1)
    return db.scalar(select(func.count(Notification.id)).where(
        func.lower(Notification.to_addr) == to_addr.strip().lower(), Notification.kind == kind,
        Notification.created_at >= since)) or 0


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
                attachments = json.loads(n.attachments_json) if n.attachments_json else None
                # Vertretungsnotiz / geändertes Branding können die endgültige Größe erhöhen.
                if attachments and attachments[0].get("form_response_id"):
                    from . import form_mail
                    from .db import FormResponse
                    resp = db.get(FormResponse, attachments[0]["form_response_id"])
                    if resp is None:
                        raise MailError("Die Formularantwort wurde gelöscht.")
                    n.body, attachments = form_mail.fit(db, resp.form, resp, n.to_addr, n.subject, n.body,
                                                       attachments, cfg, applicant=attachments[0].get("applicant", False),
                                                       reply_to=n.reply_to)
                    n.attachments_json = json.dumps(attachments, ensure_ascii=False) if attachments else None
                deliver(cfg, n.to_addr, n.subject, n.body, attachments=attachments, reply_to=n.reply_to)
            except MailError as exc:
                n.error = str(exc)[:1000]
                if n.attempts >= MAX_ATTEMPTS or not mail_configured(cfg):
                    n.status = "failed"
                    if n.kind == "krank":
                        from . import krank
                        krank.purge_sent(n)
                else:
                    n.next_attempt_at = utcnow() + RETRY_DELAYS[min(n.attempts - 1, len(RETRY_DELAYS) - 1)]
                log.warning("Mail %s an %s: %s", n.id, n.to_addr, exc)
            else:
                n.status, n.error, n.sent_at = "sent", None, utcnow()
                if n.kind == "krank":
                    # Gesundheitsdaten nicht in der Warteschlange aufbewahren (Krankmelder)
                    from . import krank
                    krank.purge_sent(n)
                sent += 1
            db.commit()
    return sent


# --- Nachrichtentexte (bearbeitbar unter Admin > E-Mail-Vorlagen) --------------

def account_link_mail(db, user: User, link: str, kind: str) -> tuple[str, str]:
    """kind: invite | reset"""
    key = "account_invite" if kind == "invite" else "password_reset"
    hours = settings.invite_ttl_hours if kind == "invite" else settings.reset_ttl_hours
    return mailtpl.render(db, key, {"name": user.name, "email": user.email, "link": link,
                                    "gueltig_stunden": hours})


def _recording_label(rec: Recording) -> str:
    title = rec.meeting.title if rec.meeting else f"Raum {rec.room}"
    return f"{title}, {to_local(rec.created_at):%d.%m.%Y %H:%M} Uhr"


def _recipients(db, rec: Recording) -> list[str]:
    if rec.meeting and rec.meeting.owner and rec.meeting.owner.active:
        return [rec.meeting.owner.email]
    return list(db.scalars(select(User.email).where(User.is_admin.is_(True), User.active.is_(True))))


_RECORDING_TEMPLATE = {"new_recording": "recording_new", "done": "recording_done",
                       "failed": "recording_failed", "silent": "recording_silent"}


def notify_recording(db, rec: Recording, event: str) -> None:
    """event: new_recording | done | failed | silent. Muss vor db.commit() aufgerufen werden."""
    cfg = get_settings(db)
    gate = "failed" if event == "silent" else event
    if cfg.get(f"notify_{gate}") != "1" or not mail_configured(cfg):
        return
    subject, body = mailtpl.render(db, _RECORDING_TEMPLATE[event], {
        "aufnahme": _recording_label(rec), "link": f"{settings.portal_base_url}/recordings/{rec.id}",
        "fehler": rec.error or "",
    }, cfg)
    for addr in _recipients(db, rec):
        enqueue(db, addr, subject, body, event, cfg)
