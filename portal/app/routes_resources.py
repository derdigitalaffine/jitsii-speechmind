"""Ressourcenbuchung – Verwaltung: Ressourcen pflegen, Belegung, Anfragen, Übergabe/Abnahme, interne und
Serienbuchungen, geteilte Kalender, Feiertage."""

import json
import re
import secrets
from datetime import date, datetime, timedelta

from fastapi import Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import forms as fm, holidays, links, payments as pay, resources as rs, shares as sh
from .config import settings
from .db import (
    CustomHoliday, Group, Resource, ResourceBooking, ResourceCalendar, ResourceClosure, ResourceExtra, ResourcePhoto,
    ResourceTariff, ResourceUnit, User, get_settings, set_setting, to_local, utcnow,
)
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, redirect, render, require

res_user = require("resources")
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_PHOTO = 8 * 1024 * 1024


def files_dir(resource_id: int):
    return settings.data_dir / "resources" / str(resource_id)


def _module_on() -> None:
    if "resources" not in enabled_modules():
        raise HTTPException(404, "Die Ressourcenbuchung ist auf diesem Server nicht eingeschaltet.")


def _res(db, rid: int, user: User, need: int) -> tuple[Resource, int]:
    _module_on()
    res = db.get(Resource, rid)
    lvl = rs.level(db, user, res)
    if res is None or lvl == 0:
        raise HTTPException(404, "Ressource nicht gefunden.")
    if lvl < need:
        raise HTTPException(403, "Für diese Aktion reicht Ihre Freigabe für die Ressource nicht aus.")
    return res, lvl


def _booking(db, bid: int, user: User, need: int) -> tuple[ResourceBooking, int]:
    b = db.get(ResourceBooking, bid)
    if b is None:
        raise HTTPException(404, "Buchung nicht gefunden.")
    _, lvl = _res(db, b.resource_id, user, need)
    return b, lvl


def _users(db):
    return db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()


def _groups(db):
    return db.scalars(select(Group).order_by(Group.name)).all()


# --- Übersicht -----------------------------------------------------------------------------

@app.get("/resources")
def resources_list(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    items = rs.visible(db, user)
    if not items and not user.can("resources"):
        raise HTTPException(403, "Für „Ressourcen“ fehlt die Berechtigung. Bitte wenden Sie sich an die Verwaltung des Portals.")
    managed = [r.id for r, lvl in items if lvl >= 3]
    return render(request, "resources.html", user, items=items, counts=rs.booking_counts(db, managed), money=pay.money,
                  modes=rs.MODES, statuses=rs.STATUSES, when=rs.when_text, unit_label=rs.unit_label, unit_ids=rs.unit_ids)


@app.post("/resources/new", dependencies=[Depends(check_csrf)])
def resource_create(request: Request, name: str = Form(...), category: str = Form(""), user: User = Depends(res_user),
                    db: Session = Depends(get_db)):
    _module_on()
    name = " ".join(name.split())[:200]
    if not name:
        flash(request, "Bitte einen Namen angeben.", "error")
        return redirect("/resources")
    res = Resource(owner_id=user.id, name=name, category=" ".join(category.split())[:80], slug=rs.unique_slug(db, name),
                   manager_user_id=user.id, active=False)
    db.add(res)
    db.flush()
    res.tariffs.append(ResourceTariff(name="Standard", percent=100, position=0))
    db.commit()
    flash(request, "Ressource angelegt. Richten Sie jetzt Zeiten, Preise und Zusatzleistungen ein und schalten Sie sie dann frei.")
    return redirect(f"/resources/{res.id}/edit")


@app.get("/resources/{rid:int}")
def resource_detail(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, lvl = _res(db, rid, user, 1)
    upcoming = db.scalars(select(ResourceBooking).where(ResourceBooking.resource_id == res.id,
                                                        ResourceBooking.status.in_(("requested", "confirmed")),
                                                        ResourceBooking.ends_at > utcnow())
                          .order_by(ResourceBooking.starts_at).limit(50)).all()
    return render(request, "resource.html", user, res=res, level=lvl, upcoming=upcoming, statuses=rs.STATUSES,
                  when=rs.when_text, unit_label=rs.unit_label, unit_ids=rs.unit_ids, money=pay.money,
                  share_levels=sh.LEVELS["resource"], users=_users(db) if lvl == 4 else [],
                  groups=_groups(db) if lvl == 4 else [], public_link=f"{links.base('resources')}/r/{res.slug}")


@app.get("/resources/{rid:int}/events.json")
def resource_events(request: Request, rid: int, start: str = "", end: str = "", user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    res, lvl = _res(db, rid, user, 1)
    s, e = _range(start, end)
    events = rs.calendar_events(db, [res], s, e, "full" if lvl >= 2 else "title", True, staff_links=True)
    return JSONResponse(rs.fc_events(events), headers={"Cache-Control": "no-store"})


def _range(start: str, end: str) -> tuple[datetime, datetime]:
    try:
        s = datetime.fromisoformat(start[:19]) if start else utcnow() - timedelta(days=31)
        e = datetime.fromisoformat(end[:19]) if end else utcnow() + timedelta(days=62)
    except ValueError:
        s, e = utcnow() - timedelta(days=31), utcnow() + timedelta(days=62)
    s, e = s.replace(tzinfo=None), e.replace(tzinfo=None)
    if e - s > timedelta(days=400):
        e = s + timedelta(days=400)
    return s - timedelta(days=1), e + timedelta(days=1)


# --- Bearbeiten ----------------------------------------------------------------------------

@app.get("/resources/{rid:int}/edit")
def resource_edit(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, lvl = _res(db, rid, user, 3)
    from . import dms
    dms_areas = []
    if "dms" in enabled_modules():
        by_id = {a.id: a for a in dms.areas(db)}
        dms_areas = [(a, dms.label(a, by_id)) for a, _ in dms.tree(db)]
    editor = {
        "units": [{"id": u.id, "name": u.name, "description": u.description, "capacity": u.capacity,
                   **{k: rs.money_input(getattr(u, k)) for k in ("price_day", "price_block", "price_hour", "wkd_day", "wkd_block", "wkd_hour")}}
                  for u in res.parts],
        "tariffs": [{"id": t.id, "name": t.name, "percent": t.percent, "description": t.description, "needs_proof": t.needs_proof}
                    for t in res.tariffs],
        "extras": [{"id": x.id, "name": x.name, "description": x.description, "price": rs.money_input(x.price_cents), "per": x.per,
                    "stock": x.stock, "max_qty": x.max_qty, "mandatory": x.mandatory, "active": x.active} for x in res.extras],
        "blocks": rs.blocks(res), "hours": rs.hours(res), "fields": rs.fields(res), "per": rs.EXTRA_PER,
        "requestTypes": {k: fm.TYPES[k][:2] for k in ("short", "long", "radio", "checkbox", "dropdown", "date", "file")},
        "subtypes": fm.SUBTYPES,
    }
    return render(request, "resource_edit.html", user, res=res, level=lvl, editor=editor, modes=rs.MODES, users=_users(db),
                  groups=_groups(db), dms_areas=dms_areas, price=rs.money_input, pay_methods=pay.METHODS,
                  closures=[(c, (to_local(c.ends_at) - timedelta(seconds=1)).date()) for c in res.closures])


def _clean_list(raw: str, limit: int = 100) -> list:
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    return data[:limit] if isinstance(data, list) else []


def _int(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


@app.post("/resources/{rid:int}/edit", dependencies=[Depends(check_csrf)])
async def resource_save(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, lvl = _res(db, rid, user, 3)
    data = await request.form()
    text = lambda k, n=255: " ".join(str(data.get(k, "")).split())[:n]  # noqa: E731
    res.name = text("name", 200) or res.name
    res.category = text("category", 80)
    res.description = str(data.get("description", "")).replace("\r\n", "\n").strip()[:10000]
    res.equipment = str(data.get("equipment", "")).replace("\r\n", "\n").strip()[:5000]
    res.location = text("location")
    for key in ("lat", "lon"):
        try:
            v = float(str(data.get(key, "")).replace(",", "."))
            setattr(res, key, round(v, 6) if (-90 <= v <= 90 if key == "lat" else -180 <= v <= 180) else None)
        except ValueError:
            setattr(res, key, None)
    res.capacity = _int(data.get("capacity"), 0, 100000, 0)
    new_slug = rs.slug(text("slug", 80) or res.name)
    res.slug = rs.unique_slug(db, new_slug, res.id)
    res.active, res.public = data.get("active") == "1", data.get("public") == "1"
    res.mode = "instant" if data.get("mode") == "instant" else "request"
    res.units = ",".join(m for m in rs.MODES if m in data.getlist("units")) or "day"
    res.slot_minutes = _int(data.get("slot_minutes"), 5, 1440, 60)
    res.min_minutes = _int(data.get("min_minutes"), 0, 10080, 60)
    res.max_minutes = _int(data.get("max_minutes"), 0, 10080, 0)
    res.max_days = _int(data.get("max_days"), 1, 60, 3)
    res.min_notice_hours = _int(data.get("min_notice_hours"), 0, 24 * 365, 48)
    res.max_advance_days = _int(data.get("max_advance_days"), 1, 3650, 365)
    res.buffer_before = _int(data.get("buffer_before"), 0, 1440, 0)
    res.buffer_after = _int(data.get("buffer_after"), 0, 1440, 0)
    for key in ("price_day", "price_block", "price_hour", "wkd_day", "wkd_block", "wkd_hour", "deposit_cents"):
        setattr(res, key, rs.parse_cents(data.get(key, "")))
    res.pay_methods = ",".join(m for m in ("paypal", "transfer", "cash") if m in data.getlist("pay_methods")) or "transfer"
    res.pay_days = _int(data.get("pay_days"), 1, 90, 7)
    res.cost_center = text("cost_center", 120)
    res.self_cancel = data.get("self_cancel") == "1"
    res.cancel_free_days = _int(data.get("cancel_free_days"), 0, 365, 14)
    res.cancel_fee_percent = _int(data.get("cancel_fee_percent"), 0, 100, 0)
    res.terms_text = str(data.get("terms_text", "")).replace("\r\n", "\n").strip()[:20000]
    uid, gid = str(data.get("manager_user_id", "")), str(data.get("manager_group_id", ""))
    res.manager_user_id = int(uid) if uid.isdigit() and db.get(User, int(uid)) else None
    res.manager_group_id = int(gid) if gid.isdigit() and db.get(Group, int(gid)) else None
    mailbox = str(data.get("mailbox", "")).strip().lower()[:255]
    res.mailbox = mailbox if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", mailbox) else ""
    aid = str(data.get("dms_area_id", ""))
    res.dms_area_id = int(aid) if aid.isdigit() else None
    # Zeitblöcke und Buchungszeiten
    blocks = []
    for b in _clean_list(str(data.get("blocks_json", "")), 20):
        if isinstance(b, dict) and rs.TIME_RE.match(str(b.get("start", ""))) and rs.TIME_RE.match(str(b.get("end", ""))):
            blocks.append({"id": str(b.get("id") or secrets.token_hex(3))[:12], "label": " ".join(str(b.get("label", "")).split())[:60]
                           or f"{b['start']}–{b['end']}", "start": b["start"], "end": b["end"]})
    res.blocks_json = json.dumps(blocks, ensure_ascii=False)
    try:
        raw_hours = json.loads(str(data.get("hours_json", "{}")))
    except ValueError:
        raw_hours = {}
    clean_hours = {}
    if isinstance(raw_hours, dict):
        for day, ranges in raw_hours.items():
            if day in [str(i) for i in range(7)] and isinstance(ranges, list):
                clean_hours[day] = [[a, b] for a, b in (r for r in ranges if isinstance(r, list) and len(r) == 2)
                                    if rs.TIME_RE.match(str(a)) and (rs.TIME_RE.match(str(b)) or b == "24:00")][:4]
    res.hours_json = json.dumps(clean_hours)
    # Teilräume, Tarife, Zusatzleistungen
    _sync_children(db, res, "parts", ResourceUnit, _clean_list(str(data.get("units_json", "")), 50), _unit)
    tariffs = _clean_list(str(data.get("tariffs_json", "")), 20)
    _sync_children(db, res, "tariffs", ResourceTariff, tariffs, _tariff)
    if not res.tariffs:
        res.tariffs.append(ResourceTariff(name="Standard", percent=100))
    _sync_children(db, res, "extras", ResourceExtra, _clean_list(str(data.get("extras_json", "")), 60), _extra)
    from .workflow import clean_request_items
    try:
        res.fields_json = json.dumps(clean_request_items(json.loads(str(data.get("fields_json", "[]")))), ensure_ascii=False)
    except ValueError:
        pass
    db.commit()
    flash(request, "Ressource gespeichert." + ("" if res.active else " Sie ist noch nicht freigeschaltet (Schalter „aktiv“)."))
    return redirect(f"/resources/{res.id}/edit" + ("#" + str(data.get("tab", "")) if data.get("tab") else ""))


def _sync_children(db, res: Resource, attr: str, model, rows: list, apply) -> None:
    existing = {c.id: c for c in getattr(res, attr)}
    keep = []
    for pos, row in enumerate(rows):
        if not isinstance(row, dict) or not " ".join(str(row.get("name", "")).split()):
            continue
        child = existing.pop(row.get("id"), None) if isinstance(row.get("id"), int) else None
        if child is None:
            child = model(name="")
            getattr(res, attr).append(child)
        apply(child, row)
        child.position = pos
        keep.append(child)
    for child in existing.values():
        getattr(res, attr).remove(child)


def _unit(u: ResourceUnit, row: dict) -> None:
    u.name = " ".join(str(row.get("name", "")).split())[:200]
    u.description = str(row.get("description", "")).strip()[:2000]
    u.capacity = _int(row.get("capacity"), 0, 100000, 0)
    for k in ("price_day", "price_block", "price_hour", "wkd_day", "wkd_block", "wkd_hour"):
        setattr(u, k, rs.parse_cents(row.get(k, "")))


def _tariff(t: ResourceTariff, row: dict) -> None:
    t.name = " ".join(str(row.get("name", "")).split())[:120]
    t.percent = _int(row.get("percent"), 0, 1000, 100)
    t.description = str(row.get("description", "")).strip()[:500]
    t.needs_proof = bool(row.get("needs_proof"))


def _extra(x: ResourceExtra, row: dict) -> None:
    x.name = " ".join(str(row.get("name", "")).split())[:200]
    x.description = str(row.get("description", "")).strip()[:500]
    x.price_cents = rs.parse_cents(row.get("price", ""))
    x.per = row.get("per") if row.get("per") in rs.EXTRA_PER else "once"
    stock = str(row.get("stock", "")).strip()
    x.stock = int(stock) if stock.isdigit() else None
    x.max_qty = _int(row.get("max_qty"), 1, 10000, 1)
    x.mandatory, x.active = bool(row.get("mandatory")), row.get("active", True) is not False


@app.post("/resources/{rid:int}/photos", dependencies=[Depends(check_csrf)])
async def resource_photo(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    data = await request.form()
    n = 0
    for f in data.getlist("photos"):
        if not isinstance(f, UploadFile) or not f.filename:
            continue
        content = await f.read(MAX_PHOTO + 1)
        kind = _image_type(content)
        if len(content) > MAX_PHOTO or kind is None:
            flash(request, f"„{f.filename}“ übersprungen (nur JPG, PNG, WebP bis 8 MB).", "error")
            continue
        target = files_dir(res.id)
        target.mkdir(parents=True, exist_ok=True)
        name = secrets.token_hex(10) + kind
        (target / name).write_bytes(content)
        res.photos.append(ResourcePhoto(file=name, name=f.filename[:200], position=len(res.photos)))
        n += 1
    db.commit()
    if n:
        flash(request, f"{n} Foto(s) hinzugefügt.")
    return redirect(f"/resources/{res.id}/edit#fotos")


def _image_type(content: bytes) -> str | None:
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


@app.post("/resources/{rid:int}/photos/{pid:int}/delete", dependencies=[Depends(check_csrf)])
def resource_photo_delete(request: Request, rid: int, pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    photo = db.get(ResourcePhoto, pid)
    if photo and photo.resource_id == res.id:
        (files_dir(res.id) / photo.file).unlink(missing_ok=True)
        db.delete(photo)
        db.commit()
    return redirect(f"/resources/{res.id}/edit#fotos")


@app.post("/resources/{rid:int}/terms", dependencies=[Depends(check_csrf)])
async def resource_terms(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    data = await request.form()
    f = data.get("file")
    if data.get("remove") == "1":
        if res.terms_file:
            (files_dir(res.id) / res.terms_file).unlink(missing_ok=True)
        res.terms_file = ""
    elif isinstance(f, UploadFile) and f.filename:
        content = await f.read(20 * 1024 * 1024 + 1)
        if not content.startswith(b"%PDF") or len(content) > 20 * 1024 * 1024:
            flash(request, "Bitte eine PDF-Datei bis 20 MB.", "error")
            return redirect(f"/resources/{res.id}/edit#bedingungen")
        files_dir(res.id).mkdir(parents=True, exist_ok=True)
        name = secrets.token_hex(10) + ".pdf"
        (files_dir(res.id) / name).write_bytes(content)
        res.terms_file = name
    db.commit()
    flash(request, "Nutzungsordnung gespeichert.")
    return redirect(f"/resources/{res.id}/edit#bedingungen")


@app.post("/resources/{rid:int}/closures", dependencies=[Depends(check_csrf)])
def resource_closure_add(request: Request, rid: int, date_from: str = Form(...), date_to: str = Form(""),
                         unit_id: str = Form(""), reason: str = Form(""), user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    d1, d2 = rs._date(date_from), rs._date(date_to) or rs._date(date_from)
    if not d1:
        flash(request, "Bitte ein Datum angeben.", "error")
        return redirect(f"/resources/{res.id}/edit#zeiten")
    if d2 < d1:
        d1, d2 = d2, d1
    unit = int(unit_id) if unit_id.isdigit() and any(u.id == int(unit_id) for u in res.parts) else None
    res.closures.append(ResourceClosure(unit_id=unit, reason=" ".join(reason.split())[:255],
                                        starts_at=rs._utc(datetime.combine(d1, datetime.min.time())),
                                        ends_at=rs._utc(datetime.combine(d2 + timedelta(days=1), datetime.min.time()))))
    db.commit()
    flash(request, "Sperrzeit eingetragen.")
    return redirect(f"/resources/{res.id}/edit#zeiten")


@app.post("/resources/{rid:int}/closures/{cid:int}/delete", dependencies=[Depends(check_csrf)])
def resource_closure_delete(request: Request, rid: int, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    c = db.get(ResourceClosure, cid)
    if c and c.resource_id == res.id:
        db.delete(c)
        db.commit()
    return redirect(f"/resources/{res.id}/edit#zeiten")


@app.post("/resources/{rid:int}/delete", dependencies=[Depends(check_csrf)])
def resource_delete(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 4)
    if db.scalar(select(ResourceBooking.id).where(ResourceBooking.resource_id == res.id, ResourceBooking.status.in_(rs.ACTIVE),
                                                  ResourceBooking.ends_at > utcnow()).limit(1)):
        flash(request, "Es gibt noch anstehende Buchungen – bitte zuerst stornieren oder die Ressource nur deaktivieren.", "error")
        return redirect(f"/resources/{res.id}/edit")
    import shutil
    shutil.rmtree(files_dir(res.id), ignore_errors=True)
    db.delete(res)
    db.commit()
    flash(request, "Ressource gelöscht.")
    return redirect("/resources")


@app.post("/resources/{rid:int}/shares", dependencies=[Depends(check_csrf)])
async def resource_share_add(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 4)
    added, lv = sh.add(db, "resource", res, await request.form())
    db.commit()
    flash(request, f"{added} Freigabe(n): {sh.LEVELS['resource'][lv][0]}." if added else "Bitte Personen oder Gruppen wählen.")
    return redirect(f"/resources/{res.id}#teilen")


@app.post("/resources/{rid:int}/shares/{share_id:int}", dependencies=[Depends(check_csrf)])
def resource_share_update(request: Request, rid: int, share_id: int, action: str = Form("save"), level: int = Form(1),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 4)
    msg = sh.update(db, "resource", res, share_id, action, level)
    db.commit()
    flash(request, msg or "Freigabe nicht gefunden.")
    return redirect(f"/resources/{res.id}#teilen")


# --- Buchungen (Verwaltung) ------------------------------------------------------------------

@app.get("/resources/bookings")
def bookings_list(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    items = {r.id: (r, lvl) for r, lvl in rs.visible(db, user)}
    if not items:
        raise HTTPException(403, "Keine Ressourcen freigegeben.")
    f = {k: request.query_params.get(k, "") for k in ("status", "resource", "q", "when")}
    q = select(ResourceBooking).where(ResourceBooking.resource_id.in_(list(items)))
    if f["resource"].isdigit():
        q = q.where(ResourceBooking.resource_id == int(f["resource"]))
    if f["status"] in rs.STATUSES:
        q = q.where(ResourceBooking.status == f["status"])
    elif not f["status"]:
        q = q.where(ResourceBooking.status.in_(rs.ACTIVE))
    if f["when"] != "past":
        q = q.where(ResourceBooking.ends_at > utcnow() - timedelta(days=1))
    else:
        q = q.where(ResourceBooking.ends_at <= utcnow())
    if f["q"]:
        like = f"%{f['q'].strip()}%"
        q = q.where(or_(ResourceBooking.ref.ilike(like), ResourceBooking.name.ilike(like), ResourceBooking.email.ilike(like),
                        ResourceBooking.title.ilike(like), ResourceBooking.organizer.ilike(like)))
    rows = db.scalars(q.order_by(ResourceBooking.starts_at.desc() if f["when"] == "past" else ResourceBooking.starts_at).limit(500)).all()
    return render(request, "resource_bookings.html", user, rows=rows, items=items, f=f, statuses=rs.STATUSES,
                  when=rs.when_text, unit_label=rs.unit_label, unit_ids=rs.unit_ids, money=pay.money,
                  pay_statuses=pay.STATUSES)


@app.get("/resources/bookings/{bid:int}")
def booking_detail(request: Request, bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b, lvl = _booking(db, bid, user, 1)
    res = b.resource
    items = fm.questions(rs.fields(res))
    answers = rs.answers_of(b)
    series = db.scalars(select(ResourceBooking).where(ResourceBooking.series_id == b.series_id,
                                                      ResourceBooking.id != b.id).order_by(ResourceBooking.starts_at)).all() if b.series_id else []
    return render(request, "resource_booking.html", user, b=b, res=res, level=lvl, statuses=rs.STATUSES, when=rs.when_text,
                  units=rs.unit_label(res, rs.unit_ids(b)), lines=rs.lines_of(b), extras=rs.extras_of(b), money=pay.money,
                  questions=items, answers=answers, display=fm.display, handover=rs.handover(b), series=series,
                  manage_link=rs.manage_link(b), **pay.box(db, user, b.payment, f"/resources/bookings/{b.id}"))


@app.post("/resources/bookings/{bid:int}/decide", dependencies=[Depends(check_csrf)])
def booking_decide(request: Request, bid: int, accept: str = Form(...), message: str = Form(""),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 3)
    if rs.decide(db, b, user, accept == "1", message):
        flash(request, "Buchung bestätigt – Bestätigung und Zahlungsaufforderung sind unterwegs." if accept == "1" else "Anfrage abgelehnt.")
    else:
        flash(request, "Nicht möglich – der Zeitraum ist inzwischen anderweitig belegt oder die Anfrage ist schon entschieden.", "error")
    db.commit()
    return redirect(f"/resources/bookings/{b.id}")


@app.post("/resources/bookings/{bid:int}/cancel", dependencies=[Depends(check_csrf)])
def booking_cancel(request: Request, bid: int, reason: str = Form(""), user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 3)
    info = rs.cancel(db, b, user.name, reason.strip()[:1000], staff=True)
    db.commit()
    flash(request, "Buchung storniert. " + info)
    return redirect(f"/resources/bookings/{b.id}")


@app.post("/resources/bookings/{bid:int}/handover", dependencies=[Depends(check_csrf)])
async def booking_handover(request: Request, bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 3)
    data = await request.form()
    part = "back" if data.get("part") == "back" else "out"
    info = rs.record_handover(db, b, user, part, data)
    db.commit()
    flash(request, ("Abnahme gespeichert. " if part == "back" else "Übergabe gespeichert. ") + info)
    return redirect(f"/resources/bookings/{b.id}#uebergabe")


@app.post("/resources/bookings/{bid:int}/note", dependencies=[Depends(check_csrf)])
def booking_note(request: Request, bid: int, note: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 3)
    if note.strip():
        rs._note(b, f"{user.name}: {note.strip()[:2000]}")
        db.commit()
    return redirect(f"/resources/bookings/{b.id}")


@app.get("/resources/bookings/{bid:int}/pdf")
def booking_pdf(bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 2)
    return Response(rs.confirmation_pdf(db, b), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Buchung-{b.ref}.pdf"'})


@app.get("/resources/bookings/{bid:int}/files/{name}")
def booking_file(bid: int, name: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    b, _ = _booking(db, bid, user, 2)
    if not re.fullmatch(r"[0-9a-f]{16}(\.[a-z0-9]{1,10})?", name):
        raise HTTPException(404)
    path = settings.data_dir / "resources" / "bookings" / str(b.id) / name
    if not path.is_file():
        raise HTTPException(404)
    label = next((f["name"] for v in rs.answers_of(b).values() if isinstance(v, list) for f in v
                  if isinstance(f, dict) and f.get("file") == name), name)
    # Dateiname stammt aus dem Upload: Starlette kodiert ihn korrekt (RFC 5987); Inhalt nie im Portal ausführen
    return FileResponse(path, filename=label, media_type="application/octet-stream",
                        headers={"Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


# --- Interne Buchung / Serie ---------------------------------------------------------------

@app.get("/resources/{rid:int}/book")
def internal_book(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    from .routes_resources_public import booking_ctx
    return render(request, "resource_book.html", user, **booking_ctx(db, res), staff=True)


@app.post("/resources/{rid:int}/book", dependencies=[Depends(check_csrf)])
async def internal_book_save(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    data = await request.form()
    contact, errors = rs.contact_from(data)
    errors = [e for e in errors if "E-Mail" not in e or str(data.get("email", "")).strip()]
    contact["email"] = contact["email"] if "@" in contact["email"] else ""
    if not contact["name"]:
        contact["name"] = user.name
        errors = [e for e in errors if "Namen" not in e]
    free = data.get("free") == "1"
    repeat = _int(data.get("repeat_weeks"), 0, 52, 0)
    until = rs._date(data.get("repeat_until"))
    series_id = secrets.token_hex(6) if repeat and until else ""
    q = rs.quote(db, res, data, staff=True)
    if errors or not q["ok"]:
        for e in errors + q["errors"]:
            flash(request, e, "error")
        return redirect(f"/resources/{res.id}/book")
    made, skipped = [], []
    shift = timedelta(0)
    while True:
        qq = q if not shift else rs.quote(db, res, _shifted(data, shift), staff=True)
        if qq["ok"]:
            b = rs.create(db, res, qq, contact, {}, internal=True, by=user.name, free=free, series_id=series_id)
            b.decided_at, b.decided_by = utcnow(), user.name
            if b.total_cents and b.email:
                rs._finalize(db, b)
            made.append(b)
        else:
            skipped.append(rs.when_text(ResourceBooking(starts_at=qq["start"], ends_at=qq["end"], mode=qq["mode"])) if qq["start"] else "?")
        if not series_id:
            break
        shift += timedelta(weeks=repeat)
        if (to_local(q["start"]).date() + shift) > until or len(made) + len(skipped) >= 200:
            break
    db.commit()
    msg = f"{len(made)} Buchung(en) eingetragen."
    if skipped:
        msg += f" Übersprungen (belegt): {', '.join(skipped[:8])}{' …' if len(skipped) > 8 else ''}"
    flash(request, msg, "error" if skipped and not made else "ok")
    return redirect(f"/resources/bookings/{made[0].id}" if made else f"/resources/{res.id}")


class _Shifted(dict):
    def getlist(self, key):
        v = self.get(key, [])
        return v if isinstance(v, list) else [v]


def _shifted(data, delta: timedelta):
    out = _Shifted({k: (data.getlist(k) if len(data.getlist(k)) > 1 or k in ("units", "blocks") else data.get(k)) for k in data.keys()})
    for key in ("date", "date_from", "date_to"):
        d = rs._date(out.get(key))
        if d:
            out[key] = (d + delta).isoformat()
    return out


# --- Geteilte Kalender ---------------------------------------------------------------------

@app.get("/resources/calendars")
def calendars(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    items = [(r, lvl) for r, lvl in rs.visible(db, user)]
    if not items:
        raise HTTPException(403)
    own = db.scalars(select(ResourceCalendar).order_by(ResourceCalendar.created_at.desc())).all()
    own = [c for c in own if user.is_admin or c.created_by_id == user.id]
    names = {r.id: r.name for r, _ in items}
    return render(request, "resource_calendars.html", user, items=items, calendars=own, names=names,
                  base=links.base("resources"))


@app.post("/resources/calendars", dependencies=[Depends(check_csrf)])
async def calendar_create(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    allowed = {r.id: lvl for r, lvl in rs.visible(db, user)}
    level_name = data.get("level") if data.get("level") in ("busy", "title", "full") else "busy"
    need = {"busy": 1, "title": 1, "full": 2}[level_name]
    ids = [int(x) for x in data.getlist("resources") if str(x).isdigit() and allowed.get(int(x), 0) >= need]
    if not ids:
        flash(request, "Bitte mindestens eine Ressource wählen, für die Sie diese Detailstufe teilen dürfen.", "error")
        return redirect("/resources/calendars")
    cal = ResourceCalendar(name=" ".join(str(data.get("name", "")).split())[:200] or "Belegungskalender",
                           token=secrets.token_urlsafe(24), level=level_name, tentative=data.get("tentative") == "1",
                           resource_ids=",".join(map(str, ids)), created_by_id=user.id, embed=data.get("embed") == "1")
    db.add(cal)
    db.commit()
    flash(request, "Kalender-Link erstellt.")
    return redirect(f"/resources/calendars#cal-{cal.id}")


@app.post("/resources/calendars/{cid:int}/delete", dependencies=[Depends(check_csrf)])
def calendar_delete(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cal = db.get(ResourceCalendar, cid)
    if cal is None or not (user.is_admin or cal.created_by_id == user.id):
        raise HTTPException(404)
    db.delete(cal)
    db.commit()
    flash(request, "Link widerrufen – Abos damit funktionieren nicht mehr.")
    return redirect("/resources/calendars")


# --- Feiertage ---------------------------------------------------------------------------------

@app.get("/resources/holidays")
def holidays_page(request: Request, year: int = 0, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    year = year or to_local(utcnow()).year
    cfg = get_settings(db)
    custom = db.scalars(select(CustomHoliday).order_by(CustomHoliday.day)).all()
    return render(request, "resource_holidays.html", user, year=year, state=cfg.get("holiday_state", "RP"),
                  states=holidays.STATES, days=holidays.special_days(db, year), custom=custom)


@app.post("/resources/holidays", dependencies=[Depends(check_csrf)])
def holidays_save(request: Request, state: str = Form(""), day: str = Form(""), name: str = Form(""),
                  user: User = Depends(res_user), db: Session = Depends(get_db)):
    if state in holidays.STATES:
        if not user.is_admin and state != get_settings(db).get("holiday_state"):
            raise HTTPException(403, "Das Bundesland stellen Admins ein.")
        set_setting(db, "holiday_state", state)
    d = rs._date(day)
    if d and name.strip():
        db.add(CustomHoliday(day=d, name=" ".join(name.split())[:120]))
    db.commit()
    flash(request, "Gespeichert.")
    return redirect(f"/resources/holidays?year={d.year if d else date.today().year}")


@app.post("/resources/holidays/{hid:int}/delete", dependencies=[Depends(check_csrf)])
def holidays_delete(request: Request, hid: int, user: User = Depends(res_user), db: Session = Depends(get_db)):
    h = db.get(CustomHoliday, hid)
    if h:
        db.delete(h)
        db.commit()
    return redirect("/resources/holidays")
