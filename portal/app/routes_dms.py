"""Ablage (DMS): Recherche, Eintrag, manuelle Ablage, Aktenplan mit Rechten, Löschfristen."""

import csv
import io
import re
from datetime import datetime
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import applications as apps, dms, forms as fm
from .db import (
    LOCAL_TZ, DmsAccess, DmsArea, DmsLog, DmsRecord, DmsSearch, Group, User, utcnow,
)
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, redirect, render
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
    page = max(1, min(page, 1000))
    records, total = dms.search(db, user, f, limit=50, offset=(page - 1) * 50)
    tree = [(a, d) for a, d in dms.tree(db) if user.is_admin or a.id in lv]
    by_id = {a.id: a for a in dms.areas(db)}
    forms_titles = sorted({t for (t,) in db.execute(select(DmsRecord.form_title).distinct()) if t})
    active = {k: v for k, v in f.items() if v and k != "sort"}
    qs = urlencode({k: v for k, v in f.items() if v})
    return render(request, "dms.html", user, records=records, total=total, page=page, pages=(total + 49) // 50, f=f,
                  active=active, qs=qs, tree=tree, by_id=by_id, label=dms.label, levels=lv, form_titles=forms_titles,
                  statuses=apps.STATUSES, searches=db.scalars(select(DmsSearch).where(DmsSearch.user_id == user.id)
                                                              .order_by(DmsSearch.name)).all(),
                  can_write=any(v >= dms.WRITE for v in lv.values()), manager=user.is_admin or user.can("dms_admin"))


@app.get("/dms/export.csv")
def dms_export(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _user(db, user)
    records, _total = dms.search(db, user, _filters(request), limit=10000)
    by_id = {a.id: a for a in dms.areas(db)}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
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

def _record(db: Session, user: User, record_id: int, need: int = dms.READ) -> tuple[DmsRecord, int]:
    _user(db, user)
    record = db.get(DmsRecord, record_id)
    level = dms.record_level(db, user, record) if record else 0
    if record is None or level == 0:
        raise HTTPException(404, "Eintrag nicht gefunden.")
    if level < need:
        raise HTTPException(403, "Für diesen Bereich haben Sie nur Leserechte.")
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
    by_id = {a.id: a for a in dms.areas(db)}
    return render(request, "dms_record.html", user, record=record, level=level, by_id=by_id, label=dms.label,
                  statuses=apps.STATUSES, write_areas=[(a, d) for a, d in dms.tree(db) if lv.get(a.id, 0) >= dms.WRITE],
                  **ctx)


def _send(path, name: str, mime: str):
    safe = mime in SAFE_MIME or (mime.startswith("image/") and mime != "image/svg+xml")
    return FileResponse(path, filename=name, media_type=mime if safe else "application/octet-stream",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@app.get("/dms/r/{record_id:int}/files/{file_id:int}")
def dms_file(record_id: int, file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id)
    f = next((x for x in record.files if x.id == file_id), None)
    path = dms.files_dir(record.id) / f.file if f else None
    if f is None or not path.is_file():
        raise HTTPException(404, "Datei nicht gefunden.")
    return _send(path, f.name, f.mime)


@app.get("/dms/r/{record_id:int}/case/{src}/{name}")
def dms_case_file(record_id: int, src: str, name: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
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
    return _send(path, entry.get("name") or name, entry.get("type") or "")


@app.get("/dms/r/{record_id:int}/document/{doc_id:int}")
def dms_case_document(record_id: int, doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import workflow
    record, _ = _record(db, user, record_id)
    resp = record.response
    doc = next((d for d in resp.documents if d.id == doc_id), None) if resp else None
    if doc is None or not (workflow.documents_dir(resp) / doc.file).is_file():
        raise HTTPException(404)
    return FileResponse(workflow.documents_dir(resp) / doc.file, filename=f"{resp.ref_no}-{doc.name}.pdf", media_type="application/pdf")


@app.get("/dms/r/{record_id:int}/pdf")
def dms_record_pdf(record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record, _ = _record(db, user, record_id)
    if record.response is None:
        raise HTTPException(404)
    return Response(apps.pdf(record.response.form, record.response), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{record.ref_no or record.id}.pdf"'})


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
        dms._store(record, f.filename.replace("/", "_").replace("\\", "_"), content, "upload", user.name, note, f.content_type or "")
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
    (dms.files_dir(record.id) / f.file).unlink(missing_ok=True)
    dms.log(db, user, "Datei gelöscht", f"{f.name} aus {record.ref_no or record.title}")
    db.delete(f)
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
        old = record.area.name
        record.area_id = int(target)
        db.flush()
        db.refresh(record)
        dms.log(db, user, "verschoben", f"{record.ref_no or record.title}: {old} → {record.area.name}")
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
    return render(request, "dms_new.html", user, write_areas=write, selected=area, today=datetime.now(LOCAL_TZ).date().isoformat())


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
                       note=str(data.get("note", "")).replace("\r\n", "\n").strip()[:10000], created_by=user.name,
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
                dms._store(record, f.filename.replace("/", "_").replace("\\", "_"), content, "upload", user.name, "", f.content_type or "")
                n += 1
    by_id = {a.id: a for a in dms.areas(db)}
    record.retention_until = dms.retention_date(record.closed_at, dms.retention_years(by_id[area_id], by_id))
    record.text = " ".join([title, record.ref_no, record.applicant, record.applicant_email, record.street, record.zip,
                            record.city, record.district, record.note, *[x.name for x in record.files]]).lower()
    dms.log(db, user, "abgelegt", f"„{title}“ mit {n} Datei(en) in {by_id[area_id].name}")
    db.commit()
    flash(request, "Vorgang abgelegt.")
    return redirect(f"/dms/r/{record.id}")


# --- Aktenplan ----------------------------------------------------------------------------------

@app.get("/dms/areas")
def dms_areas(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    tree = dms.tree(db)
    counts = {a.id: 0 for a, _ in tree}
    for (aid,) in db.execute(select(DmsRecord.area_id)):
        counts[aid] = counts.get(aid, 0) + 1
    by_id = {a.id: a for a, _ in tree}
    return render(request, "dms_areas.html", user, tree=tree, counts=counts, by_id=by_id, label=dms.label,
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
    _manager(user)
    area = db.get(DmsArea, area_id)
    if area is None:
        raise HTTPException(404)
    if db.scalar(select(DmsRecord.id).where(DmsRecord.area_id == area_id).limit(1)) or \
            db.scalar(select(DmsArea.id).where(DmsArea.parent_id == area_id).limit(1)):
        flash(request, "Der Bereich enthält noch Einträge oder Unterbereiche.", "error")
        return redirect("/dms/areas")
    from .db import Form
    for form in db.scalars(select(Form).where(Form.dms_area_id == area_id)):
        form.dms_area_id = None
    db.delete(area)
    db.commit()
    flash(request, "Bereich gelöscht.")
    return redirect("/dms/areas")


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
            dms.delete_record(db, record, user, "Aufbewahrungsfrist abgelaufen")
            n += 1
    db.commit()
    flash(request, f"{n} Eintrag/Einträge nach Ablauf der Aufbewahrungsfrist gelöscht und protokolliert.")
    return redirect("/dms/retention")
