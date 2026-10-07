"""Gemeinsame Anhänge und größenbegrenzte Benachrichtigungen für Formulare und Anträge."""

import base64
import hashlib
import io
import json
import mimetypes
import re
import secrets
from datetime import timedelta
from email.policy import SMTP
from pathlib import Path

from sqlalchemy import delete

from . import forms as fm, notify
from .config import settings
from .db import FormMailDownload, SessionLocal, get_settings, utcnow
from .security import encrypt, room_slug

MAX_MAIL_BYTES = 10 * 1024 * 1024
OPTIONS = ("notify_pdf", "notify_files", "pdf_uploads", "confirm_csv", "confirm_json", "confirm_pdf", "confirm_files")


def binary(name, data, mime):
    return {"filename": name, "content_b64": base64.b64encode(data).decode("ascii"), "mime": mime}


def response_pdf(form, resp):
    if form.kind == "application":
        from .applications import pdf
        return pdf(form, resp, with_attachments=form.pdf_uploads)
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from xml.sax.saxutils import escape
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(form.title), styles["Title"])]
    for q in fm.questions(fm.schema(form)):
        story += [Paragraph(escape(q.get("title") or "Angabe"), styles["Heading3"]),
                  Paragraph(escape(fm.display(q, resp.answers.get(q["id"])) or "–").replace("\n", "<br/>"), styles["BodyText"]),
                  Spacer(1, 8)]
    out = io.BytesIO()
    SimpleDocTemplate(out).build(story)
    return out.getvalue()


def attachments(form, resp, *, applicant=False, request=None):
    """Daten: aktueller Stand; Originaldateien: nur diese Einsendung/Nachreichung."""
    prefix = "confirm" if applicant else "notify"
    scope = [resp] if applicant or form.notify_scope != "all" else list(form.responses)
    if not any(r.id == resp.id for r in scope):
        scope.append(resp)
    name = f"{room_slug(form.title)}-{resp.ref_no or resp.id}"
    out = []
    if getattr(form, prefix + "_csv"):
        out.append({"filename": name + ".csv", "content": fm.to_csv(form, scope), "mime": "text/csv", "scope_all": not applicant and form.notify_scope == "all"})
    if getattr(form, prefix + "_json"):
        out.append({"filename": name + ".json", "content": fm.to_json(form, scope), "mime": "application/json", "scope_all": not applicant and form.notify_scope == "all"})
    pdf_on = form.confirm_pdf if applicant else (
        form.app_pdf if form.kind == "application" else form.notify_pdf)
    if pdf_on:
        out.append(binary(name + ".pdf", response_pdf(form, resp), "application/pdf"))
    if getattr(form, prefix + "_files"):
        base = fm.files_dir(form.id, resp.id)
        answers = request.answers if request is not None else resp.answers
        if request is not None:
            base = base / f"req{request.id}"
        used = {a["filename"] for a in out}
        for value in answers.values():
            for f in value if isinstance(value, list) else []:
                if not isinstance(f, dict) or not f.get("file"):
                    continue
                path = (base / f["file"]).resolve()
                if path.parent != base.resolve():
                    raise ValueError("Ungültiger Dateipfad")
                filename = re.sub(r"[\x00-\x1f\x7f]", "", Path(f.get("name") or f["file"]).name) or "Datei"
                original, n = filename, 2
                while filename in used:
                    filename = f"{Path(original).stem}-{n}{Path(original).suffix}"
                    n += 1
                used.add(filename)
                out.append(binary(filename, path.read_bytes(), mimetypes.guess_type(filename)[0] or "application/octet-stream"))
    return out


def enqueue(db, form, resp, to, subject, body, kind, *, applicant=False, request=None, cfg=None, **kwargs):
    cfg = cfg or get_settings(db)
    if not notify.mail_configured(cfg):
        return False
    atts = attachments(form, resp, applicant=applicant, request=request)
    for att in atts:
        att["form_response_id"] = resp.id
        att["applicant"] = applicant
    body, atts = fit(db, form, resp, to, subject, body, atts, cfg, applicant=applicant, reply_to=kwargs.get("reply_to"))
    return notify.enqueue(db, to, subject, body, kind, cfg, attachments=atts or None, **kwargs)


def fit(db, form, resp, to, subject, body, atts, cfg, *, applicant=False, reply_to=None):
    msg = notify._build(cfg, to, subject, body, atts, reply_to)
    if len(msg.as_bytes(policy=SMTP)) > MAX_MAIL_BYTES and atts:
        # Unveränderlicher, verschlüsselter Snapshot; enthält für Bürger niemals andere Antworten.
        db.execute(delete(FormMailDownload).where(FormMailDownload.expires_at < utcnow()))
        token = secrets.token_urlsafe(32) if applicant else None
        bundle = FormMailDownload(response_id=resp.id, applicant=applicant,
                                  token_hash=hashlib.sha256(token.encode()).hexdigest() if token else None,
                                  expires_at=utcnow() + timedelta(days=7), payload_enc=encrypt(json.dumps(atts)))
        db.add(bundle)
        db.flush()
        root = f"{settings.portal_base_url}/form-mail/{token}" if token else (
            f"{settings.portal_base_url}/forms/{form.id}/responses/{resp.id}/mail-downloads/{bundle.id}")
        body += "\n\nDie gesamte E-Mail würde 10 MB überschreiten. Die Anhänge stehen im Portal zum Download bereit (7 Tage):\n"
        body += "\n".join(f"{a['filename']}: {root}/{i}" for i, a in enumerate(atts))
        atts = None
    if len(notify._build(cfg, to, subject, body, atts, reply_to).as_bytes(policy=SMTP)) > MAX_MAIL_BYTES:
        raise notify.MailError("Die E-Mail überschreitet auch ohne Anhänge 10 MB.")
    return body, atts


def purge_expired():
    with SessionLocal() as db:
        db.execute(delete(FormMailDownload).where(FormMailDownload.expires_at <= utcnow()))
        db.commit()
