"""Online-Anträge: Einstellungen je Antrag, Antragseingang, Vorgang, Statusseite und öffentlicher Antragskatalog."""

import re
from datetime import datetime, timezone

from fastapi import Depends, Form as FormField, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import applications as apps, forms as fm, worker
from .db import LOCAL_TZ, Form, FormResponse, Group, User, get_settings, set_setting, utcnow
from .main import (
    app, check_csrf, current_user, enabled_modules, flash, get_db, rate_limit, redirect, render, session_user,
)
from .planning import EMAIL_RE


def _module_on() -> None:
    if "applications" not in enabled_modules():
        raise HTTPException(404, "Online-Anträge sind auf diesem Server nicht eingeschaltet.")


def _form(db: Session, form_id: int, user: User, need: int) -> tuple[Form, int]:
    form = db.get(Form, form_id)
    level = fm.access_level(db, form, user) if form is not None else 0
    if level == 0:
        raise HTTPException(404, "Formular nicht gefunden.")
    if level < need:
        raise HTTPException(403, "Für diese Aktion reicht Ihre Freigabe nicht aus.")
    return form, level


# --- Einstellungen (Reiter „Antrag“) -------------------------------------------------------

@app.get("/forms/{form_id:int}/application")
def form_application(request: Request, form_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    form, level = _form(db, form_id, user, fm.EDIT)
    from .routes_forms import _ctx
    items = fm.schema(form)
    return render(request, "form_application.html", user, **_ctx(db, form, "application", level),
                  questions=fm.questions(items), rules=apps.routing_rules(form),
                  users=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all(),
                  groups=db.scalars(select(Group).order_by(Group.name)).all(),
                  has_email=any(q["type"] == "short" and q.get("subtype") == "email" for q in fm.questions(items)),
                  catalog_url=f"{request.base_url}antraege", mail_ready=apps.mail_ready(db))


@app.post("/forms/{form_id:int}/application", dependencies=[Depends(check_csrf)])
async def form_application_save(request: Request, form_id: int, user: User = Depends(current_user),
                                db: Session = Depends(get_db)):
    _module_on()
    form, _ = _form(db, form_id, user, fm.EDIT)
    data = await request.form()
    form.kind = "application" if data.get("is_application") == "1" else "survey"
    prefix = re.sub(r"[^A-Z0-9]", "", str(data.get("app_prefix", "")).upper())[:10]
    form.app_prefix = prefix
    form.app_category = " ".join(str(data.get("app_category", "")).split())[:100]
    form.app_info = str(data.get("app_info", "")).replace("\r\n", "\n").strip()[:5000]
    form.app_fee = " ".join(str(data.get("app_fee", "")).split())[:255]
    form.app_duration = " ".join(str(data.get("app_duration", "")).split())[:255]
    form.app_assignee_id = int(data["app_assignee_id"]) if str(data.get("app_assignee_id", "")).isdigit() else None
    form.app_group_id = int(data["app_group_id"]) if str(data.get("app_group_id", "")).isdigit() else None
    mailbox = str(data.get("app_mailbox", "")).strip().lower()[:255]
    form.app_mailbox = mailbox if EMAIL_RE.match(mailbox or "-") else ""
    try:
        form.app_deadline_days = max(0, min(365, int(data.get("app_deadline_days", 14) or 0)))
    except ValueError:
        form.app_deadline_days = 14
    form.app_catalog = data.get("app_catalog") == "1"
    form.app_pdf = data.get("app_pdf") == "1"
    rules = [{"question": q, "value": v, "user_id": u, "group_id": g, "email": e} for q, v, u, g, e in zip(
        data.getlist("rule_question"), data.getlist("rule_value"), data.getlist("rule_user"),
        data.getlist("rule_group"), data.getlist("rule_email"))]
    import json
    form.app_routing_json = json.dumps(apps.clean_rules(rules, fm.schema(form)), ensure_ascii=False)
    if mailbox and not form.app_mailbox:
        flash(request, "Die Adresse des Funktionspostfachs ist ungültig und wurde nicht übernommen.", "error")
    if form.kind == "application" and not form.public_token and form.app_catalog:
        from .security import new_link_token
        form.public_token = new_link_token()   # Anträge im Katalog brauchen einen öffentlichen Link
    db.commit()
    flash(request, "Antragseinstellungen gespeichert." + (" Das Formular ist jetzt ein Online-Antrag." if form.kind == "application" else ""))
    return redirect(f"/forms/{form.id}/application")


# --- Antragseingang ----------------------------------------------------------------------

def _local_date(value: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        return None
    return d.replace(hour=23, minute=59, tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


@app.get("/forms/applications")
def applications_inbox(request: Request, status: str = "open", form: str = "", scope: str = "all", q: str = "",
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    base = apps.inbox_query(db, user)
    visible = db.scalars(base).all()
    now = utcnow()
    counts = {"open": sum(1 for r in visible if not r.closed_at), "overdue": sum(1 for r in visible if not r.closed_at and r.due_at and r.due_at < now),
              "mine": sum(1 for r in visible if not r.closed_at and r.assignee_id == user.id), "all": len(visible)}
    for key in apps.STATUSES:
        counts[key] = sum(1 for r in visible if r.status == key)
    items = visible
    if status == "open":
        items = [r for r in items if not r.closed_at]
    elif status == "overdue":
        items = [r for r in items if not r.closed_at and r.due_at and r.due_at < now]
    elif status in apps.STATUSES:
        items = [r for r in items if r.status == status]
    if scope == "mine":
        groups = set(apps._group_ids(db, user))
        items = [r for r in items if r.assignee_id == user.id or (r.group_id in groups)]
    if form.isdigit():
        items = [r for r in items if r.form_id == int(form)]
    if q.strip():
        needle = q.strip().lower()
        items = [r for r in items if needle in " ".join([r.ref_no or "", r.name, r.email, r.form.title]).lower()]
    items.sort(key=lambda r: (r.closed_at is not None, r.due_at or datetime.max, r.id))
    forms = sorted({r.form for r in visible}, key=lambda f: f.title)
    return render(request, "applications.html", user, items=items, counts=counts, statuses=apps.STATUSES,
                  filt={"status": status, "form": form, "scope": scope, "q": q}, forms=forms, now=now,
                  cfg=get_settings(db))


def _application(db: Session, form_id: int, resp_id: int, user: User, need: int) -> tuple[FormResponse, int]:
    resp = db.get(FormResponse, resp_id)
    if resp is None or resp.form_id != form_id or not resp.ref_no:
        raise HTTPException(404, "Antrag nicht gefunden.")
    level = apps.access(db, user, resp)
    if level == 0:
        raise HTTPException(404, "Antrag nicht gefunden.")
    if level < need:
        raise HTTPException(403, "Sie dürfen diesen Antrag nur ansehen.")
    return resp, level


@app.get("/forms/{form_id:int}/applications/{resp_id:int}")
def application_detail(request: Request, form_id: int, resp_id: int, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    _module_on()
    resp, level = _application(db, form_id, resp_id, user, 1)
    items = fm.schema(resp.form)
    return render(request, "application.html", user, resp=resp, form=resp.form, level=level, items=items,
                  questions=fm.questions(items), display=fm.display, statuses=apps.STATUSES, closed=apps.CLOSED,
                  users=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all(),
                  groups=db.scalars(select(Group).order_by(Group.name)).all(), now=utcnow(),
                  track_link=apps.track_link(resp), applicant=apps.applicant_email(resp.form, resp),
                  checksum_ok=apps.checksum(resp) == resp.checksum, mail_ready=apps.mail_ready(db))


@app.post("/forms/{form_id:int}/applications/{resp_id:int}/action", dependencies=[Depends(check_csrf)])
async def application_action(request: Request, form_id: int, resp_id: int, user: User = Depends(current_user),
                             db: Session = Depends(get_db)):
    _module_on()
    resp, _ = _application(db, form_id, resp_id, user, 2)
    data = await request.form()
    action = data.get("action")
    text = str(data.get("text", "")).replace("\r\n", "\n").strip()[:20000]
    if action == "status":
        status = str(data.get("status", ""))
        if status not in apps.STATUSES:
            raise HTTPException(400)
        apps.set_status(db, resp, status, text, user, inform=data.get("inform") == "1")
        flash(request, f"Status: {apps.status_label(status)}." + (" Die antragstellende Person wird informiert." if data.get("inform") == "1" else ""))
    elif action == "message":
        if not text:
            flash(request, "Bitte eine Nachricht eingeben.", "error")
        else:
            apps.message(db, resp, text, user)
            flash(request, "Nachricht an die antragstellende Person wird verschickt.")
    elif action == "note":
        if text:
            apps.note(resp, text, user)
            flash(request, "Interne Notiz gespeichert.")
    elif action == "assign":
        uid = int(data["user_id"]) if str(data.get("user_id", "")).isdigit() else None
        gid = int(data["group_id"]) if str(data.get("group_id", "")).isdigit() else None
        apps.assign(db, resp, uid, gid, user)
        flash(request, "Zuständigkeit geändert.")
    elif action == "due":
        due = _local_date(str(data.get("due", ""))) if data.get("due") else None
        apps.set_due(resp, due, user)
        flash(request, "Frist geändert.")
    elif action == "take":
        apps.assign(db, resp, user.id, resp.group_id, user)
        if resp.status == "received":
            apps.set_status(db, resp, "in_progress", "", user, inform=data.get("inform") == "1")
        flash(request, "Sie bearbeiten diesen Antrag.")
    else:
        raise HTTPException(400)
    db.commit()
    worker.wake()
    return redirect(f"/forms/{form_id}/applications/{resp_id}#verlauf")


@app.get("/forms/{form_id:int}/applications/{resp_id:int}/pdf")
def application_pdf(form_id: int, resp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    resp, _ = _application(db, form_id, resp_id, user, 1)
    return Response(apps.pdf(resp.form, resp), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{resp.ref_no}.pdf"'})


# --- Statusseite für Antragsteller:innen -----------------------------------------------

def _tracked(db: Session, token: str) -> FormResponse:
    resp = db.scalar(select(FormResponse).where(FormResponse.track_token == token)) if len(token) > 20 else None
    if resp is None:
        raise HTTPException(404, "Diesen Antrag gibt es nicht (mehr). Bitte prüfen Sie den Link aus Ihrer Eingangsbestätigung.")
    return resp


@app.get("/a/{token}")
def application_status(request: Request, token: str, db: Session = Depends(get_db)):
    resp = _tracked(db, token)
    items = fm.schema(resp.form)
    response = render(request, "application_status.html", session_user(request, db), resp=resp, form=resp.form,
                      questions=fm.questions(items), display=fm.display, statuses=apps.STATUSES, closed=apps.CLOSED,
                      events=[e for e in resp.events if e.public])
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"   # geheimer Link soll nicht weitergegeben werden
    return response


@app.post("/a/{token}/reply", dependencies=[Depends(check_csrf)])
def application_reply(request: Request, token: str, text: str = FormField(""), db: Session = Depends(get_db)):
    rate_limit(request, "app-reply", limit=10)
    resp = _tracked(db, token)
    text = text.replace("\r\n", "\n").strip()[:10000]
    if resp.closed_at:
        flash(request, "Der Antrag ist abgeschlossen. Bitte wenden Sie sich direkt an die Verwaltung.", "error")
    elif not text:
        flash(request, "Bitte eine Nachricht eingeben.", "error")
    else:
        apps.applicant_reply(db, resp, text)
        db.commit()
        worker.wake()
        flash(request, "Ihre Nachricht wurde übermittelt.")
    return redirect(f"/a/{token}")


@app.post("/a/{token}/withdraw", dependencies=[Depends(check_csrf)])
def application_withdraw(request: Request, token: str, db: Session = Depends(get_db)):
    rate_limit(request, "app-reply", limit=10)
    resp = _tracked(db, token)
    if not resp.closed_at:
        apps.withdraw(db, resp)
        db.commit()
        worker.wake()
        flash(request, "Ihr Antrag wurde zurückgezogen.")
    return redirect(f"/a/{token}")


@app.get("/a/{token}/pdf")
def application_status_pdf(token: str, db: Session = Depends(get_db)):
    resp = _tracked(db, token)
    return Response(apps.pdf(resp.form, resp), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{resp.ref_no}.pdf"',
                             "Cache-Control": "no-store"})


# --- Öffentlicher Antragskatalog ---------------------------------------------------------

def _catalog(request: Request, db: Session, embed: bool):
    if embed and get_settings(db).get("apps_embed", "1") != "1":
        raise HTTPException(404, "Das Einbinden des Antragskatalogs ist abgeschaltet.")
    forms = apps.catalog(db)
    cats: dict[str, list[Form]] = {}
    for f in forms:
        cats.setdefault(f.app_category or "Allgemein", []).append(f)
    user = None if embed else session_user(request, db)
    response = render(request, "antraege.html", user, cats=cats, total=len(forms), embed=embed,
                      layout="base_embed.html" if embed else "base.html", R="/antraege-embed" if embed else "/antraege",
                      embed_label="Online-Anträge", embed_icon="fa-file-signature",
                      embed_public_path="/antraege", public_link=fm.public_link)
    if not user and "jsm_session" not in request.cookies:
        request.session.clear()
    return response


@app.get("/antraege")
def applications_catalog(request: Request, db: Session = Depends(get_db)):
    return _catalog(request, db, False)


@app.get("/antraege-embed")
def applications_catalog_embed(request: Request, db: Session = Depends(get_db)):
    return _catalog(request, db, True)


@app.post("/forms/applications/settings", dependencies=[Depends(check_csrf)])
def applications_settings(request: Request, apps_embed: str = FormField(""), apps_embed_origins: str = FormField(""),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(403)
    origins = [o.strip().rstrip("/") for o in re.split(r"[\s,;]+", apps_embed_origins) if o.strip()]
    set_setting(db, "apps_embed", "1" if apps_embed == "1" else "0")
    set_setting(db, "apps_embed_origins", " ".join(origins))
    db.commit()
    flash(request, "Einstellungen zum Antragskatalog gespeichert.")
    return redirect("/forms/applications#katalog")

