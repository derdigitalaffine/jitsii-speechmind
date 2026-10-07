"""Downloads aus Benachrichtigungen: Anmeldung intern, befristetes Token für die eigene Antwort."""

import base64
import hashlib
import json
from urllib.parse import quote

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from . import applications as apps, forms as fm
from .db import FormMailDownload, FormResponse, utcnow
from .main import app, current_user, get_db
from .security import decrypt


def download(bundle, index):
    if bundle is None or bundle.expires_at <= utcnow():
        raise HTTPException(404, "Der Downloadlink ist ungültig oder abgelaufen.")
    atts = json.loads(decrypt(bundle.payload_enc) or "[]")
    if index < 0 or index >= len(atts):
        raise HTTPException(404)
    att = atts[index]
    data = base64.b64decode(att["content_b64"]) if "content_b64" in att else att["content"].encode("utf-8")
    return Response(data, media_type=att.get("mime") or "application/octet-stream",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(att["filename"], safe=""),
                             "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                             "X-Content-Type-Options": "nosniff"})


@app.get("/form-mail/{token}/{index:int}")
def applicant_download(token: str, index: int, db=Depends(get_db)):
    bundle = db.scalar(select(FormMailDownload).where(
        FormMailDownload.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        FormMailDownload.applicant.is_(True))) if len(token) == 43 else None
    return download(bundle, index)


@app.get("/forms/{form_id:int}/responses/{response_id:int}/mail-downloads/{bundle_id:int}/{index:int}")
def staff_download(form_id: int, response_id: int, bundle_id: int, index: int,
                   user=Depends(current_user), db=Depends(get_db)):
    resp = db.get(FormResponse, response_id)
    bundle = db.get(FormMailDownload, bundle_id)
    if resp is None or resp.form_id != form_id or bundle is None or bundle.response_id != resp.id or bundle.applicant:
        raise HTTPException(404)
    form_access = fm.access_level(db, resp.form, user)
    # Exports of all responses require form-wide rights, even for a case assignee.
    atts = json.loads(decrypt(bundle.payload_enc) or "[]")
    needs_form = any(a.get("scope_all") for a in atts)
    if not form_access and (needs_form or not resp.ref_no or not apps.access(db, user, resp)):
        raise HTTPException(404)
    return download(bundle, index)
