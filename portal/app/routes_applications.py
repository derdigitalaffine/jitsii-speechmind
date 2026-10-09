"""Online-Anträge: Einstellungen je Antrag, Antragseingang, Vorgang, Statusseite und öffentlicher Antragskatalog."""

import json
import re
from datetime import datetime, timezone

from fastapi import Depends, Form as FormField, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import applications as apps, forms as fm, icons, worker, workflow
from .config import settings
from .db import LOCAL_TZ, Form, FormResponse, Group, Process, User, get_settings, set_setting, utcnow
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
    if level == 0 or form.deleted_at:
        raise HTTPException(404, "Formular nicht gefunden.")
    if form.archived_at and need >= fm.INVITE:
        raise HTTPException(409, "Archiviertes Formular: Zum Bearbeiten zuerst wiederherstellen.")
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
    from . import orgs
    auto = apps.style_of(Form(title=form.title, app_category=form.app_category), apps.category_styles(db))
    return render(request, "form_application.html", user, **_ctx(db, form, "application", level),
                  org_options=orgs.options(db), icon_list=icons.picker_data(), icon_auto=auto["icon"], icon_color=auto["color"],
                  questions=fm.questions(items), rules=apps.routing_rules(form),
                  users=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all(),
                  groups=db.scalars(select(Group).order_by(Group.name)).all(),
                  has_email=any(q["type"] == "short" and q.get("subtype") == "email" for q in fm.questions(items)),
                  catalog_url=f"{request.base_url}antraege", mail_ready=apps.mail_ready(db),
                  processes=workflow.processes_for_select(db), can_processes=user.can("processes"),
                  dms_areas=_dms_areas(db) if "dms" in enabled_modules() else [], **_legal_ctx(db, form))


def _legal_ctx(db, form) -> dict:
    """Auswahl der Rechtsgrundlagen (nur mit eingeschaltetem Modul Rechtstexte)."""
    if "laws" not in enabled_modules():
        return {"laws": [], "legal": []}
    import json as _json
    from .db import LawText
    try:
        legal = _json.loads(form.legal_json or "[]")
    except ValueError:
        legal = []
    return {"laws": db.scalars(select(LawText).order_by(LawText.title)).all(), "legal": legal if isinstance(legal, list) else []}


def _dms_areas(db) -> list:
    from . import dms
    by_id = {a.id: a for a in dms.areas(db)}
    return [(a, dms.label(a, by_id)) for a, _d in dms.tree(db)]


@app.post("/forms/{form_id:int}/application", dependencies=[Depends(check_csrf)])
async def form_application_save(request: Request, form_id: int, user: User = Depends(current_user),
                                db: Session = Depends(get_db)):
    _module_on()
    form, _ = _form(db, form_id, user, fm.EDIT)
    data = await request.form()
    kind = "application" if data.get("is_application") == "1" else "survey"
    if kind != form.kind and not user.can("app_create"):
        flash(request, "Ob ein Formular als Online-Antrag läuft, darf nur ändern, wer das Recht "
                       "„Online-Anträge einrichten“ hat. Die übrigen Einstellungen wurden gespeichert.", "error")
    else:
        form.kind = kind
    prefix = re.sub(r"[^A-Z0-9]", "", str(data.get("app_prefix", "")).upper())[:10]
    form.app_prefix = prefix
    form.app_category = " ".join(str(data.get("app_category", "")).split())[:100]
    if "app_icon" in data:
        form.app_icon = icons.clean(str(data.get("app_icon", "")))
        color = str(data.get("app_color", "")).strip()
        form.app_color = color if apps.COLOR_RE.match(color) and data.get("app_color_on") == "1" else ""
    oid = str(data.get("org_id", "") or "")
    from .db import Organization
    form.org_id = int(oid) if oid.isdigit() and db.get(Organization, int(oid)) else None
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
    if "dms_area_id" in data:
        aid = str(data.get("dms_area_id", ""))
        from .db import DmsArea
        form.dms_area_id = int(aid) if aid.isdigit() and db.get(DmsArea, int(aid)) else None
    if "process_id" in data:
        pid = str(data.get("process_id", ""))
        form.process_id = int(pid) if pid.isdigit() and db.get(Process, int(pid)) else None
    if "legal_law" in data:
        from . import laws
        form.legal_json = json.dumps(laws.clean_form_refs(db, data.getlist("legal_law"), data.getlist("legal_para")),
                                     ensure_ascii=False)
        laws.invalidate_refs()
    form.app_catalog = data.get("app_catalog") == "1"
    form.app_pdf = data.get("app_pdf") == "1"
    rules = [{"question": q, "value": v, "user_id": u, "group_id": g, "email": e} for q, v, u, g, e in zip(
        data.getlist("rule_question"), data.getlist("rule_value"), data.getlist("rule_user"),
        data.getlist("rule_group"), data.getlist("rule_email"))]
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
    cat_rows = []
    if user.is_admin or user.can("app_create"):
        styles = apps.category_styles(db)
        names = sorted({f.app_category or "Allgemein" for f in db.scalars(select(Form).where(Form.kind == "application"))})
        cat_rows = [{"name": c, "icon": styles.get(c, {}).get("icon", ""), "color": styles.get(c, {}).get("color", ""),
                     "auto": icons.suggest(c) or icons.DEFAULT, "auto_color": icons.color_for(c)} for c in names]
    return render(request, "applications.html", user, items=items, counts=counts, statuses=apps.STATUSES,
                  filt={"status": status, "form": form, "scope": scope, "q": q}, forms=forms, now=now,
                  cfg=get_settings(db), cat_rows=cat_rows, icon_list=icons.picker_data() if cat_rows else [])


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
    task = workflow.open_task(resp)
    step = workflow.step_of(task) if task else None
    answers = workflow.current_answers(resp)
    compose = None
    if task and task.kind == "request" and task.state == "open" and step:
        titles = {(q.get("title") or "").strip().lower(): q["id"] for q in fm.questions(items)}
        compose = {"task_id": task.id, "title": step.get("public_name") or step["name"],
                   "message": workflow.fill(step.get("message", ""), resp), "items": step.get("items", []),
                   "reopen": [titles[t.strip().lower()] for t in step.get("reopen", []) if t.strip().lower() in titles],
                   "due_days": step.get("due_days") or 14}
    geo_features = [f for q in fm.questions(items) if q["type"] == "geo"
                    for f in fm.geo_features(answers.get(q["id"]), q.get("title") or "Ort")]
    from .routes_maps import map_bundle
    import json
    from . import fees, payments as pay
    case_payments = [p for p in [fees.payment_of(db, resp)] + [workflow.payment_of_task(db, t) for t in resp.tasks
                                                                if t.kind == "payment"] if p is not None]
    case_payments = [pay.box(db, user, p, f"/forms/{resp.form_id}/applications/{resp.id}") for p in case_payments]
    return render(request, "application.html", user, resp=resp, form=resp.form, level=level, items=items, case_payments=case_payments,
                  questions=workflow.case_questions(resp), display=fm.display, statuses=apps.STATUSES, closed=apps.CLOSED,
                  users=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all(),
                  groups=db.scalars(select(Group).order_by(Group.name)).all(), now=utcnow(),
                  track_link=apps.track_link(resp), applicant=apps.applicant_email(resp.form, resp),
                  checksum_ok=apps.checksum(resp) == resp.checksum, mail_ready=apps.mail_ready(db),
                  task=task, step=step, geo_features=geo_features, compose=compose,
                  geo_bundle=map_bundle(db, request, user, None, "forms") if geo_features else None,
                  can_work=bool(task and workflow.can_work(db, user, task)),
                  four_eyes=workflow.four_eyes_block(task, user) if task and task.kind == "approval" else "",
                  steps=workflow.steps_of(resp), step_types=workflow.STEP_TYPES, current=workflow.current_answers(resp),
                  corrections=workflow.corrections(resp), fields=resp.fields,
                  field_labels={f["key"]: f["label"] for s in workflow.steps_of(resp) for f in s.get("fields", [])},
                  can_start=bool(not resp.process_version_id and not resp.closed_at and resp.form.process
                                 and resp.form.process.current),
                  request_bundle=({"types": {k: fm.TYPES[k][:2] for k in workflow.REQUEST_TYPES},
                                             "subtypes": fm.SUBTYPES,
                                             "order": {"types": list(workflow.REQUEST_TYPES), "subtypes": list(fm.SUBTYPES)},
                                             "templates": [{"id": t.id, "name": t.name, "message": t.message,
                                                            "items": json.loads(t.schema_json or "[]"), "due_days": t.due_days}
                                                           for t in workflow.request_templates(db)]}))


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

def _tracked(db: Session, token: str, request: Request) -> FormResponse:
    resp = db.scalar(select(FormResponse).where(FormResponse.track_token == token)) if len(token) > 20 else None
    if resp is None:
        raise HTTPException(404, "Diesen Antrag gibt es nicht (mehr). Bitte prüfen Sie den Link aus Ihrer Eingangsbestätigung.")
    from .form_access import response_access
    response_access(request, db, resp)
    return resp


@app.get("/a/{token}")
def application_status(request: Request, token: str, db: Session = Depends(get_db)):
    resp = _tracked(db, token, request)
    items = fm.schema(resp.form)
    response = render(request, "application_status.html", session_user(request, db), resp=resp, form=resp.form,
                      questions=workflow.case_questions(resp), display=fm.display, statuses=apps.STATUSES, closed=apps.CLOSED,
                      events=[e for e in resp.events if e.public], progress=workflow.progress(resp),
                      open_requests=workflow.open_requests(resp), current=workflow.current_answers(resp),
                      confirm_task=workflow.open_confirm(resp), applicant=apps.applicant_email(resp.form, resp),
                      corrections=workflow.corrections(resp), documents=[d for d in resp.documents if d.public],
                      open_payments=_open_payments(db, resp), money=_money)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"   # geheimer Link soll nicht weitergegeben werden
    return response


@app.post("/a/{token}/reply", dependencies=[Depends(check_csrf)])
def application_reply(request: Request, token: str, text: str = FormField(""), db: Session = Depends(get_db)):
    rate_limit(request, "app-reply", limit=10)
    resp = _tracked(db, token, request)
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
    resp = _tracked(db, token, request)
    if not resp.closed_at:
        apps.withdraw(db, resp)
        db.commit()
        worker.wake()
        flash(request, "Ihr Antrag wurde zurückgezogen.")
    return redirect(f"/a/{token}")


@app.get("/a/{token}/pdf")
def application_status_pdf(request: Request, token: str, db: Session = Depends(get_db)):
    resp = _tracked(db, token, request)
    return Response(apps.pdf(resp.form, resp), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{resp.ref_no}.pdf"',
                             "Cache-Control": "no-store"})


# --- Öffentlicher Antragskatalog ---------------------------------------------------------

CATALOG_VIEWS = ("karten", "tabelle")


def _catalog(request: Request, db: Session, embed: bool):
    cfg = get_settings(db)
    if embed and cfg.get("apps_embed", "1") != "1":
        raise HTTPException(404, "Das Einbinden des Antragskatalogs ist abgeschaltet.")
    forms = apps.catalog(db)
    cats: dict[str, list[Form]] = {}
    for f in forms:
        cats.setdefault(f.app_category or "Allgemein", []).append(f)
    user = None if embed else session_user(request, db)
    legal = {}
    if "laws" in enabled_modules():
        from . import laws
        legal = {f.id: laws.form_refs(db, f) for f in forms}
    org_list = sorted({f.org for f in forms if f.org is not None}, key=lambda o: (o.position, o.name))
    cat_styles = apps.category_styles(db)
    styles = {f.id: apps.style_of(f, cat_styles) for f in forms}
    # Ansicht: ?ansicht=…, sonst zuletzt gewählt (Cookie), sonst Voreinstellung der Verwaltung
    chosen = request.query_params.get("ansicht", "")
    view = chosen if chosen in CATALOG_VIEWS else request.cookies.get("jsm_app_catalog_view", "")
    view = view if view in CATALOG_VIEWS else (cfg.get("apps_catalog_view") if cfg.get("apps_catalog_view") in CATALOG_VIEWS else "karten")
    response = render(request, "antraege.html", user, cats=cats, total=len(forms), embed=embed, legal=legal, org_list=org_list,
                      layout="base_embed.html" if embed else "base.html", R="/antraege-embed" if embed else "/antraege",
                      embed_label="Online-Anträge", embed_icon="fa-file-signature", styles=styles, view=view,
                      embed_public_path="/antraege", public_link=fm.public_link)
    if chosen in CATALOG_VIEWS:
        response.set_cookie("jsm_app_catalog_view", chosen, max_age=365 * 86400, httponly=True, samesite="lax",
                            secure=settings.secure_cookies)
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
                          apps_catalog_view: str = FormField("karten"),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(403)
    origins = [o.strip().rstrip("/") for o in re.split(r"[\s,;]+", apps_embed_origins) if o.strip()]
    set_setting(db, "apps_embed", "1" if apps_embed == "1" else "0")
    set_setting(db, "apps_embed_origins", " ".join(origins))
    set_setting(db, "apps_catalog_view", apps_catalog_view if apps_catalog_view in CATALOG_VIEWS else "karten")
    db.commit()
    flash(request, "Einstellungen zum Antragskatalog gespeichert.")
    return redirect("/forms/applications#katalog")


@app.post("/forms/applications/categories", dependencies=[Depends(check_csrf)])
async def applications_categories(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Symbol und Farbe je Kategorie (gelten für alle Anträge der Kategorie ohne eigene Wahl)."""
    if not (user.is_admin or user.can("app_create")):
        raise HTTPException(403)
    data = await request.form()
    styles = {}
    for cat, icon, color, on in zip(data.getlist("cat"), data.getlist("cat_icon"), data.getlist("cat_color"),
                                    data.getlist("cat_color_on")):
        cat = " ".join(str(cat).split())[:100]
        st = {"icon": icons.clean(str(icon)), "color": str(color) if on == "1" and apps.COLOR_RE.match(str(color)) else ""}
        if cat and (st["icon"] or st["color"]):
            styles[cat] = st
    set_setting(db, "apps_category_styles", json.dumps(styles, ensure_ascii=False))
    db.commit()
    flash(request, "Symbole der Kategorien gespeichert.")
    return redirect("/forms/applications#kategorien")




def _open_payments(db, resp):
    from . import fees
    found = [fees.payment_of(db, resp)] + [workflow.payment_of_task(db, t) for t in resp.tasks if t.kind == "payment"]
    return [p for p in found if p is not None and p.status in ("open", "pending")]


def _money(cents):
    from .payments import money
    return money(cents)
