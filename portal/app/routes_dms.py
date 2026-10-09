"""Ablage (DMS): Recherche, Eintrag, manuelle Ablage, Aktenplan mit Rechten, Löschfristen."""

import io
import re
from datetime import datetime
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from . import dms_lifecycle as lifecycle, trash, csvsafe, applications as apps, dms, forms as fm
from .db import (
    LOCAL_TZ, DmsAccess, DmsArea, DmsLog, DmsRecord, DmsSearch, Group, Person, User, utcnow,
)
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, redirect, render, safe_next
from .routes_forms import SAFE_MIME

MAX_UPLOAD = 50 * 1024 * 1024


def _module_on() -> None:
    if "dms" not in enabled_modules():
        raise HTTPException(404, "Die Ablage ist auf diesem Server nicht eingeschaltet.")


def _user(db: Session, user: User) -> dict[int, int]:
    _module_on()
    lv = dms.levels(db, user)
    if not lv and not user.is_admin and not user.can("dms_admin"):
        raise HTTPException(403, "Sie haben keinen Zugriff auf die Ablage. Bitte wenden Sie sich an die Verwaltung des Aktenplans.")
    return lv


def _manager(user: User) -> None:
    _module_on()
    if not (user.is_admin or user.can("dms_admin")):
        raise HTTPException(403, "Für den Aktenplan fehlt die Berechtigung „Aktenplan verwalten“.")


def _filters(request: Request) -> dict:
    return {k: request.query_params.get(k, "").strip()[:200] for k in dms.FILTERS}


# --- Recherche ---------------------------------------------------------------------------

@app.get("/dms")
def dms_search(request: Request, page: int = 1, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = _user(db, user)
    f = _filters(request)
    visible = {a.id: a for a in dms.areas(db) if a.id in lv}
    selected = visible.get(int(f['area'])) if f['area'].isdigit() else None
    if f['area'] and selected is None:
        raise HTTPException(404, "Dieser Ordner ist nicht zugänglich.")
    filtering = any(f[k] for k in dms.FILTERS if k not in {'area', 'sort', 'scope'})
    f['scope'] = 'all' if filtering or f['scope'] == 'all' else 'folder'
    folder_ids = [a.id for a in visible.values() if a.parent_id not in visible]
    children = [a for a in visible.values() if a.parent_id == selected.id] if selected else [visible[i] for i in folder_ids]
    children.sort(key=lambda a: (a.position, a.code, a.name.casefold()))
    def folder_url(a=None):
        return '/dms?' + urlencode({**({'area': a.id} if a else {}), **({'state':'archive'} if f.get('state') == 'archive' else {})})
    page = max(1, min(page, 1000))
    records, total = dms.search(db, user, f, limit=50, offset=(page - 1) * 50, root_ids=folder_ids)
    tree = [(a, d) for a, d in dms.tree(db) if user.is_admin or a.id in lv]
    by_id = {a.id: a for a in dms.areas(db) if a.id in lv}
    forms_titles = sorted({t for (t,) in db.execute(select(DmsRecord.form_title).where(DmsRecord.area_id.in_(list(lv))).distinct()) if t})
    active = {k: v for k, v in f.items() if v and k not in {"sort", "scope"}}
    qs = urlencode({k: v for k, v in f.items() if v})
    return render(request, "dms.html", user, records=records, total=total, page=page, pages=(total + 49) // 50, f=f,
                  active=active, qs=qs, tree=tree, by_id=by_id, label=dms.label, levels=lv, form_titles=forms_titles,
                  statuses=apps.STATUSES, searches=db.scalars(select(DmsSearch).where(DmsSearch.user_id == user.id)
                                                              .order_by(DmsSearch.name)).all(),
                  can_write=any(v >= dms.WRITE for v in lv.values()), manager=user.is_admin or user.can("dms_admin"),
                  write_areas=[(a, d) for a, d in dms.tree(db) if lv.get(a.id, 0) >= dms.WRITE],
                  person_name=_person_name(db, user, f.get("person", "")), selected_folder=selected,
                  may_delete_folder=bool(selected and lv.get(selected.id,0)>=dms.WRITE and not lifecycle.area_protection(db,selected)),
                  folders=children, folder_url=folder_url, breadcrumbs=dms.path(selected, visible),
                  folder_tree=dms.folder_tree(list(visible.values())), filtering=filtering, ancestor_ids=[a.id for a in dms.path(selected, visible)])


def _person_name(db, user: User, pid: str) -> str:
    if not pid.isdigit():
        return ""
    person = db.scalar(dms.visible_persons_query(db, user).where(Person.id == int(pid)))
    return (person.name or person.email) if person else pid


@app.get("/dms/export.csv")
def dms_export(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = _user(db, user)
    f = _filters(request)
    visible = [a for a in dms.areas(db) if a.id in lv]
    root_ids = [a.id for a in visible if a.parent_id not in lv]
    records, _total = dms.search(db, user, f, limit=10000, root_ids=root_ids)
    by_id = {a.id: a for a in dms.areas(db) if a.id in lv}
    buf = io.StringIO()
    w = csvsafe.writer(buf, delimiter=";")
    w.writerow(["Aktenzeichen", "Titel", "Art", "Antragsteller:in", "E-Mail", "Straße", "PLZ", "Ort", "Ortsteil", "Eingang",
                "Status", "Abschluss", "Bereich", "Aufbewahren bis"])
    for r in records:
        w.writerow([r.ref_no, r.title, r.kind, r.applicant, r.applicant_email, r.street, r.zip, r.city, r.district,
                    r.received_at.strftime("%d.%m.%Y"), apps.status_label(r.status) if r.kind == "antrag" else "abgelegt",
                    r.closed_at.strftime("%d.%m.%Y") if r.closed_at else "", dms.label(r.area, by_id),
                    r.retention_until.strftime("%d.%m.%Y") if r.retention_until else ""])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="ablage-recherche.csv"'})


@app.post("/dms/searches", dependencies=[Depends(check_csrf)])
async def dms_search_save(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _user(db, user)
    data = await request.form()
    name = " ".join(str(data.get("name", "")).split())[:120]
    query = str(data.get("query", ""))[:2000]
    if name and query:
        db.add(DmsSearch(user_id=user.id, name=name, query=query))
        db.commit()
        flash(request, f"Suche „{name}“ gespeichert.")
    return redirect("/dms?" + query)


@app.post("/dms/searches/{sid:int}/delete", dependencies=[Depends(check_csrf)])
def dms_search_delete(request: Request, sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _user(db, user)
    s = db.get(DmsSearch, sid)
    if s and s.user_id == user.id:
        db.delete(s)
        db.commit()
    return redirect("/dms")


# --- Eintrag -----------------------------------------------------------------------------------

def _record(db: Session, user: User, record_id: int, need: int = dms.READ, *, allow_archived: bool = False) -> tuple[DmsRecord, int]:
    _user(db, user)
    record = db.get(DmsRecord, record_id)
    level = dms.record_level(db, user, record) if record else 0
    if record is None or level == 0:
        raise HTTPException(404, "Eintrag nicht gefunden.")
    if level < need:
        raise HTTPException(403, "Für diesen Bereich haben Sie nur Leserechte.")
    if need >= dms.WRITE and record.archived_at and not allow_archived:
        raise HTTPException(409, "Archivierter Eintrag: zuerst wieder aktivieren, um Änderungen vorzunehmen.")
    return record, level


@app.get("/dms/r/{record_id:int}")
def dms_record(request: Request, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import workflow
    record, level = _record(db, user, record_id)
    resp = record.response
    ctx = {}
    if resp is not None:
        items = fm.schema(resp.form)
        ctx = {"resp": resp, "questions": fm.questions(items), "current": workflow.current_answers(resp),
               "display": fm.display, "case_access": apps.access(db, user, resp) > 0,
               "field_labels": {f["key"]: f["label"] for s in workflow.steps_of(resp) for f in s.get("fields", [])}}
    lv = dms.levels(db, user)
    by_id = {a.id: a for a in dms.areas(db) if a.id in lv}
    person_q = request.query_params.get("person_q", "").strip()[:100]
    candidates = []
    if person_q and level >= dms.WRITE:
        q = dms.visible_persons_query(db, user)
        for word in person_q.split()[:5]:
            like = f"%{word}%"
            q = q.where(or_(Person.name.ilike(like), Person.email.ilike(like), Person.city.ilike(like), Person.zip.ilike(like)))
        candidates = db.scalars(q.order_by(Person.name).limit(15)).all()
    ctx.update(person_q=person_q, candidates=candidates)
    return render(request, "dms_record.html", user, record=record, level=level, by_id=by_id, label=dms.label,
                  may_remove=lifecycle.owns(user, record), protection=lifecycle.protection(db, record),
                  area_path=dms.path(record.area, by_id), statuses=apps.STATUSES, write_areas=[(a, d) for a, d in dms.tree(db) if lv.get(a.id, 0) >= dms.WRITE],
                  **ctx)


def _send(path, name: str, mime: str, preview: bool = False):
    safe = mime in SAFE_MIME or (mime.startswith("image/") and mime != "image/svg+xml")
    inline = preview and mime in {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"}
    return FileResponse(path, filename=name, media_type=mime if safe else "application/octet-stream",
                        content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'; sandbox",
                                 "X-Frame-Options": "SAMEORIGIN" if inline else "DENY", "X-Content-Type-Options": "nosniff"})


@app.get("/dms/r/{record_id:int}/files/{file_id:int}")
def dms_file(record_id: int, file_id: int, preview: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id)
    f = next((x for x in record.files if x.id == file_id), None)
    path = dms.files_dir(record.id) / f.file if f else None
    if f is None or not path.is_file():
        raise HTTPException(404, "Datei nicht gefunden.")
    return _send(path, f.name, f.mime, preview)


@app.get("/dms/r/{record_id:int}/case/{src}/{name}")
def dms_case_file(record_id: int, src: str, name: str, preview: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Uploads aus dem Antrag (src=a) oder aus einer Nachforderung (src=req<nr>) – mit Leserecht der Ablage."""
    record, _ = _record(db, user, record_id)
    resp = record.response
    if resp is None or not re.fullmatch(r"a|req\d+", src) or not re.fullmatch(r"[0-9a-f]{16}(\.[a-z0-9]{1,10})?", name):
        raise HTTPException(404)
    if src == "a":
        values, path = resp.answers.values(), fm.files_dir(resp.form_id, resp.id) / name
    else:
        req = next((r for r in resp.requests if f"req{r.id}" == src), None)
        if req is None:
            raise HTTPException(404)
        values, path = req.answers.values(), fm.files_dir(resp.form_id, resp.id) / src / name
    entry = next((f for v in values if isinstance(v, list) for f in v if isinstance(f, dict) and f.get("file") == name), None)
    if entry is None or not path.is_file():
        raise HTTPException(404, "Datei nicht gefunden.")
    return _send(path, entry.get("name") or name, entry.get("type") or "", preview)


@app.get("/dms/r/{record_id:int}/document/{doc_id:int}")
def dms_case_document(record_id: int, doc_id: int, preview: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import workflow
    record, _ = _record(db, user, record_id)
    resp = record.response
    doc = next((d for d in resp.documents if d.id == doc_id), None) if resp else None
    if doc is None or not (workflow.documents_dir(resp) / doc.file).is_file():
        raise HTTPException(404)
    return _send(workflow.documents_dir(resp) / doc.file, f"{resp.ref_no}-{doc.name}.pdf", "application/pdf", preview)


@app.get("/dms/r/{record_id:int}/pdf")
def dms_record_pdf(record_id: int, preview: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id)
    if record.response is None:
        raise HTTPException(404)
    return Response(apps.pdf(record.response.form, record.response), media_type="application/pdf",
                    headers={"Content-Disposition": f'{"inline" if preview else "attachment"}; filename="{record.ref_no or record.id}.pdf"', "Cache-Control": "private, no-store", "X-Frame-Options": "SAMEORIGIN" if preview else "DENY", "X-Content-Type-Options": "nosniff"})


@app.post("/dms/r/{record_id:int}/upload", dependencies=[Depends(check_csrf)])
async def dms_upload(request: Request, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id, dms.WRITE)
    data = await request.form()
    note = str(data.get("note", "")).strip()[:500]
    n = 0
    for f in data.getlist("files"):
        if not hasattr(f, "filename") or not f.filename:
            continue
        content = await f.read(MAX_UPLOAD + 1)
        if len(content) > MAX_UPLOAD:
            flash(request, f"„{f.filename}“ ist größer als 50 MB und wurde nicht abgelegt.", "error")
            continue
        stored = dms._store(record, f.filename.replace("/", "_").replace("\\", "_"), content, "upload", user.name, note, f.content_type or "")
        stored.uploaded_by_id = user.id
        n += 1
    if n:
        record.text = (record.text + " " + " ".join(x.name.lower() for x in record.files) + " " + note.lower())[:200000]
        record.updated_at = utcnow()
        dms.log(db, user, "abgelegt", f"{n} Datei(en) zu {record.ref_no or record.title}")
        db.commit()
        flash(request, f"{n} Datei(en) abgelegt.")
    return redirect(f"/dms/r/{record.id}#dateien")


@app.post("/dms/r/{record_id:int}/files/{file_id:int}/delete", dependencies=[Depends(check_csrf)])
def dms_file_delete(request: Request, record_id: int, file_id: int, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id, dms.WRITE)
    f = next((x for x in record.files if x.id == file_id), None)
    if f is None or f.kind != "upload":
        raise HTTPException(400, "Abschlussstände und erzeugte Dokumente lassen sich nicht einzeln löschen.")
    if not (user.is_admin or f.uploaded_by_id == user.id):
        raise HTTPException(403, "Nur Uploader oder Admin dürfen die Datei löschen.")
    reasons = lifecycle.file_protection(db, f)
    if reasons: raise HTTPException(409, "; ".join(reasons))
    trash.delete_obj(db, "dms_file", f, user.name)
    dms.log(db, user, "Datei gelöscht", f"{f.name} aus {record.ref_no or record.title}")
    db.commit()
    flash(request, "Datei gelöscht.")
    return redirect(f"/dms/r/{record.id}#dateien")


def _parse_day(value: str):
    try:
        return datetime.fromisoformat(value).replace(hour=12)
    except ValueError:
        return None


@app.post("/dms/r/{record_id:int}/edit", dependencies=[Depends(check_csrf)])
async def dms_record_edit(request: Request, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id, dms.WRITE)
    data = await request.form()
    lv = dms.levels(db, user)
    target = str(data.get("area_id", ""))
    if target.isdigit() and int(target) != record.area_id:
        if lv.get(int(target), 0) < dms.WRITE:
            raise HTTPException(403, "In diesem Bereich dürfen Sie nicht ablegen.")
        dms.move_record(db, record, db.get(DmsArea, int(target)), user)
    record.note = str(data.get("note", "")).replace("\r\n", "\n").strip()[:10000]
    if record.kind == "manuell":
        record.title = " ".join(str(data.get("title", "")).split())[:300] or record.title
        record.applicant = " ".join(str(data.get("applicant", "")).split())[:255]
        record.applicant_email = str(data.get("applicant_email", "")).strip()[:255]
        for key in ("street", "zip", "city", "district"):
            setattr(record, key, " ".join(str(data.get(key, "")).split())[:200])
        day = _parse_day(str(data.get("received", "")))
        if day:
            record.received_at = day
    keep = _parse_day(str(data.get("retention_until", "")))
    if data.get("retention_until") is not None:
        record.retention_until = keep
        if record.kind == "manuell" or record.closed_at:
            dms.log(db, user, "Frist geändert", f"{record.ref_no or record.title}: aufbewahren bis {keep.strftime('%d.%m.%Y') if keep else 'unbegrenzt'}")
    record.text = " ".join([record.text, record.note.lower(), record.title.lower(), record.applicant.lower()])[:200000]
    record.updated_at = utcnow()
    db.commit()
    flash(request, "Eintrag gespeichert.")
    return redirect(f"/dms/r/{record.id}")


@app.get("/dms/new")
def dms_new(request: Request, area: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = _user(db, user)
    write = [(a, d) for a, d in dms.tree(db) if lv.get(a.id, 0) >= dms.WRITE]
    if not write:
        if user.can("dms_admin"):
            flash(request, "Legen Sie zuerst im Aktenplan einen Bereich an.", "error")
            return redirect("/dms/areas")
        flash(request, "Sie haben in keinem Ablagebereich Schreibrechte.", "error")
        return redirect("/dms")
    person = None
    pid = request.query_params.get("person", "")
    if pid.isdigit():
        person = db.scalar(dms.visible_persons_query(db, user).where(Person.id == int(pid)))
    return render(request, "dms_new.html", user, write_areas=write, selected=area, person=person,
                  today=datetime.now(LOCAL_TZ).date().isoformat())


@app.post("/dms/new", dependencies=[Depends(check_csrf)])
async def dms_new_save(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = _user(db, user)
    data = await request.form()
    area_id = int(data["area_id"]) if str(data.get("area_id", "")).isdigit() else 0
    if lv.get(area_id, 0) < dms.WRITE:
        raise HTTPException(403, "In diesem Bereich dürfen Sie nicht ablegen.")
    title = " ".join(str(data.get("title", "")).split())[:300]
    if not title:
        flash(request, "Bitte einen Titel angeben.", "error")
        return redirect("/dms/new")
    record = DmsRecord(area_id=area_id, kind="manuell", title=title, ref_no=" ".join(str(data.get("ref_no", "")).split())[:60],
                       applicant=" ".join(str(data.get("applicant", "")).split())[:255],
                       applicant_email=str(data.get("applicant_email", "")).strip()[:255],
                       owner_id=user.id, note=str(data.get("note", "")).replace("\r\n", "\n").strip()[:10000], created_by=user.name,
                       received_at=_parse_day(str(data.get("received", ""))) or utcnow(), closed_at=utcnow())
    for key in ("street", "zip", "city", "district"):
        setattr(record, key, " ".join(str(data.get(f"n__{key}", "")).split())[:200])
    if data.get("n__house_no"):
        record.street = f"{record.street} {data.get('n__house_no')}".strip()[:200]
    for key in ("lat", "lon"):
        try:
            setattr(record, key, round(float(str(data.get(f"n__{key}", "")).replace(",", ".")), 6))
        except ValueError:
            pass
    db.add(record)
    db.flush()
    n = 0
    for f in data.getlist("files"):
        if hasattr(f, "filename") and f.filename:
            content = await f.read(MAX_UPLOAD + 1)
            if len(content) <= MAX_UPLOAD:
                stored = dms._store(record, f.filename.replace("/", "_").replace("\\", "_"), content, "upload", user.name, "", f.content_type or "")
                stored.uploaded_by_id = user.id
                n += 1
    by_id = {a.id: a for a in dms.areas(db) if a.id in lv}
    record.retention_until = dms.retention_date(record.closed_at, dms.retention_years(by_id[area_id], by_id))
    record.text = " ".join([title, record.ref_no, record.applicant, record.applicant_email, record.street, record.zip,
                            record.city, record.district, record.note, *[x.name for x in record.files]]).lower()
    pid = str(data.get("person_id", ""))
    chosen = db.get(Person, int(pid)) if pid.isdigit() else None
    if chosen is not None and db.scalar(dms.visible_persons_query(db, user).where(Person.id == chosen.id)) is not None:
        record.person = chosen
    else:
        record.person = dms.match_person(db, record.applicant, record.applicant_email, record.street, record.zip, record.city)
    dms.log(db, user, "abgelegt", f"„{title}“ mit {n} Datei(en) in {by_id[area_id].name}")
    db.commit()
    flash(request, "Vorgang abgelegt.")
    return redirect(f"/dms/r/{record.id}")


# --- Aktenplan ----------------------------------------------------------------------------------

@app.get("/dms/areas")
def dms_areas(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    dms.unsorted(db)
    db.commit()
    tree = dms.tree(db)
    counts = {a.id: 0 for a, _ in tree}
    for (aid,) in db.execute(select(DmsRecord.area_id)):
        counts[aid] = counts.get(aid, 0) + 1
    by_id = {a.id: a for a, _ in tree}
    return render(request, "dms_areas.html", user, tree=tree, counts=counts, by_id=by_id, label=dms.label, folder_tree=dms.folder_tree(list(by_id.values())),
                  users=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all(),
                  groups=db.scalars(select(Group).order_by(Group.name)).all(), levels=dms.LEVELS,
                  inherited={a.id: dms.retention_years(a, by_id) for a, _ in tree})


@app.post("/dms/areas/save", dependencies=[Depends(check_csrf)])
async def dms_area_save(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    data = await request.form()
    aid = str(data.get("id", ""))
    area = db.get(DmsArea, int(aid)) if aid.isdigit() else None
    name = " ".join(str(data.get("name", "")).split())[:200]
    if not name:
        flash(request, "Bitte einen Namen angeben.", "error")
        return redirect("/dms/areas")
    parent = str(data.get("parent_id", ""))
    parent_id = int(parent) if parent.isdigit() and db.get(DmsArea, int(parent)) else None
    if area is not None and parent_id and parent_id in dms.subtree_ids(db, area.id):
        flash(request, "Ein Bereich kann nicht unter sich selbst eingeordnet werden.", "error")
        return redirect("/dms/areas")
    if area is None:
        area = DmsArea(name=name)
        db.add(area)
    area.name, area.parent_id = name, parent_id
    area.code = " ".join(str(data.get("code", "")).split())[:40]
    area.description = str(data.get("description", "")).strip()[:2000]
    try:
        area.retention_years = max(0, min(100, int(data.get("retention_years") or 0)))
    except ValueError:
        area.retention_years = 0
    db.flush()
    # Fristen der vorhandenen abgeschlossenen Einträge neu berechnen
    by_id = {a.id: a for a in dms.areas(db)}
    for record in db.scalars(select(DmsRecord).where(DmsRecord.area_id.in_(dms.subtree_ids(db, area.id)))):
        if record.closed_at:
            record.retention_until = dms.retention_date(record.closed_at, dms.retention_years(by_id[record.area_id], by_id))
    db.commit()
    flash(request, f"Bereich „{area.name}“ gespeichert.")
    return redirect(f"/dms/areas#bereich-{area.id}")


@app.post("/dms/areas/{area_id:int}/delete", dependencies=[Depends(check_csrf)])
def dms_area_delete(request: Request, area_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = _user(db, user)
    area = db.get(DmsArea, area_id)
    if area is not None and lv.get(area.id, 0) < dms.WRITE: raise HTTPException(403)
    if area is None:
        raise HTTPException(404)
    if area.system_key:
        flash(request, "„Nicht einsortiert“ ist fest eingerichtet und lässt sich nicht löschen.", "error")
        return redirect("/dms/areas" if user.is_admin or user.can("dms_admin") else "/dms")
    if db.scalar(select(DmsRecord.id).where(DmsRecord.area_id == area_id).limit(1)) or \
            db.scalar(select(DmsArea.id).where(DmsArea.parent_id == area_id).limit(1)):
        flash(request, "Der Bereich enthält noch Einträge oder Unterbereiche.", "error")
        return redirect("/dms/areas" if user.is_admin or user.can("dms_admin") else "/dms")
    reasons = lifecycle.area_protection(db, area)
    if reasons: raise HTTPException(409, '; '.join(reasons))
    from .db import Form
    if db.scalar(select(Form.id).where(Form.dms_area_id == area_id).limit(1)):
        raise HTTPException(409, "Ordner wird von einem Formular verwendet.")
    trash.delete_obj(db, "dms_area", area, user.name)
    db.commit()
    flash(request, "Bereich gelöscht.")
    return redirect("/dms/areas" if user.is_admin or user.can("dms_admin") else "/dms")


@app.post("/dms/areas/{area_id:int}/access", dependencies=[Depends(check_csrf)])
async def dms_access_add(request: Request, area_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    area = db.get(DmsArea, area_id)
    if area is None:
        raise HTTPException(404)
    data = await request.form()
    level = dms.WRITE if data.get("level") == "2" else dms.READ
    added = 0
    for raw in data.getlist("who"):
        kind, _, ident = str(raw).partition(":")
        if not ident.isdigit() or kind not in ("u", "g"):
            continue
        uid, gid = (int(ident), None) if kind == "u" else (None, int(ident))
        existing = next((a for a in area.access if a.user_id == uid and a.group_id == gid), None)
        if existing:
            existing.level = level
        else:
            area.access.append(DmsAccess(user_id=uid, group_id=gid, level=level))
        added += 1
    db.commit()
    flash(request, f"{added} Berechtigung(en) für „{area.name}“ gespeichert.")
    return redirect(f"/dms/areas#bereich-{area.id}")


@app.post("/dms/access/{access_id:int}/delete", dependencies=[Depends(check_csrf)])
def dms_access_delete(request: Request, access_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    acc = db.get(DmsAccess, access_id)
    if acc is None:
        raise HTTPException(404)
    area_id = acc.area_id
    db.delete(acc)
    db.commit()
    return redirect(f"/dms/areas#bereich-{area_id}")


# --- Löschfristen -------------------------------------------------------------------------------

@app.get("/dms/retention")
def dms_retention(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    by_id = {a.id: a for a in dms.areas(db)}
    return render(request, "dms_retention.html", user, records=dms.expired(db), by_id=by_id, label=dms.label,
                  log=db.scalars(select(DmsLog).order_by(DmsLog.at.desc()).limit(200)).all())


@app.post("/dms/retention/delete", dependencies=[Depends(check_csrf)])
async def dms_retention_delete(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    data = await request.form()
    ids = {int(x) for x in data.getlist("ids") if str(x).isdigit()}
    n = 0
    for record in dms.expired(db):
        if record.id in ids:
            try:
                dms.delete_record(db, record, user, "Aufbewahrungsfrist abgelaufen")
                n += 1
            except ValueError as exc:
                flash(request, f"{record.title}: {exc}", "error")
    db.commit()
    flash(request, f"{n} Eintrag/Einträge nach Ablauf der Aufbewahrungsfrist gelöscht und protokolliert.")
    return redirect("/dms/retention")


# --- Verschieben (Sammelaktion) -------------------------------------------------------------------

@app.post("/dms/move", dependencies=[Depends(check_csrf)])
async def dms_move(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lv = _user(db, user)
    data = await request.form()
    target = db.get(DmsArea, int(data["area_id"])) if str(data.get("area_id", "")).isdigit() else None
    if target is None or lv.get(target.id, 0) < dms.WRITE:
        flash(request, "Bitte einen Zielbereich wählen, in dem Sie ablegen dürfen.", "error")
        return redirect(safe_next(str(data.get("next", ""))) if data.get("next") else "/dms")
    moved = skipped = 0
    for rid in data.getlist("ids"):
        record = db.get(DmsRecord, int(rid)) if str(rid).isdigit() else None
        if record is None or lv.get(record.area_id, 0) < dms.WRITE:
            skipped += 1
            continue
        moved += dms.move_record(db, record, target, user)
    db.commit()
    flash(request, f"{moved} Eintrag/Einträge nach „{target.name}“ verschoben."
          + (f" {skipped} übersprungen (keine Schreibrechte)." if skipped else ""), "error" if skipped and not moved else "ok")
    return redirect(safe_next(str(data.get("next", ""))) if data.get("next") else "/dms")


# --- Personen (Bürger:innen / Antragsteller:innen) ----------------------------------------------

def _person(db, user: User, person_id: int) -> Person:
    _user(db, user)
    person = db.scalar(dms.visible_persons_query(db, user).where(Person.id == person_id))
    if person is None:
        raise HTTPException(404, "Person nicht gefunden.")
    return person


def _person_write(db, user: User, person: Person) -> bool:
    """Ändern darf, wer den Aktenplan verwaltet oder in einem Bereich mit Einträgen der Person ablegen darf."""
    if user.is_admin or user.can("dms_admin"):
        return True
    lv = dms.levels(db, user)
    return any(lv.get(r.area_id, 0) >= dms.WRITE for r in db.scalars(select(DmsRecord).where(DmsRecord.person_id == person.id)))


@app.get("/dms/persons")
def dms_persons(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _user(db, user)
    term = request.query_params.get("q", "").strip()[:100]
    q = dms.visible_persons_query(db, user)
    for word in term.split()[:5]:
        like = f"%{word}%"
        q = q.where(or_(Person.name.ilike(like), Person.email.ilike(like), Person.city.ilike(like), Person.zip.ilike(like),
                        Person.street.ilike(like), Person.phone.ilike(like)))
    rows = db.scalars(q.order_by(Person.name).limit(300)).all()
    counts = dict(db.execute(select(DmsRecord.person_id, func.count(DmsRecord.id))
                             .where(DmsRecord.person_id.in_([p.id for p in rows] or [-1])).group_by(DmsRecord.person_id)).all())
    return render(request, "dms_persons.html", user, rows=rows, q=term, counts=counts)


@app.get("/dms/persons/{person_id:int}")
def dms_person(request: Request, person_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    person = _person(db, user, person_id)
    lv = dms.levels(db, user)
    records, total = dms.search(db, user, {"person": str(person.id)}, limit=500)
    by_id = {a.id: a for a in dms.areas(db) if a.id in lv}
    merge = []
    if user.is_admin or user.can("dms_admin"):
        like_name = " ".join(person.name.split()[-1:])
        cands = select(Person).where(Person.id != person.id)
        conds = [Person.email == person.email] if person.email else []
        if like_name:
            conds.append(Person.name.ilike(f"%{like_name}%"))
        merge = db.scalars(cands.where(or_(*conds)).order_by(Person.name).limit(20)).all() if conds else []
    return render(request, "dms_person.html", user, person=person, records=records, total=total, by_id=by_id,
                  label=dms.label, statuses=apps.STATUSES, can_edit=_person_write(db, user, person), merge=merge,
                  hidden=db.scalar(select(func.count(DmsRecord.id)).where(DmsRecord.person_id == person.id)) - total)


@app.post("/dms/persons/{person_id:int}", dependencies=[Depends(check_csrf)])
async def dms_person_save(request: Request, person_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    person = _person(db, user, person_id)
    if not _person_write(db, user, person):
        raise HTTPException(403, "Für diese Person haben Sie nur Leserechte.")
    data = await request.form()
    name = " ".join(str(data.get("name", "")).split())[:255]
    if not name:
        flash(request, "Bitte einen Namen angeben.", "error")
        return redirect(f"/dms/persons/{person.id}")
    person.name = name
    person.email = str(data.get("email", "")).strip().lower()[:255]
    for key, size in (("phone", 60), ("street", 255), ("zip", 10), ("city", 200)):
        setattr(person, key, " ".join(str(data.get(key, "")).split())[:size])
    person.note = str(data.get("note", "")).replace("\r\n", "\n").strip()[:5000]
    person.updated_at = utcnow()
    db.commit()
    flash(request, "Angaben zur Person gespeichert.")
    return redirect(f"/dms/persons/{person.id}")


@app.post("/dms/persons/{person_id:int}/merge", dependencies=[Depends(check_csrf)])
async def dms_person_merge(request: Request, person_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    keep = db.get(Person, person_id)
    data = await request.form()
    drop = db.get(Person, int(data["other_id"])) if str(data.get("other_id", "")).isdigit() else None
    if keep is None or drop is None or keep.id == drop.id:
        raise HTTPException(404)
    n = dms.merge_persons(db, keep, drop, user)
    db.commit()
    flash(request, f"„{drop.name}“ mit {n} Eintrag/Einträgen übernommen.")
    return redirect(f"/dms/persons/{keep.id}")


@app.post("/dms/r/{record_id:int}/person", dependencies=[Depends(check_csrf)])
async def dms_record_person(request: Request, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id, dms.WRITE)
    data = await request.form()
    pid = str(data.get("person_id", ""))
    if pid == "new":
        person = Person(name=record.applicant or "Unbekannt", email="", street=record.street, zip=record.zip[:10], city=record.city)
        db.add(person)
        db.flush()
    else:
        person = db.scalar(dms.visible_persons_query(db, user).where(Person.id == int(pid))) if pid.isdigit() else None
    if person is None:
        raise HTTPException(404, "Person nicht gefunden.")
    record.person = person
    dms.log(db, user, "Person zugeordnet", f"{record.ref_no or record.title} → #{person.id} {person.name}")
    db.commit()
    flash(request, f"Eintrag „{person.name}“ zugeordnet.")
    return redirect(f"/dms/r/{record.id}")

@app.post('/dms/r/{record_id:int}/archive', dependencies=[Depends(check_csrf)])
def dms_archive(request: Request, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id, dms.WRITE)
    if not lifecycle.owns(user, record): raise HTTPException(403, 'Nur Ersteller oder Admin dürfen archivieren.')
    record.archived_at = utcnow()
    record.updated_at = utcnow()
    db.commit()
    flash(request, 'Archiviert. Bestehende Verknüpfungen bleiben lesbar.')
    return redirect('/dms?state=archive')


@app.post('/dms/r/{record_id:int}/activate', dependencies=[Depends(check_csrf)])
def dms_activate(request: Request, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id, dms.WRITE, allow_archived=True)
    if not lifecycle.owns(user, record): raise HTTPException(403)
    record.archived_at = None
    record.updated_at = utcnow()
    db.commit()
    return redirect(f'/dms/r/{record.id}')


@app.post('/dms/r/{record_id:int}/delete', dependencies=[Depends(check_csrf)])
def dms_delete(request: Request, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id, dms.WRITE)
    try: dms.delete_record(db, record, user, 'Vom Ersteller entfernt')
    except ValueError as exc: raise HTTPException(409, str(exc))
    db.commit()
    flash(request, '30 Tage im Papierkorb wiederherstellbar.')
    return redirect('/dms/trash')


@app.get('/dms/areas/{area_id:int}/delete-preview')
def dms_area_preview(request: Request, area_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    if not user.is_admin: raise HTTPException(403, 'Rekursive Löschung ist Admins vorbehalten.')
    area = db.get(DmsArea, area_id)
    if not area: raise HTTPException(404)
    return render(request, 'dms_delete_preview.html', user, area=area, **lifecycle.folder_preview(db, area_id))


@app.post('/dms/areas/{area_id:int}/delete-recursive', dependencies=[Depends(check_csrf)])
async def dms_area_recursive(request: Request, area_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    if not user.is_admin: raise HTTPException(403)
    data = await request.form()
    # Acquire the SQLite writer lock before checking the preview and moving files.
    db.execute(update(DmsArea).where(DmsArea.id == area_id).values(position=DmsArea.position))
    preview = lifecycle.folder_preview(db, area_id)
    if not preview['areas']: raise HTTPException(404)
    if data.get('confirm') != 'LÖSCHEN' or data.get('fingerprint') != preview['fingerprint'] or str(data.get('count')) != str(preview['count']):
        raise HTTPException(409, 'Bestätigung fehlt oder Inhalte haben sich verändert. Vorschau erneut öffnen.')
    if preview['blocked']: raise HTTPException(409, 'Geschützte oder verknüpfte Inhalte verhindern die gesamte Löschung.')
    # Save all folders and records as one item, retaining their parent-before-child restore order.
    from .db import TrashItem
    from datetime import timedelta
    import json
    root = db.get(DmsArea, area_id)
    snapshot = trash.snapshot(db, DmsArea.__table__, DmsArea.id.in_([a.id for a in preview['areas']]))
    rows = snapshot['rows']
    area_rows = [r for r in rows if r['table'] == 'dms_areas']
    area_rows.sort(key=lambda row: len(dms.path(db.get(DmsArea, row['data']['id']), {a.id:a for a in dms.areas(db)})))
    rows[:] = area_rows + [r for r in rows if r['table'] != 'dms_areas']
    for record in preview['records']:
        part = trash.snapshot(db, DmsRecord.__table__, DmsRecord.id == record.id)
        rows.extend(part['rows']); snapshot['nulls'].extend(part['nulls'])
    item = TrashItem(kind='dms_area', label=root.name, table_name='dms_areas', row_id=root.id,
                     data_json=json.dumps(snapshot, ensure_ascii=False), deleted_by=user.name,
                     expires_at=utcnow()+timedelta(days=30))
    db.add(item); db.flush()
    item.files_json = json.dumps(trash._move_files([dms.files_dir(r.id) for r in preview['records']], item.id))
    for record in preview['records']:
        if record.response:
            record.response.dms_removed = True
        db.delete(record)
    db.flush()
    for row in reversed(area_rows): db.delete(db.get(DmsArea, row['data']['id'])); db.flush()
    trash.log(db, user.name, 'delete', 'dms_area', preview['count'], 'Rekursiv nach bestätigter Vorschau')
    db.commit()
    return redirect('/dms/trash')


@app.get('/dms/trash')
def dms_trash(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    import json
    from .db import TrashItem
    lv = _user(db, user)
    items = []
    for item in db.scalars(select(TrashItem).where(TrashItem.kind.in_(['dms','dms_file','dms_area']), TrashItem.expires_at > utcnow()).order_by(TrashItem.deleted_at.desc())):
        snapshot = json.loads(item.data_json)
        own = any(row['table'] == 'dms_records' and row['data'].get('owner_id') == user.id or
                  row['table'] == 'dms_files' and row['data'].get('uploaded_by_id') == user.id for row in snapshot['rows'])
        if user.is_admin or own: items.append(item)
    return render(request, 'dms_trash.html', user, items=items,
                  targets=[a for a in dms.areas(db) if lv.get(a.id,0) >= dms.WRITE])


@app.post('/dms/trash/{item_id:int}/restore', dependencies=[Depends(check_csrf)])
async def dms_restore(request: Request, item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    import json
    from .db import TrashItem
    lv = _user(db, user)
    item = db.get(TrashItem, item_id)
    if not item or item.kind not in {'dms','dms_file','dms_area'} or item.expires_at <= utcnow(): raise HTTPException(404)
    snapshot = json.loads(item.data_json)
    if not user.is_admin:
        if item.kind == 'dms_area': raise HTTPException(403)
        owners = [row['data'].get('owner_id') for row in snapshot['rows'] if row['table']=='dms_records'] if item.kind=='dms' else [row['data'].get('uploaded_by_id') for row in snapshot['rows'] if row['table']=='dms_files']
        if not owners or any(owner != user.id for owner in owners): raise HTTPException(403)
    data = await request.form()
    target = str(data.get('target_id',''))
    restored_area_ids = {row['data']['id'] for row in snapshot['rows'] if row['table'] == 'dms_areas'}
    for row in snapshot['rows']:
        if row['table'] == 'dms_areas':
            parent_id = row['data'].get('parent_id')
            if parent_id and parent_id not in restored_area_ids and not db.get(DmsArea, parent_id):
                if not target.isdigit() or not db.get(DmsArea, int(target)) or lv.get(int(target), 0) < dms.WRITE:
                    raise HTTPException(409, 'Der ursprüngliche übergeordnete Ordner fehlt. Bitte einen beschreibbaren Zielordner auswählen.')
                row['data']['parent_id'] = int(target)
        if row['table']=='dms_records':
            original = db.get(DmsArea,row['data']['area_id'])
            if not original and item.kind != 'dms_area':
                if not target.isdigit() or not db.get(DmsArea,int(target)) or lv.get(int(target),0)<dms.WRITE: raise HTTPException(409,'Bitte einen beschreibbaren Zielordner auswählen.')
                row['data']['area_id']=int(target)
            elif original and lv.get(original.id,0)<dms.WRITE: raise HTTPException(403,'Keine Schreibrechte im ursprünglichen Ordner.')
        if row['table']=='dms_files' and item.kind=='dms_file':
            record = db.get(DmsRecord,row['data']['record_id'])
            if not record or lv.get(record.area_id,0)<dms.WRITE: raise HTTPException(409,'Übergeordneten Eintrag zuerst wiederherstellen oder Schreibrechte anfordern.')
    item.data_json=json.dumps(snapshot,ensure_ascii=False)
    error=trash.restore(db,item,user.name)
    if error: raise HTTPException(409,error)
    db.commit()
    flash(request,'Wiederhergestellt. Es gelten die aktuellen Zugriffsrechte des Zielordners.')
    return redirect('/dms')
