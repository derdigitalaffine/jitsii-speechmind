"""Seiten des Formularservers: Verwaltung, Baukasten, Teilen, Auswertung und Ausfüllen."""

import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import Depends, Form as FormField, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from . import forms as fm, shortlinks as sl, worker
from .db import LOCAL_TZ, Form, FormInvite, FormResponse, FormShare, Group, User, get_settings, to_local, utcnow
from .main import (
    app, check_csrf, current_user, flash, get_db, rate_limit, redirect, render, require, session_user,
)
from .planning import parse_emails
from .security import new_link_token

forms_user = require("forms")


SAFE_MIME = {"application/pdf", "text/plain", "text/csv", "application/zip", "application/msword",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.spreadsheet"}


def _form(db: Session, form_id: int, user: User, need: int) -> tuple[Form, int]:
    """Formular mit Zugriffsprüfung. need: fm.VIEW, fm.INVITE, fm.EDIT oder fm.OWNER."""
    form = db.get(Form, form_id)
    level = fm.access_level(db, form, user) if form is not None else 0
    if level == 0:
        raise HTTPException(404, "Formular nicht gefunden.")
    if level < need:
        raise HTTPException(403, "Für diese Aktion reicht Ihre Freigabe für das Formular nicht aus.")
    return form, level


def _parse_local(value: str) -> datetime | None:
    try:
        local = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None) if local else None


def _ctx(db: Session, form: Form, tab: str, level: int) -> dict:
    """Gemeinsame Angaben für die Kopfzeile mit Reitern."""
    return {"form": form, "tab": tab, "level": level, "levels": fm.LEVELS, "is_open": fm.is_open(form), "public_url": fm.public_link(form),
            "response_count": db.scalar(select(func.count(FormResponse.id)).where(FormResponse.form_id == form.id)),
            "types": fm.TYPES}


# --- Übersicht -----------------------------------------------------------------

@app.get("/forms")
def forms_list(request: Request, all: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    show_all = user.is_admin and all == "1"
    own = []
    if user.can("forms"):
        q = select(Form).options(joinedload(Form.owner)).order_by(Form.updated_at.desc())
        if not show_all:
            q = q.where(Form.owner_id == user.id)
        own = db.scalars(q).all()
    shared = [] if show_all else fm.shared_with(db, user)
    counts = dict(db.execute(select(FormResponse.form_id, func.count(FormResponse.id))
                             .group_by(FormResponse.form_id)).all())
    return render(request, "forms.html", user, forms=own, shared=shared, counts=counts, show_all=show_all,
                  is_open=fm.is_open, levels=fm.LEVELS)


@app.post("/forms", dependencies=[Depends(check_csrf)])
def forms_create(request: Request, title: str = FormField(...), user: User = Depends(forms_user),
                 db: Session = Depends(get_db)):
    form = Form(owner_id=user.id, title=" ".join(title.split())[:255] or "Neues Formular",
                schema_json=json.dumps(fm.template_items(), ensure_ascii=False))
    db.add(form)
    db.commit()
    flash(request, "Formular angelegt. Fügen Sie links Fragen und Überschriften hinzu.")
    return redirect(f"/forms/{form.id}")


@app.get("/forms/inbox")
def forms_inbox(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    invites = [i for i in fm.user_invites(db, user) if i.form is not None]
    return render(request, "forms_inbox.html", user, invites=invites, is_open=fm.is_open, link=fm.invite_link)


# --- Baukasten -------------------------------------------------------------------

@app.get("/forms/{form_id}")
def form_builder(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.EDIT)
    return render(request, "form_builder.html", user, **_ctx(db, form, "build", level),
                  schema=fm.schema(form), subtypes=fm.SUBTYPES, max_file_mb=fm.MAX_FILE_MB)


@app.post("/forms/{form_id}/schema", dependencies=[Depends(check_csrf)])
def form_save_schema(request: Request, form_id: int, title: str = FormField(""), description: str = FormField(""),
                     items_json: str = FormField("[]"), user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.EDIT)
    form.title = " ".join(title.split())[:255] or form.title
    form.description = description.replace("\r\n", "\n").strip()[:5000]
    items = fm.clean_schema(items_json)
    form.schema_json = json.dumps(items, ensure_ascii=False)
    form.updated_at = utcnow()
    db.commit()
    flash(request, f"Formular gespeichert ({len(fm.questions(items))} Fragen, {len(fm.pages(items))} Seite(n)).")
    return redirect(f"/forms/{form.id}")


@app.get("/forms/{form_id}/preview")
def form_preview(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.VIEW)
    return _fill_page(request, form, preview=True)


# --- Einstellungen ---------------------------------------------------------------

@app.get("/forms/{form_id}/settings")
def form_settings(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.EDIT)
    expires = to_local(form.expires_at).strftime("%Y-%m-%dT%H:%M") if form.expires_at else ""
    return render(request, "form_settings.html", user, **_ctx(db, form, "settings", level), expires=expires)


@app.post("/forms/{form_id}/settings", dependencies=[Depends(check_csrf)])
async def form_settings_save(request: Request, form_id: int, user: User = Depends(current_user),
                             db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.EDIT)
    data = await request.form()
    flag = lambda key: data.get(key) == "1"  # noqa: E731
    form.active = flag("active")
    form.expires_at = _parse_local(str(data.get("expires_at", "")))
    form.anonymous = flag("anonymous")
    form.multiple = flag("multiple")
    form.confirm_mail = flag("confirm_mail")
    form.submit_message = str(data.get("submit_message", "")).replace("\r\n", "\n").strip()[:5000]
    form.notify = flag("notify")
    emails, bad = parse_emails(str(data.get("notify_to", "")))
    form.notify_to = ", ".join(emails)
    form.notify_answers = flag("notify_answers")
    form.notify_csv = flag("notify_csv")
    form.notify_json = flag("notify_json")
    form.notify_scope = "all" if data.get("notify_scope") == "all" else "single"
    db.commit()
    if bad:
        flash(request, "Ungültige Adresse(n) ignoriert: " + ", ".join(bad), "error")
    flash(request, "Einstellungen gespeichert.")
    return redirect(f"/forms/{form.id}/settings")


# --- Teilen ----------------------------------------------------------------------

@app.get("/forms/{form_id}/share")
def form_share(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.INVITE)
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
    groups = db.scalars(select(Group).order_by(Group.name)).all()
    cfg = get_settings(db)
    return render(request, "form_share.html", user, **_ctx(db, form, "share", level), users=users, groups=groups,
                  invite_link=fm.invite_link, errors=sl.QR_ERRORS, mail_ready=bool(cfg.get("smtp_host")),
                  shortlink_url=("/shortlinks?" + "new=" + quote(fm.public_link(form) or "") + "&title="
                                 + quote(form.title) + "&next=" + quote(f"/forms/{form.id}/share") + "#neu")
                  if form.public_token else "")


@app.get("/forms/{form_id}/qr.{fmt}")
def form_qr(form_id: int, fmt: str, size: int = 10, dark: str = "#000000", light: str = "#ffffff",
            error: str = "m", border: int = 2, download: str = "", user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.INVITE)
    if not form.public_token:
        raise HTTPException(404, "Kein öffentlicher Link.")
    opts = sl.qr_options(fmt, size, dark, light, error, border)
    data, media = sl.qr_image(fm.public_link(form), opts)
    headers = {"Cache-Control": "private, max-age=60"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="qr-formular-{form.id}.{opts["fmt"]}"'
    return Response(data, media_type=media, headers=headers)


@app.post("/forms/{form_id}/public", dependencies=[Depends(check_csrf)])
def form_public(request: Request, form_id: int, action: str = FormField(...), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.INVITE)
    if action == "enable" or action == "renew":
        form.public_token = new_link_token()
        flash(request, "Öffentlicher Link erzeugt." if action == "enable" else
              "Neuer öffentlicher Link erzeugt. Der bisherige funktioniert nicht mehr.")
    elif action == "disable":
        form.public_token = None
        flash(request, "Öffentlicher Link abgeschaltet. Persönliche Einladungslinks gelten weiter.")
    db.commit()
    return redirect(f"/forms/{form.id}/share")


@app.post("/forms/{form_id}/invite", dependencies=[Depends(check_csrf)])
async def form_invite(request: Request, form_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.INVITE)
    data = await request.form()
    user_ids = [int(v) for v in data.getlist("users") if str(v).isdigit()]
    group_ids = [int(v) for v in data.getlist("groups") if str(v).isdigit()]
    emails, bad = parse_emails(str(data.get("emails", "")))
    if bad:
        flash(request, "Ungültige E-Mail-Adresse: " + ", ".join(bad), "error")
        return redirect(f"/forms/{form.id}/share")
    added, skipped, mail_ready = fm.invite(db, form, user, user_ids, group_ids, emails)
    db.commit()
    worker.wake()
    if not added and not skipped:
        flash(request, "Bitte Personen, Gruppen oder E-Mail-Adressen auswählen.", "error")
    else:
        flash(request, f"{added} Person(en) eingeladen" + (f", {skipped} waren schon eingeladen" if skipped else "") + "."
              + ("" if mail_ready else " Mailversand ist nicht eingerichtet: Bitte die persönlichen Links unten "
                                       "selbst weitergeben."))
    return redirect(f"/forms/{form.id}/share#einladungen")


@app.post("/forms/{form_id}/remind", dependencies=[Depends(check_csrf)])
def form_remind(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.INVITE)
    count = fm.remind(db, form, user)
    db.commit()
    worker.wake()
    flash(request, f"Erinnerung an {count} Person(en) wird verschickt." if count else
          "Keine offenen Einladungen (oder Mailversand nicht eingerichtet).")
    return redirect(f"/forms/{form.id}/share#einladungen")


@app.post("/forms/{form_id}/invites/{invite_id}", dependencies=[Depends(check_csrf)])
def form_invite_action(request: Request, form_id: int, invite_id: int, action: str = FormField(...),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.INVITE)
    inv = db.get(FormInvite, invite_id)
    if inv is None or inv.form_id != form.id:
        raise HTTPException(404)
    if action == "delete":
        db.delete(inv)
        flash(request, f"Einladung für {inv.email} entfernt. Der persönliche Link funktioniert nicht mehr.")
    elif action == "resend" and not inv.submitted_at:
        fm.remind(db, form, user, [inv])
        flash(request, f"Erinnerung an {inv.email} wird verschickt.")
    db.commit()
    worker.wake()
    return redirect(f"/forms/{form.id}/share#einladungen")


@app.post("/forms/{form_id}/shares", dependencies=[Depends(check_csrf)])
async def form_share_add(request: Request, form_id: int, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Formular im Portal für Personen oder Gruppen freigeben (nur Besitzer:in bzw. Admin)."""
    form, _ = _form(db, form_id, user, fm.OWNER)
    data = await request.form()
    level = int(data.get("level", 1)) if str(data.get("level", "1")).isdigit() else 1
    level = level if level in fm.LEVELS else 1
    added = 0
    for kind, ids in (("user", data.getlist("users")), ("group", data.getlist("groups"))):
        for raw in ids:
            if not str(raw).isdigit():
                continue
            target = int(raw)
            if kind == "user" and target == form.owner_id:
                continue
            existing = next((sh for sh in form.shares if (sh.user_id if kind == "user" else sh.group_id) == target), None)
            if existing:
                existing.level = level
            else:
                form.shares.append(FormShare(user_id=target if kind == "user" else None,
                                             group_id=target if kind == "group" else None, level=level))
            added += 1
    db.commit()
    flash(request, f"Freigabe für {added} Eintrag/Einträge gespeichert: {fm.LEVELS[level][0]}." if added else
          "Bitte Personen oder Gruppen auswählen.", "ok" if added else "error")
    return redirect(f"/forms/{form.id}/share#freigaben")


@app.post("/forms/{form_id}/shares/{share_id}", dependencies=[Depends(check_csrf)])
def form_share_update(request: Request, form_id: int, share_id: int, action: str = FormField("save"),
                      level: int = FormField(1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, _ = _form(db, form_id, user, fm.OWNER)
    share = db.get(FormShare, share_id)
    if share is None or share.form_id != form.id:
        raise HTTPException(404)
    if action == "delete":
        db.delete(share)
        flash(request, "Freigabe entfernt.")
    elif level in fm.LEVELS:
        share.level = level
        flash(request, f"Freigabe geändert: {fm.LEVELS[level][0]}.")
    db.commit()
    return redirect(f"/forms/{form.id}/share#freigaben")


# --- Auswertung ------------------------------------------------------------------

@app.get("/forms/{form_id}/results")
def form_results(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.VIEW)
    responses = list(form.responses)
    items = fm.questions(fm.schema(form))
    return render(request, "form_results.html", user, **_ctx(db, form, "results", level), responses=responses,
                  items=items, summary=fm.summary(form, responses), display=fm.display)


@app.get("/forms/{form_id}/responses/{response_id}")
def form_response_detail(request: Request, form_id: int, response_id: int, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.VIEW)
    resp = db.get(FormResponse, response_id)
    if resp is None or resp.form_id != form.id:
        raise HTTPException(404)
    ids = [r.id for r in form.responses]
    pos = ids.index(resp.id)
    return render(request, "form_response.html", user, **_ctx(db, form, "results", level), resp=resp,
                  items=fm.questions(fm.schema(form)), display=fm.display, number=pos + 1,
                  prev_id=ids[pos - 1] if pos > 0 else None, next_id=ids[pos + 1] if pos + 1 < len(ids) else None)


@app.post("/forms/{form_id}/responses/{response_id}/delete", dependencies=[Depends(check_csrf)])
def form_response_delete(request: Request, form_id: int, response_id: int, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.EDIT)
    resp = db.get(FormResponse, response_id)
    if resp is None or resp.form_id != form.id:
        raise HTTPException(404)
    db.delete(resp)
    db.commit()
    fm.delete_files(form.id, response_id)
    flash(request, "Antwort gelöscht.")
    return redirect(f"/forms/{form.id}/results#antworten")


@app.post("/forms/{form_id}/responses/delete-all", dependencies=[Depends(check_csrf)])
def form_responses_delete_all(request: Request, form_id: int, user: User = Depends(current_user),
                              db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.EDIT)
    n = len(form.responses)
    for resp in list(form.responses):
        db.delete(resp)
    for inv in form.invites:
        inv.submitted_at = None
    db.commit()
    fm.delete_files(form.id)
    flash(request, f"{n} Antwort(en) gelöscht.")
    return redirect(f"/forms/{form.id}/results")


@app.get("/forms/{form_id}/export.{fmt}")
def form_export(form_id: int, fmt: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.VIEW)
    slug = re.sub(r"[^a-z0-9]+", "-", form.title.lower()).strip("-")[:40] or "formular"
    stamp = to_local(utcnow()).strftime("%Y-%m-%d")
    if fmt == "csv":
        return Response(fm.to_csv(form, list(form.responses)), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{slug}-{stamp}.csv"'})
    if fmt == "json":
        return Response(fm.to_json(form, list(form.responses)), media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{slug}-{stamp}.json"'})
    raise HTTPException(404)


@app.get("/forms/{form_id}/responses/{response_id}/files/{name}")
def form_file(form_id: int, response_id: int, name: str, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.VIEW)
    resp = db.get(FormResponse, response_id)
    if resp is None or resp.form_id != form.id:
        raise HTTPException(404)
    entry = next((f for v in resp.answers.values() if isinstance(v, list)
                  for f in v if isinstance(f, dict) and f.get("file") == name), None)
    path = fm.files_dir(form.id, resp.id) / name
    if entry is None or not path.is_file():
        raise HTTPException(404, "Datei nicht gefunden.")
    # Den vom Browser gemeldeten Typ nur für harmlose Formate übernehmen; immer als Download, nie als Seite
    mime = entry.get("type") or ""
    safe = mime in SAFE_MIME or (mime.startswith("image/") and mime != "image/svg+xml")
    return FileResponse(path, filename=entry.get("name") or name, media_type=mime if safe else "application/octet-stream",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@app.post("/forms/{form_id}/copy", dependencies=[Depends(check_csrf)])
def form_copy(request: Request, form_id: int, user: User = Depends(forms_user), db: Session = Depends(get_db)):
    form, _ = _form(db, form_id, user, fm.VIEW)
    clone = fm.copy_form(db, form, user)
    db.commit()
    flash(request, "Kopie angelegt (ohne Antworten, Einladungen und öffentlichen Link).")
    return redirect(f"/forms/{clone.id}")


@app.post("/forms/{form_id}/delete", dependencies=[Depends(check_csrf)])
def form_delete(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    form, level = _form(db, form_id, user, fm.EDIT)
    db.delete(form)
    db.commit()
    fm.delete_files(form_id)
    flash(request, f"Formular „{form.title}“ mit allen Antworten gelöscht.")
    return redirect("/forms")


# --- Ausfüllen (öffentlich bzw. per persönlichem Link) ------------------------------

def _fill_page(request: Request, form: Form, *, preview: bool = False, action: str = "", invite: FormInvite | None = None,
               values: dict | None = None, errors: dict | None = None, page_index: int = 0, status: int = 200):
    items = fm.schema(form)
    page_list = fm.pages(items)
    for p in page_list:
        for item in p["items"]:
            if item.get("shuffle") and item.get("options"):
                item["options"] = fm.shuffled(item["options"])
    response = render(request, "form_fill.html", None, form=form, pages=page_list, preview=preview, action=action,
                      invite=invite, values=values or {}, errors=errors or {}, page_index=page_index,
                      types=fm.TYPES, other=fm.OTHER)
    response.status_code = status
    return response


def _message(request: Request, form: Form | None, kind: str, status: int = 200):
    response = render(request, "form_message.html", None, form=form, kind=kind)
    response.status_code = status
    return response


def _values_for_redisplay(items: list[dict], data) -> dict:
    """Eingaben nach einem Fehler wieder anzeigen (ohne Dateien)."""
    values = {}
    for q in fm.questions(items):
        name = f"q_{q['id']}"
        if q["type"] == "checkbox":
            values[q["id"]] = data.getlist(name)
        else:
            values[q["id"]] = data.get(name, "")
        values[q["id"] + "__other"] = data.get(name + "__other", "")
    return values


async def _submit(request: Request, db: Session, form: Form, invite: FormInvite | None, action: str):
    rate_limit(request, "form-submit", limit=30)
    data = await request.form()
    if data.get("website"):  # Honigtopf gegen Spam-Bots
        return _message(request, form, "thanks")
    items = fm.schema(form)
    files = {key: [f for f in data.getlist(key) if hasattr(f, "filename")] for key in data.keys()
             if key.startswith("q_")}
    answers, errors, uploads = fm.validate(items, data, files)
    if errors:
        first = next((i for i, p in enumerate(fm.pages(items)) if any(it["id"] in errors for it in p["items"])), 0)
        flash(request, "Bitte prüfen Sie die markierten Angaben.", "error")
        return _fill_page(request, form, action=action, invite=invite, values=_values_for_redisplay(items, data),
                          errors=errors, page_index=first, status=422)
    member = session_user(request, db)
    resp = FormResponse(form_id=form.id, answers_json="{}")
    if invite is not None:
        resp.source = "invite"
        if not form.anonymous:
            resp.name, resp.email, resp.user_id = invite.name, invite.email, invite.user_id
        invite.submitted_at = utcnow()
    elif member is not None:
        resp.source = "user"
        if not form.anonymous:
            resp.name, resp.email, resp.user_id = member.name, member.email, member.id
    db.add(resp)
    db.flush()
    if uploads:
        answers.update(await fm.store_uploads(resp, uploads))
    resp.answers_json = json.dumps(answers, ensure_ascii=False)
    db.flush()
    fm.notify_new_response(db, form, resp)
    email = (invite.email if invite else member.email if member else "") or fm.respondent_email(form, answers)
    fm.confirm_to_respondent(db, form, resp, email, invite.name if invite else member.name if member else "")
    db.commit()
    worker.wake()
    return _message(request, form, "thanks")


def _closed_or_none(request: Request, form: Form | None):
    if form is None:
        return _message(request, None, "invalid", 404)
    if not fm.is_open(form):
        return _message(request, form, "closed")
    return None


@app.get("/f/{token}")
def form_public_fill(request: Request, token: str, db: Session = Depends(get_db)):
    form = db.scalar(select(Form).where(Form.public_token == token)) if len(token) > 10 else None
    return _closed_or_none(request, form) or _fill_page(request, form, action=f"/f/{token}")


@app.post("/f/{token}", dependencies=[Depends(check_csrf)])
async def form_public_submit(request: Request, token: str, db: Session = Depends(get_db)):
    form = db.scalar(select(Form).where(Form.public_token == token)) if len(token) > 10 else None
    return _closed_or_none(request, form) or await _submit(request, db, form, None, f"/f/{token}")


def _invite(db: Session, token: str) -> FormInvite | None:
    return db.scalar(select(FormInvite).where(FormInvite.token == token)) if len(token) > 10 else None


@app.get("/f/i/{token}")
def form_invite_fill(request: Request, token: str, db: Session = Depends(get_db)):
    inv = _invite(db, token)
    form = inv.form if inv else None
    blocked = _closed_or_none(request, form)
    if blocked:
        return blocked
    if inv.submitted_at and not form.multiple:
        return _message(request, form, "done")
    return _fill_page(request, form, action=f"/f/i/{token}", invite=inv)


@app.post("/f/i/{token}", dependencies=[Depends(check_csrf)])
async def form_invite_submit(request: Request, token: str, db: Session = Depends(get_db)):
    inv = _invite(db, token)
    form = inv.form if inv else None
    blocked = _closed_or_none(request, form)
    if blocked:
        return blocked
    if inv.submitted_at and not form.multiple:
        return _message(request, form, "done")
    return await _submit(request, db, form, inv, f"/f/i/{token}")
