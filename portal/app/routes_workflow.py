"""Workflow für Online-Anträge: Prozesseditor, „Meine Aufgaben“, Arbeitsschritte im Vorgang und Nachforderungen."""

import json
import re
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import applications as apps, forms as fm, worker, workflow as wf
from .db import (
    LOCAL_TZ, ApplicationDocument, ApplicationRequest, ApplicationTask, FormResponse, Group, Process,
    RequestTemplate, User, utcnow,
)
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, session_user, rate_limit, redirect, render, require
from .routes_forms import SAFE_MIME

process_user = require("processes")


def _module_on() -> None:
    if "applications" not in enabled_modules():
        raise HTTPException(404, "Online-Anträge sind auf diesem Server nicht eingeschaltet.")


def _local_date(value: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        return None
    return d.replace(hour=23, minute=59, tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _users(db):
    return db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()


def _groups(db):
    return db.scalars(select(Group).order_by(Group.name)).all()


# --- Meine Aufgaben ----------------------------------------------------------------------

@app.get("/tasks")
def tasks_page(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Meine Aufgaben: Anträge, Ressourcenbuchungen und persönliche Umlauf-Rückmeldungen."""
    mods = enabled_modules()
    if not mods & {"applications", "resources", "circulations"}:
        raise HTTPException(404, "Kein Aufgabenmodul ist eingeschaltet.")
    from . import task_overview
    view = task_overview.collect(db, user, mods, now=utcnow())
    view = task_overview.filtered(view, request.query_params.get('scope', 'all'), request.query_params.get('source', 'all'))
    return render(request, "tasks.html", user, work=view, apps_on="applications" in mods,
                  circulations_on="circulations" in mods, resources_on="resources" in mods)



# --- Arbeitsschritte im Vorgang -----------------------------------------------------------

def _case(db: Session, form_id: int, resp_id: int, user: User) -> tuple[FormResponse, int]:
    resp = db.get(FormResponse, resp_id)
    if resp is None or resp.form_id != form_id or not resp.ref_no:
        raise HTTPException(404, "Antrag nicht gefunden.")
    level = apps.access(db, user, resp)
    if level == 0:
        raise HTTPException(404, "Antrag nicht gefunden.")
    return resp, level


def _back(form_id: int, resp_id: int, anchor: str = "schritt") -> str:
    return f"/forms/{form_id}/applications/{resp_id}#{anchor}"


@app.post("/forms/{form_id:int}/applications/{resp_id:int}/task/{task_id:int}", dependencies=[Depends(check_csrf)])
async def task_action(request: Request, form_id: int, resp_id: int, task_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    _module_on()
    resp, level = _case(db, form_id, resp_id, user)
    task = db.get(ApplicationTask, task_id)
    if task is None or task.response_id != resp.id:
        raise HTTPException(404, "Arbeitsschritt nicht gefunden.")
    data = await request.form()
    action = str(data.get("action", ""))
    comment = str(data.get("comment", "")).replace("\r\n", "\n").strip()[:10000]
    back = str(data.get("back", ""))
    if action in ("done", "approved", "rejected"):
        if not wf.can_work(db, user, task):
            raise HTTPException(403, "Dieser Arbeitsschritt ist einer anderen Person oder Gruppe zugewiesen.")
        values = {k[2:]: v for k, v in data.items() if k.startswith("f_")}
        error = wf.complete(db, task, user, action, comment, [str(c) for c in data.getlist("check")], values)
        if error:
            flash(request, error, "error")
            return redirect(_back(form_id, resp_id))
        flash(request, {"done": "Schritt erledigt.", "approved": "Freigabe erteilt.", "rejected": "Abgelehnt."}[action]
              + _next_hint(resp))
    elif action == "claim":
        if not (wf.can_work(db, user, task) or level >= 2):
            raise HTTPException(403)
        wf.claim(db, task, user)
        flash(request, f"Sie bearbeiten jetzt „{task.name}“.")
    elif action in ("reassign", "due", "skip", "remind"):
        if level < 2:
            raise HTTPException(403, "Sie dürfen diesen Antrag nur ansehen.")
        if task.state not in ("open", "waiting"):
            raise HTTPException(400, "Der Schritt ist nicht mehr offen.")
        if action == "reassign":
            uid = int(data["user_id"]) if str(data.get("user_id", "")).isdigit() else None
            gid = int(data["group_id"]) if str(data.get("group_id", "")).isdigit() else None
            wf.reassign(db, task, uid, gid, user)
            flash(request, "Schritt neu zugewiesen.")
        elif action == "due":
            wf.set_task_due(task, _local_date(str(data.get("due", ""))) if data.get("due") else None, user)
            flash(request, "Frist des Schritts geändert.")
        elif action == "skip":
            wf.skip(db, task, user, comment)
            flash(request, f"„{task.name}“ übersprungen." + _next_hint(resp))
        elif action == "remind" and task.kind == "confirm":
            if wf.send_confirm(db, resp, task):
                apps._event(resp, "task", "Bestätigungslink erneut verschickt", user)
                flash(request, "Bestätigungsmail wird erneut verschickt.")
            else:
                flash(request, "Keine E-Mail-Adresse bekannt.", "error")
        elif action == "remind":
            req = next((r for r in resp.requests if r.task_id == task.id and r.state == "open"), None)
            if req and wf.remind_request(db, resp, req):
                apps._event(resp, "request", f"Erinnerung an die Nachforderung „{req.title}“ gesendet", user)
                flash(request, "Erinnerung wird verschickt.")
            else:
                flash(request, "Keine E-Mail-Adresse bekannt – bitte anders Kontakt aufnehmen.", "error")
    else:
        raise HTTPException(400)
    db.commit()
    worker.wake()
    return redirect("/tasks" if back == "tasks" else _back(form_id, resp_id))


def _next_hint(resp: FormResponse) -> str:
    task = wf.open_task(resp)
    if task is None:
        return " Der Prozess ist abgeschlossen." if resp.process_version_id else ""
    return f" Nächster Schritt: {task.name} ({wf.who(task)})."


@app.post("/forms/{form_id:int}/applications/{resp_id:int}/process", dependencies=[Depends(check_csrf)])
def process_start(request: Request, form_id: int, resp_id: int, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    _module_on()
    resp, level = _case(db, form_id, resp_id, user)
    if level < 2 or resp.closed_at or resp.process_version_id:
        raise HTTPException(400)
    if wf.start(db, resp):
        db.commit()
        worker.wake()
        flash(request, "Prozess gestartet." + _next_hint(resp))
    else:
        flash(request, "Für dieses Antragsformular ist kein veröffentlichter Prozess hinterlegt.", "error")
    return redirect(_back(form_id, resp_id))


# --- Nachforderung (ad hoc) -------------------------------------------------------------

@app.post("/forms/{form_id:int}/applications/{resp_id:int}/request", dependencies=[Depends(check_csrf)])
async def request_create(request: Request, form_id: int, resp_id: int, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    _module_on()
    resp, level = _case(db, form_id, resp_id, user)
    if level < 2 or resp.closed_at:
        raise HTTPException(403)
    data = await request.form()
    try:
        items = json.loads(str(data.get("items_json", "[]")))
    except ValueError:
        items = []
    items = wf.clean_request_items(items)
    known = {q["id"] for q in wf.case_questions(resp)}
    reopen = [q for q in data.getlist("reopen") if q in known]
    message = str(data.get("message", "")).replace("\r\n", "\n").strip()[:10000]
    if not items and not reopen:
        flash(request, "Bitte mindestens ein Feld hinzufügen oder eine Angabe zur Korrektur auswählen.", "error")
        return redirect(_back(form_id, resp_id, "nachfordern"))
    due = _local_date(str(data.get("due", ""))) if data.get("due") else None
    title = " ".join(str(data.get("title", "")).split())[:200] or "Bitte ergänzen Sie Ihren Antrag"
    task = None
    if str(data.get("task_id", "")).isdigit():   # Prozessschritt „Nachforderung – Sachbearbeitung wählt“
        task = db.get(ApplicationTask, int(data["task_id"]))
        if task is None or task.response_id != resp.id or task.kind != "request" or task.state != "open":
            task = None
        elif due:
            task.due_at = due
    wf.create_request(db, resp, title, message, items, reopen, due, user.name, task=task,
                      set_query=data.get("set_query") == "1" or task is not None)
    if task is not None:
        apps._event(resp, "task", f"{task.name}: Nachforderung gestellt von {user.name}", user)
    if data.get("save_template") == "1" and items:
        db.add(RequestTemplate(name=title, message=message, schema_json=json.dumps(items, ensure_ascii=False),
                               due_days=max(1, (due - utcnow()).days + 1) if due else 14))
    db.commit()
    worker.wake()
    to = apps.applicant_email(resp.form, resp)
    flash(request, "Nachforderung gestellt." + (f" {to} erhält eine E-Mail mit dem Link zum Nachreichen." if to and apps.mail_ready(db)
                                                 else " Keine E-Mail möglich – bitte den Statuslink selbst weitergeben."))
    return redirect(_back(form_id, resp_id, "nachforderungen"))


@app.post("/forms/{form_id:int}/applications/{resp_id:int}/request/{req_id:int}", dependencies=[Depends(check_csrf)])
async def request_action(request: Request, form_id: int, resp_id: int, req_id: int, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    _module_on()
    resp, level = _case(db, form_id, resp_id, user)
    req = db.get(ApplicationRequest, req_id)
    if level < 2 or req is None or req.response_id != resp.id or req.state != "open":
        raise HTTPException(404)
    action = (await request.form()).get("action")
    if action == "remind":
        if wf.remind_request(db, resp, req):
            apps._event(resp, "request", f"Erinnerung an die Nachforderung „{req.title}“ gesendet", user)
            flash(request, "Erinnerung wird verschickt.")
        else:
            flash(request, "Keine E-Mail-Adresse bekannt.", "error")
    elif action == "cancel":
        task = db.get(ApplicationTask, req.task_id) if req.task_id else None
        if task and task.state == "waiting":
            wf.skip(db, task, user, "Nachforderung zurückgenommen")
        else:
            req.state = "cancelled"
            apps._event(resp, "request", f"Nachforderung „{req.title}“ zurückgenommen", user, public=True)
            if resp.status == "query" and not wf.open_requests(resp):
                wf._set_status(db, resp, "in_progress", actor_name=user.name)
        flash(request, "Nachforderung zurückgenommen.")
    else:
        raise HTTPException(400)
    db.commit()
    worker.wake()
    return redirect(_back(form_id, resp_id, "nachforderungen"))


def _send_file(path, entry: dict, fallback: str):
    mime = entry.get("type") or ""
    safe = mime in SAFE_MIME or (mime.startswith("image/") and mime != "image/svg+xml")
    return FileResponse(path, filename=entry.get("name") or fallback, media_type=mime if safe else "application/octet-stream",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@app.get("/forms/{form_id:int}/applications/{resp_id:int}/request/{req_id:int}/files/{name}")
def request_file(form_id: int, resp_id: int, req_id: int, name: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    _module_on()
    resp, _ = _case(db, form_id, resp_id, user)
    req = db.get(ApplicationRequest, req_id)
    if req is None or req.response_id != resp.id:
        raise HTTPException(404)
    entry = next((f for v in req.answers.values() if isinstance(v, list) for f in v
                  if isinstance(f, dict) and f.get("file") == name), None)
    path = fm.files_dir(resp.form_id, resp.id) / f"req{req.id}" / name
    if entry is None or not path.is_file():
        raise HTTPException(404, "Datei nicht gefunden.")
    return _send_file(path, entry, name)


def _document(resp: FormResponse, doc_id: int) -> ApplicationDocument:
    doc = next((d for d in resp.documents if d.id == doc_id), None)
    path = wf.documents_dir(resp) / doc.file if doc else None
    if doc is None or not path.is_file():
        raise HTTPException(404, "Dokument nicht gefunden.")
    return doc


@app.get("/forms/{form_id:int}/applications/{resp_id:int}/documents/{doc_id:int}")
def document_download(form_id: int, resp_id: int, doc_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    _module_on()
    resp, _ = _case(db, form_id, resp_id, user)
    doc = _document(resp, doc_id)
    return FileResponse(wf.documents_dir(resp) / doc.file, filename=f"{resp.ref_no}-{doc.name}.pdf",
                        media_type="application/pdf")


@app.post("/forms/{form_id:int}/applications/{resp_id:int}/documents/{doc_id:int}", dependencies=[Depends(check_csrf)])
async def document_toggle(request: Request, form_id: int, resp_id: int, doc_id: int, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    _module_on()
    resp, level = _case(db, form_id, resp_id, user)
    if level < 2:
        raise HTTPException(403)
    doc = _document(resp, doc_id)
    doc.public = not doc.public
    apps._event(resp, "document", f"Dokument „{doc.name}“ " + ("für Antragsteller:in freigegeben" if doc.public else "nicht mehr freigegeben"), user)
    db.commit()
    return redirect(_back(form_id, resp_id, "dokumente"))


# --- Statusseite: Nachforderung beantworten, Dokumente ----------------------------------------

def _tracked(db: Session, token: str, request: Request) -> FormResponse:
    from .routes_applications import _tracked as tracked
    return tracked(db, token, request)


def _request_page(request: Request, db: Session, resp: FormResponse, req: ApplicationRequest, values=None, errors=None):
    from .routes_maps import map_bundle
    items = req.items + wf.reopen_items(resp, req)
    current = wf.current_answers(resp)
    if values is None:   # Korrekturfelder mit den bisherigen Angaben vorbelegen
        values = json.loads(req.prefill_json or "{}")
        for q in wf.reopen_items(resp, req):
            v = current.get(q["id"])
            if q["type"] != "file" and v is not None:
                values[q["id"]] = v
    values = fm.form_fields.profile_values(items,values,session_user(request,db))
    geo = any(i["type"] in ("geo", "route") for i in items)
    response = render(request, "application_request.html", None, resp=resp, req=req, form=resp.form,
                      extra=req.items, reopen=wf.reopen_items(resp, req), values=values, errors=errors or {},
                      types=fm.TYPES, other=fm.OTHER,
                      geo_bundle=map_bundle(db, request, None, None, "forms") if geo else None)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _open_request(resp: FormResponse, req_id: int) -> ApplicationRequest:
    req = next((r for r in resp.requests if r.id == req_id), None)
    if req is None:
        raise HTTPException(404, "Diese Nachforderung gibt es nicht.")
    return req


@app.get("/a/{token}/request/{req_id:int}")
def applicant_request(request: Request, token: str, req_id: int, db: Session = Depends(get_db)):
    resp = _tracked(db, token, request)
    req = _open_request(resp, req_id)
    if req.state != "open":
        flash(request, "Diese Nachforderung ist bereits erledigt." if req.state == "answered" else "Diese Nachforderung wurde zurückgenommen.")
        return redirect(f"/a/{token}")
    return _request_page(request, db, resp, req)


@app.post("/a/{token}/request/{req_id:int}", dependencies=[Depends(check_csrf)])
async def applicant_request_submit(request: Request, token: str, req_id: int, db: Session = Depends(get_db)):
    rate_limit(request, "app-request", limit=20)
    resp = _tracked(db, token, request)
    req = _open_request(resp, req_id)
    if req.state != "open" or resp.closed_at:
        flash(request, "Diese Nachforderung ist nicht mehr offen.", "error")
        return redirect(f"/a/{token}")
    data = await request.form()
    files = {k: [f for f in data.getlist(k) if hasattr(f, "filename")] for k in data.keys()}
    errors = await wf.answer_request(db, resp, req, data, files)
    if errors:
        values = {}
        for item in req.items + wf.reopen_items(resp, req):
            name = f"q_{item['id']}"
            values[item["id"]] = data.getlist(name) if item["type"] == "checkbox" else data.get(name)
        return _request_page(request, db, resp, req, values, errors)
    db.commit()
    worker.wake()
    flash(request, "Vielen Dank – Ihre Angaben wurden übermittelt.")
    return redirect(f"/a/{token}")


@app.get("/a/{token}/confirm/{code}")
def applicant_confirm(request: Request, token: str, code: str, db: Session = Depends(get_db)):
    rate_limit(request, "app-confirm", limit=30)
    resp = _tracked(db, token, request)
    result = wf.confirm(db, resp, code)
    if result == "ok":
        db.commit()
        worker.wake()
        flash(request, "Vielen Dank – Ihre E-Mail-Adresse ist bestätigt. Ihr Antrag wird jetzt bearbeitet.")
    elif result == "done":
        flash(request, "Ihre E-Mail-Adresse wurde bereits bestätigt.")
    else:
        flash(request, "Dieser Bestätigungslink ist ungültig oder abgelaufen.", "error")
    return redirect(f"/a/{token}")


@app.post("/a/{token}/confirm-resend", dependencies=[Depends(check_csrf)])
def applicant_confirm_resend(request: Request, token: str, db: Session = Depends(get_db)):
    rate_limit(request, "app-confirm-resend", limit=3, window=3600)
    resp = _tracked(db, token, request)
    task = wf.open_confirm(resp)
    if task and wf.send_confirm(db, resp, task):
        db.commit()
        worker.wake()
        flash(request, "Wir haben Ihnen den Bestätigungslink erneut geschickt.")
    return redirect(f"/a/{token}")


@app.get("/a/{token}/documents/{doc_id:int}")
def applicant_document(request: Request, token: str, doc_id: int, db: Session = Depends(get_db)):
    resp = _tracked(db, token, request)
    doc = _document(resp, doc_id)
    if not doc.public:
        raise HTTPException(404, "Dokument nicht gefunden.")
    return FileResponse(wf.documents_dir(resp) / doc.file, filename=f"{resp.ref_no}-{doc.name}.pdf",
                        media_type="application/pdf", headers={"Cache-Control": "no-store"})


# --- Prozesseditor --------------------------------------------------------------------------

def _process(db: Session, process_id: int) -> Process:
    process = db.get(Process, process_id)
    if process is None:
        raise HTTPException(404, "Prozess nicht gefunden.")
    return process


@app.get("/processes")
def processes_page(request: Request, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    processes = db.scalars(select(Process).order_by(Process.name)).all()
    return render(request, "processes.html", user, processes=processes, usage={p.id: wf.usage(db, p) for p in processes},
                  steps={p.id: wf.definition_of(p)["steps"] for p in processes}, templates=wf.TEMPLATES,
                  types=wf.STEP_TYPES, request_templates=wf.request_templates(db),
                  fl_types={k: fm.TYPES[k][:2] for k in wf.REQUEST_TYPES}, fl_subtypes=fm.SUBTYPES,
                  fl_order={"types": list(wf.REQUEST_TYPES), "subtypes": list(fm.SUBTYPES)})


@app.post("/processes/new", dependencies=[Depends(check_csrf)])
async def processes_new(request: Request, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    template = wf.TEMPLATES.get(str(data.get("template", "")))
    name = " ".join(str(data.get("name", "")).split())[:200] or (template[0] if template else "Neuer Prozess")
    definition = wf.clean_definition(template[2] if template else {"steps": []})
    process = Process(name=name, description=template[1] if template else "", owner_id=user.id,
                      draft_json=json.dumps(definition, ensure_ascii=False))
    db.add(process)
    db.commit()
    return redirect(f"/processes/{process.id}")


@app.post("/processes/import", dependencies=[Depends(check_csrf)])
async def processes_import(request: Request, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    upload = data.get("file")
    try:
        raw = json.loads((await upload.read(2 * 1024 * 1024)).decode("utf-8")) if upload is not None and hasattr(upload, "read") else None
    except (ValueError, UnicodeDecodeError):
        raw = None
    if not isinstance(raw, dict) or not isinstance(raw.get("definition"), dict):
        flash(request, "Die Datei ist kein exportierter Prozess.", "error")
        return redirect("/processes")
    process = wf.import_process(db, raw, user)
    db.commit()
    flash(request, "Prozess importiert. Bitte Zuständigkeiten prüfen und dann veröffentlichen.")
    return redirect(f"/processes/{process.id}")


@app.get("/processes/{process_id:int}")
def process_editor(request: Request, process_id: int, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    process = _process(db, process_id)
    definition = wf.definition_of(process)
    use = wf.usage(db, process)
    editor = {
        "definition": definition, "types": wf.STEP_TYPES, "assignModes": wf.ASSIGN_MODES, "ops": wf.OPS,
        "fieldTypes": wf.FIELD_TYPES, "actionTypes": wf.ACTION_TYPES, "mailTargets": wf.MAIL_TARGETS,
        "expireActions": wf.EXPIRE_ACTIONS,
        "statuses": {k: v[0] for k, v in apps.STATUSES.items()}, "closed": sorted(apps.CLOSED - {"withdrawn"}),
        "users": [{"id": u.id, "name": u.name} for u in _users(db)],
        "groups": [{"id": g.id, "name": g.name} for g in _groups(db)],
        "questions": wf.question_titles(db, process),
        "requestTypes": {k: fm.TYPES[k][:2] for k in wf.REQUEST_TYPES},
        "subtypes": fm.SUBTYPES,
        "templates": [{"id": t.id, "name": t.name, "message": t.message, "items": json.loads(t.schema_json or "[]"),
                       "due_days": t.due_days} for t in wf.request_templates(db)],
        # tojson sortiert Schlüssel – die gewünschte Reihenfolge der Auswahllisten separat mitgeben
        "order": {"types": list(wf.STEP_TYPES), "assignModes": list(wf.ASSIGN_MODES), "ops": list(wf.OPS),
                  "fieldTypes": list(wf.FIELD_TYPES), "actionTypes": list(wf.ACTION_TYPES),
                  "mailTargets": list(wf.MAIL_TARGETS), "statuses": list(apps.STATUSES), "expireActions": list(wf.EXPIRE_ACTIONS),
                  "requestTypes": list(wf.REQUEST_TYPES), "subtypes": list(fm.SUBTYPES)},
    }
    dms_areas = []
    if "dms" in enabled_modules():
        from . import dms
        by_id = {a.id: a for a in dms.areas(db)}
        dms_areas = [(a, d, dms.label(a, by_id)) for a, d in dms.tree(db)]
    return render(request, "process_editor.html", user, process=process, editor=editor, usage=use,
                  hints=wf.check(definition, db), dms_areas=dms_areas)


@app.post("/processes/{process_id:int}/filing", dependencies=[Depends(check_csrf)])
async def process_filing(request: Request, process_id: int, user: User = Depends(process_user),
                         db: Session = Depends(get_db)):
    from . import dms
    from .db import DmsArea, DmsRecord
    _module_on()
    process = _process(db, process_id)
    data = await request.form()
    aid = str(data.get("dms_area_id", ""))
    process.dms_area_id = int(aid) if aid.isdigit() and db.get(DmsArea, int(aid)) else None
    db.flush()
    # laufende und abgeschlossene Vorgänge dieses Prozesses gleich umsortieren (außer von Hand verschobene)
    n = 0
    for resp in wf.responses_of(db, process):
        before = db.scalar(select(DmsRecord.area_id).where(DmsRecord.response_id == resp.id))
        record = dms.sync(db, resp)
        n += bool(record is not None and record.area_id != before)
    db.commit()
    flash(request, "Ablage gespeichert." + (f" {n} Vorgang/Vorgänge einsortiert." if n else ""))
    return redirect(f"/processes/{process.id}#ablage")


@app.post("/processes/{process_id:int}/save", dependencies=[Depends(check_csrf)])
async def process_save(request: Request, process_id: int, user: User = Depends(process_user),
                       db: Session = Depends(get_db)):
    _module_on()
    process = _process(db, process_id)
    data = await request.form()
    try:
        definition = wf.clean_definition(json.loads(str(data.get("definition", "{}"))))
    except ValueError:
        return JSONResponse({"ok": False, "error": "Ungültige Daten."}, status_code=400)
    name = " ".join(str(data.get("name", "")).split())[:200]
    if name:
        process.name = name
    process.description = str(data.get("description", "")).replace("\r\n", "\n").strip()[:5000]
    process.draft_json = json.dumps(definition, ensure_ascii=False)
    published = wf.version_definition(process.current) if process.current else None
    process.draft_changed = published != definition
    db.commit()
    return JSONResponse({"ok": True, "definition": definition, "hints": wf.check(definition, db),
                         "changed": process.draft_changed})


@app.post("/processes/{process_id:int}/publish", dependencies=[Depends(check_csrf)])
async def process_publish(request: Request, process_id: int, user: User = Depends(process_user),
                          db: Session = Depends(get_db)):
    _module_on()
    process = _process(db, process_id)
    data = await request.form()
    definition = wf.definition_of(process)
    if not definition["steps"]:
        flash(request, "Ein Prozess ohne Schritte kann nicht veröffentlicht werden.", "error")
        return redirect(f"/processes/{process.id}")
    version = wf.publish(db, process, user, str(data.get("note", "")))
    db.commit()
    flash(request, f"Version {version.version} veröffentlicht. Neue Anträge laufen ab jetzt nach dieser Version; "
                   "laufende Vorgänge bleiben auf ihrer bisherigen Version.")
    return redirect(f"/processes/{process.id}")


@app.post("/processes/{process_id:int}/restore/{version_id:int}", dependencies=[Depends(check_csrf)])
def process_restore(request: Request, process_id: int, version_id: int, user: User = Depends(process_user),
                    db: Session = Depends(get_db)):
    _module_on()
    process = _process(db, process_id)
    version = next((v for v in process.versions if v.id == version_id), None)
    if version is None:
        raise HTTPException(404)
    process.draft_json = version.definition_json
    process.draft_changed = True
    db.commit()
    flash(request, f"Version {version.version} in den Entwurf geladen. Zum Übernehmen bitte erneut veröffentlichen.")
    return redirect(f"/processes/{process.id}")


@app.post("/processes/{process_id:int}/duplicate", dependencies=[Depends(check_csrf)])
def process_duplicate(request: Request, process_id: int, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    process = _process(db, process_id)
    clone = Process(name=(process.name + " (Kopie)")[:200], description=process.description, owner_id=user.id,
                    draft_json=process.draft_json)
    db.add(clone)
    db.commit()
    flash(request, "Prozess kopiert.")
    return redirect(f"/processes/{clone.id}")


@app.post("/processes/{process_id:int}/delete", dependencies=[Depends(check_csrf)])
def process_delete(request: Request, process_id: int, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    process = _process(db, process_id)
    use = wf.usage(db, process)
    if use["running"]:
        flash(request, f"Der Prozess steuert noch {use['running']} laufende Vorgänge und kann erst danach gelöscht werden.", "error")
        return redirect(f"/processes/{process.id}")
    for form in use["forms"]:
        form.process_id = None
    db.delete(process)
    db.commit()
    flash(request, "Prozess gelöscht." + (f" {len(use['forms'])} Antragsformular(e) arbeiten jetzt ohne Prozess." if use["forms"] else ""))
    return redirect("/processes")


@app.get("/processes/{process_id:int}/export.json")
def process_export(process_id: int, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    process = _process(db, process_id)
    slug = re.sub(r"[^a-z0-9]+", "-", process.name.lower()).strip("-")[:40] or "prozess"
    body = json.dumps(wf.export_data(process), ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{slug}.json"'})


# --- Vorlagen für Nachforderungen ---------------------------------------------------------

@app.post("/processes/templates", dependencies=[Depends(check_csrf)])
async def request_template_save(request: Request, user: User = Depends(process_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    action = data.get("action")
    tpl_id = str(data.get("id", ""))
    tpl = db.get(RequestTemplate, int(tpl_id)) if tpl_id.isdigit() else None
    if action == "delete" and tpl:
        db.delete(tpl)
        flash(request, "Vorlage gelöscht.")
    elif action == "save":
        try:
            items = wf.clean_request_items(json.loads(str(data.get("items_json", "[]"))))
        except ValueError:
            items = []
        name = " ".join(str(data.get("name", "")).split())[:200]
        if not name or not items:
            flash(request, "Bitte einen Namen und mindestens ein Feld angeben.", "error")
            return redirect("/processes#vorlagen")
        tpl = tpl or RequestTemplate(name=name)
        tpl.name, tpl.message = name, str(data.get("message", "")).replace("\r\n", "\n").strip()[:10000]
        tpl.schema_json = json.dumps(items, ensure_ascii=False)
        try:
            tpl.due_days = max(1, min(365, int(data.get("due_days", 14) or 14)))
        except ValueError:
            tpl.due_days = 14
        db.add(tpl)
        flash(request, "Vorlage gespeichert.")
    db.commit()
    return redirect("/processes#vorlagen")
