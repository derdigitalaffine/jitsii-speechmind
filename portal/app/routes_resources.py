"""Ressourcenbuchung – Verwaltung: Ressourcen pflegen, Belegung, Anfragen, Übergabe/Abnahme, interne und
Serienbuchungen, geteilte Kalender, Feiertage."""

import json
import re
import secrets
from datetime import date, datetime, timedelta

from fastapi import Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile  # das liefert request.form() (nicht fastapi.UploadFile)
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import forms as fm, holidays, links, payments as pay, photos, res_admin, res_clubs, res_wait, resources as rs, shares as sh
from .config import settings
from .db import (
    CustomHoliday, Group, Resource, ResourceBooking, ResourceCalendar, ResourceClosure, ResourceClub, ResourceExtra,
    ResourceCaretaker, ResourcePhoto, ResourceTariff, ResourceUnit, ResourceWait, User, get_settings, set_setting, to_local, utcnow,
)
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, redirect, render, require

res_user = require("resources")
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_PHOTO = 25 * 1024 * 1024    # Handyfotos; gespeichert wird eine verkleinerte Fassung
MAX_PHOTOS = 40


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

VIEWS = ("karten", "tabelle")


def list_view(request: Request, cookie: str) -> tuple[str, bool]:
    """Ansicht einer Liste (Karten oder Tabelle): aus ?ansicht=…, sonst wie zuletzt gewählt (Cookie).
    Gibt (Ansicht, neu gewählt) zurück – bei neu gewählt das Cookie mit remember_view setzen."""
    chosen = request.query_params.get("ansicht", "")
    if chosen in VIEWS:
        return chosen, True
    saved = request.cookies.get(cookie, "")
    return (saved if saved in VIEWS else "karten"), False


def remember_view(response, cookie: str, view: str):
    response.set_cookie(cookie, view, max_age=365 * 86400, httponly=True, samesite="lax", secure=settings.secure_cookies)
    return response


@app.get("/resources")
def resources_list(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    items = rs.visible(db, user)
    if not items and not user.can("resources"):
        raise HTTPException(403, "Für „Ressourcen“ fehlt die Berechtigung. Bitte wenden Sie sich an die Verwaltung des Portals.")
    managed = [r.id for r, lvl in items if lvl >= 3]
    counts = rs.booking_counts(db, managed)
    requests_by = {}
    for b in counts["requested"]:
        requests_by[b.resource_id] = requests_by.get(b.resource_id, 0) + 1
    next_by: dict[int, ResourceBooking] = {}
    ids = [r.id for r, _lvl in items]
    if ids:
        for b in db.scalars(select(ResourceBooking).where(
                ResourceBooking.resource_id.in_(ids), ResourceBooking.status.in_(("requested", "confirmed")),
                ResourceBooking.ends_at >= utcnow()).order_by(ResourceBooking.starts_at)):
            next_by.setdefault(b.resource_id, b)
    view, chosen = list_view(request, "jsm_res_view")
    response = render(request, "resources.html", user, items=items, counts=counts, money=pay.money, view=view,
                      requests_by=requests_by, next_by=next_by, modes=rs.MODES, statuses=rs.STATUSES, when=rs.when_text,
                      unit_label=rs.unit_label, unit_ids=rs.unit_ids)
    return remember_view(response, "jsm_res_view", view) if chosen else response


@app.get("/resources/new")
def resource_new(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    from . import orgs
    return render(request, "resource_new.html", user, org_options=orgs.options(db), presets=res_admin.PRESETS, groups=_groups(db))


@app.post("/resources/new", dependencies=[Depends(check_csrf)])
async def resource_create(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    """Einrichtungsassistent: Vorlage, Name, Ort, Größe, Preis und Zuständigkeit – der Rest in den Reitern."""
    _module_on()
    data = await request.form()
    text = lambda k, n=255: " ".join(str(data.get(k, "")).split())[:n]  # noqa: E731
    name = text("name", 200)
    if not name:
        flash(request, "Bitte einen Namen angeben.", "error")
        return redirect("/resources/new")
    res = Resource(owner_id=user.id, name=name, category=text("category", 80), slug=rs.unique_slug(db, name),
                   manager_user_id=user.id, active=False, location=text("location"),
                   capacity=_int(data.get("capacity"), 0, 100000, 0))
    pid = str(data.get("provider_id", "") or "")
    from .db import Organization
    res.provider_id = int(pid) if pid.isdigit() and db.get(Organization, int(pid)) else None
    db.add(res)
    keep = [int(x) for x in data.getlist("extras_keep") if str(x).isdigit()]
    res_admin.apply_preset(res, str(data.get("preset", "empty")), keep_extras=keep if "price_day" in data else None)
    # Preise und Kaution wie im Assistenten angezeigt übernehmen (leer = kostenlos bzw. keine Kaution)
    if any(k in data for k in ("price_day", "price_block", "price_hour")):
        for m in ("day", "block", "hour"):
            raw = str(data.get(f"price_{m}", "") or "").strip()
            setattr(res, f"price_{m}", (pay.parse_amount(raw) or 0) if raw else 0)
        raw = str(data.get("deposit", "") or "").strip()
        res.deposit_cents = (pay.parse_amount(raw) or 0) if raw else 0
    gid = str(data.get("manager_group_id", ""))
    res.manager_group_id = int(gid) if gid.isdigit() and db.get(Group, int(gid)) else None
    mailbox = str(data.get("mailbox", "")).strip().lower()[:255]
    res.mailbox = mailbox if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", mailbox) else ""
    db.flush()
    res.tariffs.append(ResourceTariff(name="Standard", percent=100, position=0))
    db.commit()
    flash(request, "Ressource angelegt. Die Checkliste zeigt, was vor dem Freischalten noch fehlt.")
    return redirect(f"/resources/{res.id}/edit?neu=1")


@app.get("/resources/{rid:int}")
def resource_detail(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, lvl = _res(db, rid, user, 1)
    upcoming = db.scalars(select(ResourceBooking).where(ResourceBooking.resource_id == res.id,
                                                        ResourceBooking.status.in_(("requested", "confirmed")),
                                                        ResourceBooking.ends_at > utcnow())
                          .order_by(ResourceBooking.starts_at).limit(50)).all()
    waits = db.scalars(select(ResourceWait).where(ResourceWait.resource_id == res.id,
                                                  ResourceWait.status.in_(("waiting", "offered", "unconfirmed")))
                       .order_by(ResourceWait.starts_at, ResourceWait.created_at)).all() if lvl >= 2 else []
    return render(request, "resource.html", user, res=res, level=lvl, upcoming=upcoming, statuses=rs.STATUSES,
                  waits=waits, wait_statuses=res_wait.STATUSES, wait_when=res_wait.when,
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
                    "stock": x.stock, "max_qty": x.max_qty, "mandatory": x.mandatory, "active": x.active, "per_n": x.per_n or "",
                    "tiers": rs.tiers_text(rs.tiers(x)), "min": rs.money_input(x.min_cents), "max": rs.money_input(x.max_cents),
                    "cancel_rule": x.cancel_rule, "cancel_days": x.cancel_days or ""} for x in res.extras],
        "blocks": rs.blocks(res), "hours": rs.hours(res), "fields": rs.fields(res), "per": rs.EXTRA_PER,
        "cancelRules": rs.CANCEL_RULES,
        "requestTypes": {k: fm.TYPES[k][:2] for k in ("short", "long", "radio", "checkbox", "dropdown", "date", "file")},
        "subtypes": fm.SUBTYPES,
    }
    from . import orgs
    laws_list = []
    if "laws" in enabled_modules():
        from .db import LawText
        laws_list = db.scalars(select(LawText).order_by(LawText.title)).all()
    return render(request, "resource_edit.html", user, res=res, level=lvl, photo_list=_photo_list(res),
                  laws=laws_list, legal=rs.legal_raw(res), legal_roles=rs.LEGAL_ROLES,
                  all_caretakers=db.scalars(select(ResourceCaretaker).order_by(ResourceCaretaker.name)).all(), editor=editor, modes=rs.MODES, users=_users(db),
                  org_options=orgs.options(db),
                  checklist=res_admin.checklist(res), fresh=request.query_params.get("neu") == "1",
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
    if "provider_id" in data:
        pid = str(data.get("provider_id", "") or "")
        from .db import Organization
        res.provider_id = int(pid) if pid.isdigit() and db.get(Organization, int(pid)) else None
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
    deposit_methods = [m for m in ("cash", "transfer", "paypal") if m in data.getlist("deposit_methods")]
    preferred = str(data.get("deposit_method", "cash"))
    if preferred not in ("cash", "transfer", "paypal"):
        preferred = "cash"
    res.deposit_guest_choice = data.get("deposit_guest_choice") == "1"
    res.deposit_methods = ",".join([preferred] + [m for m in deposit_methods if m != preferred])
    res.pay_days = _int(data.get("pay_days"), 1, 90, 7)
    res.cost_center = text("cost_center", 120)
    res.self_cancel = data.get("self_cancel") == "1"
    res.cancel_free_days = _int(data.get("cancel_free_days"), 0, 365, 14)
    res.cancel_fee_percent = _int(data.get("cancel_fee_percent"), 0, 100, 0)
    res.terms_text = str(data.get("terms_text", "")).replace("\r\n", "\n").strip()[:20000]
    if "legal_law" in data:
        res.legal_json = json.dumps(rs.clean_legal(db, data.getlist("legal_law"), data.getlist("legal_para"),
                                                   data.getlist("legal_role"), data.getlist("legal_accept")))
    res.remind_days = _int(data.get("remind_days"), 0, 30, 2)
    res.remind_staff_days = _int(data.get("remind_staff_days"), 0, 30, 1)
    res.remind_text = str(data.get("remind_text", "")).replace("\r\n", "\n").strip()[:5000]
    res.waitlist = data.get("waitlist") == "1"
    if data.get("caretakers_present"):
        for key in ("deposit_release", "protocol_to_booker", "protocol_to_staff", "caretaker_public", "caretaker_remind"):
            setattr(res, key, data.get(key) == "1")
        ids = {int(x) for x in data.getlist("caretakers") if str(x).isdigit()}
        res.caretakers = list(db.scalars(select(ResourceCaretaker).where(ResourceCaretaker.id.in_(ids)))) if ids else []
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
    x.per_n = _int(row.get("per_n"), 0, 100000, 0) if x.per == "persons" else 0
    x.tiers_json = json.dumps(rs.parse_tiers(str(row.get("tiers", ""))) if x.per == "tier" else [])
    x.min_cents, x.max_cents = rs.parse_cents(row.get("min", "")), rs.parse_cents(row.get("max", ""))
    if x.max_cents and x.min_cents > x.max_cents:
        x.min_cents, x.max_cents = x.max_cents, x.min_cents
    x.cancel_rule = row.get("cancel_rule") if row.get("cancel_rule") in rs.CANCEL_RULES else ""
    x.cancel_days = _int(row.get("cancel_days"), 0, 3650, 0) if x.cancel_rule in ("keep", "only") else 0


def _photo_list(res: Resource) -> list[dict]:
    return [{"id": p.id, "src": f"/r/{res.slug}/photo/{p.id}", "thumb": f"/r/{res.slug}/photo/{p.id}?s=thumb",
             "caption": p.caption, "name": p.name} for p in sorted(res.photos, key=lambda x: x.position)]


def _photo_json(res: Resource, **extra) -> JSONResponse:
    return JSONResponse({**extra, "photos": _photo_list(res)})


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _renumber(res: Resource) -> None:
    for i, p in enumerate(sorted(res.photos, key=lambda x: x.position)):
        p.position = i


@app.post("/resources/{rid:int}/photos", dependencies=[Depends(check_csrf)])
async def resource_photo(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Fotos hochladen (auch mehrere): werden verkleinert (max. 1600 px), richtig gedreht, ohne EXIF/GPS als JPEG
    gespeichert und bekommen ein Vorschaubild. Aus dem Editor per fetch (JSON), sonst klassisch mit Weiterleitung."""
    res, _ = _res(db, rid, user, 3)
    data = await request.form()
    added, skipped = 0, []
    target = files_dir(res.id)
    for f in data.getlist("photos"):
        if not isinstance(f, UploadFile) or not f.filename:
            continue
        if len(res.photos) >= MAX_PHOTOS:
            skipped.append(f"„{f.filename}“: höchstens {MAX_PHOTOS} Fotos je Ressource")
            continue
        content = await f.read(MAX_PHOTO + 1)
        if len(content) > MAX_PHOTO or _image_type(content) is None:
            skipped.append(f"„{f.filename}“: nur JPG, PNG oder WebP bis {MAX_PHOTO // 1024 // 1024} MB")
            continue
        try:
            full, thumb, _size = await run_in_threadpool(photos.process, content)
        except ValueError as exc:
            skipped.append(f"„{f.filename}“: {exc}")
            continue
        target.mkdir(parents=True, exist_ok=True)
        stem = secrets.token_hex(10)
        (target / f"{stem}.jpg").write_bytes(full)
        (target / f"{stem}-t.jpg").write_bytes(thumb)
        res.photos.append(ResourcePhoto(file=f"{stem}.jpg", thumb=f"{stem}-t.jpg", name=f.filename[:200],
                                        position=len(res.photos)))
        added += 1
    db.commit()
    db.refresh(res)
    if _wants_json(request):
        return _photo_json(res, added=added, skipped=skipped)
    for msg in skipped:
        flash(request, msg + " – übersprungen.", "error")
    if added:
        flash(request, f"{added} Foto(s) hinzugefügt.")
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
        for name in (photo.file, photo.thumb):
            if name:
                (files_dir(res.id) / name).unlink(missing_ok=True)
        res.photos.remove(photo)
        db.delete(photo)
        _renumber(res)
        db.commit()
    if _wants_json(request):
        return _photo_json(res)
    return redirect(f"/resources/{res.id}/edit#fotos")


@app.post("/resources/{rid:int}/photos/order", dependencies=[Depends(check_csrf)])
async def resource_photo_order(request: Request, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Reihenfolge (ids=3,1,2); das erste Foto ist das Titelbild."""
    res, _ = _res(db, rid, user, 3)
    ids = [int(x) for x in str((await request.form()).get("ids", "")).split(",") if x.strip().isdigit()]
    rank = {pid: i for i, pid in enumerate(ids)}
    for p in res.photos:
        p.position = rank.get(p.id, len(ids) + p.position)
    _renumber(res)
    db.commit()
    db.refresh(res)
    if _wants_json(request):
        return _photo_json(res)
    return redirect(f"/resources/{res.id}/edit#fotos")


@app.post("/resources/{rid:int}/photos/{pid:int}/caption", dependencies=[Depends(check_csrf)])
async def resource_photo_caption(request: Request, rid: int, pid: int, user: User = Depends(current_user),
                                 db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    photo = db.get(ResourcePhoto, pid)
    if photo is None or photo.resource_id != res.id:
        raise HTTPException(404)
    photo.caption = " ".join(str((await request.form()).get("caption", "")).split())[:300]
    db.commit()
    if _wants_json(request):
        return _photo_json(res)
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


@app.post("/resources/{rid:int}/waits/{wid:int}/delete", dependencies=[Depends(check_csrf)])
def resource_wait_delete(request: Request, rid: int, wid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    w = db.get(ResourceWait, wid)
    if w and w.resource_id == res.id and w.status in ("unconfirmed", "waiting", "offered"):
        was_offered = w.status == "offered"
        w.status = "cancelled"
        if was_offered:
            res_wait.offer_next(db, res, w.starts_at, w.ends_at)
        db.commit()
        flash(request, "Eintrag von der Warteliste genommen.")
    return redirect(f"/resources/{res.id}#warteliste")


@app.post("/resources/{rid:int}/copy", dependencies=[Depends(check_csrf)])
def resource_copy(request: Request, rid: int, user: User = Depends(res_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    clone = res_admin.copy(db, res, user)
    db.commit()
    flash(request, "Kopie angelegt (ohne Buchungen, Sperrzeiten und Freigaben) – bitte Namen anpassen und freischalten.")
    return redirect(f"/resources/{clone.id}/edit")


@app.get("/resources/{rid:int}/export.json")
def resource_export(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res, _ = _res(db, rid, user, 3)
    return Response(res_admin.export(res), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="ressource-{res.slug}.json"'})


@app.post("/resources/import", dependencies=[Depends(check_csrf)])
async def resource_import(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    f = data.get("file")
    try:
        if not isinstance(f, UploadFile):
            raise res_admin.ResImportError("Bitte eine Datei wählen.")
        res = res_admin.import_(db, await f.read(200 * 1024 * 1024), user)
    except res_admin.ResImportError as exc:
        db.rollback()
        flash(request, str(exc), "error")
        return redirect("/resources")
    db.commit()
    flash(request, "Ressource importiert. Zuständigkeit, Ablage und Freischaltung bitte prüfen.")
    return redirect(f"/resources/{res.id}/edit?neu=1")


# --- Auswertung ------------------------------------------------------------------------------

@app.get("/resources/stats")
def resource_stats(request: Request, year: int = 0, format: str = "", user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    _module_on()
    items = [r for r, lvl in rs.visible(db, user) if lvl >= 2]
    if not items:
        raise HTTPException(403, "Keine Ressourcen freigegeben.")
    year = year if 2000 <= year <= 2100 else to_local(utcnow()).year
    data = res_admin.stats(db, items, year)
    if format == "csv":
        return Response(res_admin.stats_csv(data, year), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="auswertung-ressourcen-{year}.csv"'})
    return render(request, "resource_stats.html", user, data=data, year=year, money=pay.money,
                  months=["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"])


# --- Vereine und Dauernutzer ---------------------------------------------------------------

@app.get("/resources/clubs")
def clubs_list(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    clubs = db.scalars(select(ResourceClub).order_by(ResourceClub.pending.desc(), ResourceClub.name)).all()
    tariffs = sorted({t.name for t in db.scalars(select(ResourceTariff))})
    cfg = get_settings(db)
    return render(request, "resource_clubs.html", user, clubs=clubs, billing=res_clubs.BILLING, tariffs=tariffs,
                  signup=cfg.get("res_club_signup") == "1", mailbox=cfg.get("res_club_mailbox", ""),
                  open_months={c.id: res_clubs.months_with_items(db, c) for c in clubs if c.billing == "monthly"},
                  base=links.base("resources"))


@app.post("/resources/clubs", dependencies=[Depends(check_csrf)])
async def clubs_save(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    action = data.get("action", "save")
    cid = str(data.get("id", ""))
    club = db.get(ResourceClub, int(cid)) if cid.isdigit() else None
    if action == "settings":
        set_setting(db, "res_club_signup", "1" if data.get("signup") == "1" else "0")
        mailbox = str(data.get("mailbox", "")).strip().lower()[:255]
        set_setting(db, "res_club_mailbox", mailbox if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", mailbox) else "")
        db.commit()
        flash(request, "Einstellungen gespeichert.")
        return redirect("/resources/clubs")
    if action == "delete" and club:
        db.delete(club)
        db.commit()
        flash(request, f"„{club.name}“ gelöscht. Die Buchungen bleiben erhalten.")
        return redirect("/resources/clubs")
    if action == "approve" and club:
        club.pending, club.active = False, True
        res_clubs.send_login(db, club.email)
        db.commit()
        flash(request, f"„{club.name}“ freigegeben – der Anmeldelink ist unterwegs.")
        return redirect("/resources/clubs")
    if action == "logout_all" and club:
        res_clubs.logout_everywhere(club)
        db.commit()
        flash(request, f"„{club.name}“ ist auf allen Geräten abgemeldet.")
        return redirect("/resources/clubs")
    if action == "login" and club:
        flash(request, "Anmeldelink verschickt." if res_clubs.send_login(db, club.email) else "Nicht möglich (inaktiv oder nicht freigegeben).")
        db.commit()
        return redirect("/resources/clubs")
    values, errors = res_clubs.clean(data, club)
    other = res_clubs.by_email(db, values["email"])
    if other is not None and other is not club:
        errors.append("Diese E-Mail-Adresse gehört schon zu einem anderen Verein.")
    if errors:
        for e in errors:
            flash(request, e, "error")
        return redirect("/resources/clubs")
    if club is None:
        club = ResourceClub(**values)
        db.add(club)
    else:
        if values.get("email") != club.email:
            res_clubs.logout_everywhere(club)   # neue Adresse: alte Anmeldungen gelten nicht mehr
        for k, v in values.items():
            setattr(club, k, v)
    club.tariff_name = " ".join(str(data.get("tariff_name", "")).split())[:120]
    club.billing = data.get("billing") if data.get("billing") in res_clubs.BILLING else "instant"
    club.note = str(data.get("note", "")).strip()[:5000]
    if club.active and data.get("active") != "1":
        res_clubs.logout_everywhere(club)
    club.active = data.get("active") == "1"
    db.commit()
    flash(request, f"„{club.name}“ gespeichert.")
    return redirect("/resources/clubs")


@app.post("/resources/clubs/{cid:int}/bill", dependencies=[Depends(check_csrf)])
def club_bill(request: Request, cid: int, month: str = Form(...), user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    club = db.get(ResourceClub, cid)
    if club is None:
        raise HTTPException(404)
    p = res_clubs.bill(db, club, month, user)
    db.commit()
    flash(request, f"Sammelrechnung {p.ref} über {pay.money(p.amount_cents)} verschickt." if p else "Für diesen Monat ist nichts abzurechnen.",
          "ok" if p else "error")
    return redirect(f"/resources/clubs/{club.id}")


@app.get("/resources/clubs/{cid:int}")
def club_detail(request: Request, cid: int, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    club = db.get(ResourceClub, cid)
    if club is None:
        raise HTTPException(404)
    from .db import Payment
    statements = db.scalars(select(Payment).where(Payment.kind == "resource_club", Payment.subject_id == club.id)
                            .order_by(Payment.created_at.desc())).all()
    months = res_clubs.months_with_items(db, club)
    return render(request, "resource_club.html", user, club=club, upcoming=res_clubs.bookings(db, club),
                  past=res_clubs.bookings(db, club, upcoming=False), statements=statements, months=months,
                  items={m: res_clubs.open_items(db, club, m) for m in months}, billing=res_clubs.BILLING,
                  statuses=rs.STATUSES, when=rs.when_text, money=pay.money, pay_statuses=pay.STATUSES)


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
    f = {k: request.query_params.get(k, "").strip()[:100] for k in ("status", "resource", "q", "when", "from", "to", "club", "pay")}
    q = select(ResourceBooking).where(ResourceBooking.resource_id.in_(list(items)))
    if f["resource"].isdigit():
        q = q.where(ResourceBooking.resource_id == int(f["resource"]))
    if f["club"].isdigit():
        q = q.where(ResourceBooking.club_id == int(f["club"]))
    if f["status"] in rs.STATUSES:
        q = q.where(ResourceBooking.status == f["status"])
    elif f["status"] != "all":
        q = q.where(ResourceBooking.status.in_(rs.ACTIVE))
    d1, d2 = rs._date(f["from"]), rs._date(f["to"])
    if d1 or d2:
        if d1:
            q = q.where(ResourceBooking.ends_at > rs._utc(datetime.combine(d1, datetime.min.time())))
        if d2:
            q = q.where(ResourceBooking.starts_at < rs._utc(datetime.combine(d2 + timedelta(days=1), datetime.min.time())))
    elif f["when"] == "past":
        q = q.where(ResourceBooking.ends_at <= utcnow())
    elif f["when"] != "all":
        q = q.where(ResourceBooking.ends_at > utcnow() - timedelta(days=1))
    if f["q"]:
        like = f"%{f['q']}%"
        q = q.where(or_(ResourceBooking.ref.ilike(like), ResourceBooking.name.ilike(like), ResourceBooking.email.ilike(like),
                        ResourceBooking.title.ilike(like), ResourceBooking.organizer.ilike(like)))
    newest_first = f["when"] == "past"
    rows = db.scalars(q.order_by(ResourceBooking.starts_at.desc() if newest_first else ResourceBooking.starts_at)
                      .limit(5000 if request.query_params.get("format") == "csv" else 500)).all()
    if f["pay"] in ("open", "paid"):
        states = ("open", "pending") if f["pay"] == "open" else ("paid", "partially_refunded", "refunded")
        rows = [b for b in rows if b.payment is not None and b.payment.status in states]
    if request.query_params.get("format") == "csv":
        contact = {rid: lvl >= 2 for rid, (_, lvl) in items.items()}
        stamp = to_local(utcnow()).strftime("%Y-%m-%d")
        return Response(res_admin.bookings_csv(rows, contact), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="buchungen-{stamp}.csv"'})
    clubs = db.scalars(select(ResourceClub).order_by(ResourceClub.name)).all()
    return render(request, "resource_bookings.html", user, rows=rows, items=items, f=f, statuses=rs.STATUSES,
                  when=rs.when_text, unit_label=rs.unit_label, unit_ids=rs.unit_ids, money=pay.money,
                  pay_statuses=pay.STATUSES, clubs=clubs, query=request.url.query)


@app.post("/resources/bookings/bulk", dependencies=[Depends(check_csrf)])
async def bookings_bulk(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Mehrere Anfragen auf einmal bestätigen oder ablehnen."""
    _module_on()
    data = await request.form()
    action = data.get("action")
    done, failed = 0, 0
    for raw in data.getlist("ids")[:200]:
        b = db.get(ResourceBooking, int(raw)) if str(raw).isdigit() else None
        if b is None or rs.level(db, user, b.resource) < 3 or action not in ("accept", "reject"):
            failed += 1
            continue
        if rs.decide(db, b, user, action == "accept", str(data.get("message", ""))):
            done += 1
        else:
            failed += 1
    db.commit()
    flash(request, f"{done} Anfrage(n) {'bestätigt' if action == 'accept' else 'abgelehnt'}."
          + (f" {failed} nicht möglich (schon entschieden, belegt oder keine Berechtigung)." if failed else ""),
          "error" if failed and not done else "ok")
    return redirect("/resources/bookings" + (f"?{data.get('back')}" if data.get("back") else ""))


# --- Wochenplaner über alle Ressourcen -----------------------------------------------------

@app.get("/resources/planner")
def planner(request: Request, start: str = "", category: str = "", user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    _module_on()
    items = [(r, lvl) for r, lvl in rs.visible(db, user) if r.active or lvl >= 3]
    if not items:
        raise HTTPException(403, "Keine Ressourcen freigegeben.")
    categories = sorted({r.category for r, _ in items if r.category})
    if category:
        items = [(r, lvl) for r, lvl in items if r.category == category]
    first = rs._date(start) or to_local(utcnow()).date()
    first -= timedelta(days=first.weekday())
    days = [first + timedelta(days=i) for i in range(7)]
    s, e = rs._utc(datetime.combine(days[0], datetime.min.time())), rs._utc(datetime.combine(days[-1] + timedelta(days=1), datetime.min.time()))
    rows = db.scalars(select(ResourceBooking).where(
        ResourceBooking.resource_id.in_([r.id for r, _ in items] or [-1]), ResourceBooking.status.in_(rs.ACTIVE),
        ResourceBooking.starts_at < e, ResourceBooking.ends_at > s).order_by(ResourceBooking.starts_at)).all()
    closures = db.scalars(select(ResourceClosure).where(ResourceClosure.resource_id.in_([r.id for r, _ in items] or [-1]),
                                                        ResourceClosure.starts_at < e, ResourceClosure.ends_at > s)).all()
    grid: dict = {}
    for b in rows:
        bs, be = to_local(b.starts_at).date(), (to_local(b.ends_at) - timedelta(seconds=1)).date()
        for d in days:
            if bs <= d <= be:
                grid.setdefault((b.resource_id, d), []).append(b)
    closed = {}
    for c in closures:
        cs, ce = to_local(c.starts_at).date(), (to_local(c.ends_at) - timedelta(seconds=1)).date()
        for d in days:
            if cs <= d <= ce:
                closed[(c.resource_id, d)] = c.reason or "gesperrt"
    return render(request, "resource_planner.html", user, items=items, days=days, grid=grid, closed=closed,
                  statuses=rs.STATUSES, categories=categories, category=category, today=to_local(utcnow()).date(),
                  prev=(first - timedelta(days=7)).isoformat(), next=(first + timedelta(days=7)).isoformat(),
                  unit_label=rs.unit_label, unit_ids=rs.unit_ids)


@app.post("/resources/bookings/{bid:int}/move", dependencies=[Depends(check_csrf)])
async def booking_move(request: Request, bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Verschieben per Drag & Drop im Planer: auf einen anderen Tag und/oder eine andere Ressource."""
    b, _ = _booking(db, bid, user, 3)
    data = await request.form()
    target = rs._date(data.get("date"))
    rid = str(data.get("resource", ""))
    res = db.get(Resource, int(rid)) if rid.isdigit() else b.resource
    if target is None or res is None or rs.level(db, user, res) < 3:
        return JSONResponse({"ok": False, "error": "Ziel ungültig oder keine Berechtigung."}, status_code=400)
    if b.status not in rs.ACTIVE:
        return JSONResponse({"ok": False, "error": "Nur offene und bestätigte Buchungen lassen sich verschieben."}, status_code=400)
    shift = (target - to_local(b.starts_at).date()).days
    q_data = _transfer(rs.form_data_of(b, shift), b, res)
    q = rs.quote(db, res, q_data, staff=True, exclude_id=b.id)
    if not q["ok"]:
        return JSONResponse({"ok": False, "error": " ".join(q["errors"]) or "Nicht möglich."}, status_code=409)
    keep_price = data.get("keep_price") == "1"
    info = rs.change(db, b, res, q, user, price_cents=b.total_cents if keep_price else None,
                     notify_person=data.get("notify", "1") == "1", reason=str(data.get("reason", "")).strip()[:500])
    db.commit()
    return JSONResponse({"ok": True, "when": rs.when_text(b), "info": info})


def _transfer(data: "rs.FormData", b: ResourceBooking, res: Resource) -> "rs.FormData":
    """Eingaben auf eine andere Ressource übertragen: Tarif und Zusatzleistungen über den Namen, Räume entfallen."""
    if res.id == b.resource_id:
        return data
    data["units"] = []
    tariff = next((t for t in res.tariffs if t.name == b.tariff_name), None)
    data["tariff"] = str(tariff.id) if tariff else ""
    for key in [k for k in data if k.startswith("extra_")]:
        del data[key]
    names = {x["name"]: x.get("qty", 1) for x in rs.extras_of(b)}
    for x in res.extras:
        if x.name in names:
            data[f"extra_{x.id}"] = str(names[x.name])
    if data.get("mode") not in rs.modes(res):
        target = data.get("date") or data.get("date_from") or to_local(b.starts_at).date().isoformat()
        data["mode"] = "day" if "day" in rs.modes(res) else rs.modes(res)[0]
        data.update(date_from=target, date_to=target, date=target)
    return data


@app.get("/resources/bookings/{bid:int}/edit")
def booking_edit(request: Request, bid: int, resource: int = 0, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 3)
    res = db.get(Resource, resource) if resource else b.resource
    if res is None or rs.level(db, user, res) < 3:
        raise HTTPException(404)
    from .routes_resources_public import booking_ctx
    draft = _transfer(rs.form_data_of(b), b, res)
    draft.update(name=b.name, email=b.email, phone=b.phone, street=b.street, zip=b.zip, city=b.city)
    targets = [r for r, lvl in rs.visible(db, user) if lvl >= 3]
    return render(request, "resource_booking_edit.html", user, **booking_ctx(db, res), staff=True, edit=b, draft=draft,
                  targets=targets, when=rs.when_text, statuses=rs.STATUSES)


@app.post("/resources/bookings/{bid:int}/edit", dependencies=[Depends(check_csrf)])
async def booking_edit_save(request: Request, bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 3)
    data = await request.form()
    rid = str(data.get("resource_id", ""))
    res = db.get(Resource, int(rid)) if rid.isdigit() else b.resource
    if res is None or rs.level(db, user, res) < 3:
        raise HTTPException(403)
    if b.status not in rs.ACTIVE:
        flash(request, "Nur offene und bestätigte Buchungen lassen sich ändern.", "error")
        return redirect(f"/resources/bookings/{b.id}")
    q = rs.quote(db, res, data, staff=True, exclude_id=b.id)
    contact, errors = rs.contact_from(data)
    errors = [e for e in errors if "E-Mail" not in e or str(data.get("email", "")).strip()]
    if not contact["email"]:
        contact["email"] = ""
    if errors or not q["ok"]:
        for e in errors + q["errors"]:
            flash(request, e, "error")
        return redirect(f"/resources/bookings/{b.id}/edit?resource={res.id}")
    price = pay.parse_amount(data.get("price", "")) if str(data.get("price", "")).strip() else None
    info = rs.change(db, b, res, q, user, contact=contact, price_cents=price, notify_person=data.get("notify") == "1",
                     reason=str(data.get("reason", "")).strip()[:1000])
    db.commit()
    flash(request, "Buchung geändert. " + info)
    return redirect(f"/resources/bookings/{b.id}")


@app.get("/resources/bookings/{bid:int}")
def booking_detail(request: Request, bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b, lvl = _booking(db, bid, user, 1)
    res = b.resource
    items = fm.questions(rs.fields(res))
    answers = rs.answers_of(b)
    series = db.scalars(select(ResourceBooking).where(ResourceBooking.series_id == b.series_id,
                                                      ResourceBooking.id != b.id).order_by(ResourceBooking.starts_at)).all() if b.series_id else []
    group = [m for m in rs.group_members(db, b) if m.id != b.id] if b.group_ref else []
    extra_payments = [p for p in rs.payments_of(db, b) if p.id not in (b.payment_id, b.deposit_payment_id)]
    return render(request, "resource_booking.html", user, b=b, res=res, level=lvl, statuses=rs.STATUSES, when=rs.when_text,
                  units=rs.unit_label(res, rs.unit_ids(b)), lines=rs.lines_of(b), extras=rs.extras_of(b), money=pay.money,
                  questions=items, answers=answers, display=fm.display, handover=rs.handover(b), series=series,
                  group=group, extra_payments=extra_payments, billing=b.billing, deposit_box=pay.box(db, user, b.deposit_payment, f"/resources/bookings/{b.id}"),
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
    info = rs.record_handover(db, b, user.name, part, data)
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


# --- Darstellung: Farben je Art (Karte und Katalog) -------------------------------------------

@app.get("/resources/darstellung")
def resources_look(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    from . import res_view
    cats = sorted({r.category for r in db.scalars(select(Resource)) if r.category})
    try:
        chosen = json.loads(get_settings(db).get("res_category_colors") or "{}")
    except ValueError:
        chosen = {}
    return render(request, "resource_look.html", user, cats=cats, colors=res_view.category_colors(db, cats), chosen=chosen)


@app.post("/resources/darstellung", dependencies=[Depends(check_csrf)])
async def resources_look_save(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    from . import res_view
    data = await request.form()
    out = {}
    if data.get("action") != "reset":
        for key in data.keys():
            if key.startswith("c_"):
                cat, color = key[2:][:80], str(data.get(key) or "")
                if res_view.COLOR_RE.match(color) and data.get("auto_" + key[2:]) != "1":
                    out[cat] = color
    set_setting(db, "res_category_colors", json.dumps(out, ensure_ascii=False))
    db.commit()
    flash(request, "Farben gespeichert." if data.get("action") != "reset" else "Alle Farben wieder automatisch.")
    return redirect("/resources/darstellung")
