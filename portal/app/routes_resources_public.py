"""Ressourcenbuchung – öffentlich: Katalog mit Karte und Verfügbarkeitssuche, Buchen, Buchung verwalten,
geteilte Belegungskalender (iCal, Web, einbettbar)."""

import json
from datetime import datetime, time, timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import forms as fm, payments as pay, resources as rs
from .config import settings
from .db import Resource, ResourceBooking, ResourceCalendar, ResourcePhoto, to_local, utcnow
from .main import app, check_csrf, enabled_modules, flash, get_db, rate_limit, redirect, render, session_user
from .routes_resources import _range, files_dir


def _module_on() -> None:
    if "resources" not in enabled_modules():
        raise HTTPException(404, "Die Ressourcenbuchung ist auf diesem Server nicht eingeschaltet.")


def _public_res(db, slug: str) -> Resource:
    _module_on()
    res = db.scalar(select(Resource).where(Resource.slug == slug))
    if res is None or not res.active or not res.public:
        raise HTTPException(404, "Diese Ressource gibt es nicht oder sie ist nicht buchbar.")
    return res


def booking_ctx(db, res: Resource) -> dict:
    return {"res": res, "modes": rs.MODES, "res_modes": rs.modes(res), "blocks": rs.blocks(res), "hours": rs.hours(res),
            "extra_per": rs.EXTRA_PER, "money": pay.money, "items": rs.fields(res), "values": {}, "errors": {},
            "other": {}, "cancel_rules": rs.cancel_rules_text(res),
            "today": to_local(utcnow()).date().isoformat(),
            "min_date": (to_local(utcnow()) + timedelta(hours=res.min_notice_hours or 0)).date().isoformat(),
            "max_date": (to_local(utcnow()) + timedelta(days=res.max_advance_days or 365)).date().isoformat()}


def _price_from(res: Resource) -> int:
    values = [v for v in (res.price_day, res.price_block, res.price_hour) if v]
    values += [v for u in res.parts for v in (u.price_day, u.price_block, u.price_hour) if v]
    return min(values) if values else 0


# --- Katalog -------------------------------------------------------------------------------

@app.get("/r")
def catalog(request: Request, db: Session = Depends(get_db)):
    _module_on()
    f = {k: request.query_params.get(k, "").strip()[:100] for k in ("q", "category", "date", "persons")}
    rows = db.scalars(select(Resource).where(Resource.active.is_(True), Resource.public.is_(True))
                      .order_by(Resource.position, Resource.name)).all()
    if f["category"]:
        rows = [r for r in rows if r.category == f["category"]]
    for word in f["q"].lower().split():
        rows = [r for r in rows if word in f"{r.name} {r.location} {r.description} {r.category}".lower()]
    if f["persons"].isdigit():
        rows = [r for r in rows if not r.capacity or r.capacity >= int(f["persons"]) or any(u.capacity >= int(f["persons"]) for u in r.parts)]
    free = {}
    day = rs._date(f["date"])
    if day:
        start, end = rs._utc(datetime.combine(day, time())), rs._utc(datetime.combine(day + timedelta(days=1), time()))
        for r in rows:
            busy = rs.conflicts(db, r, None, start, end)
            if not busy:
                free[r.id] = "frei"
            elif r.parts and any(not rs.conflicts(db, r, {u.id}, start, end) for u in r.parts):
                free[r.id] = "teilweise frei"
            elif "hour" in rs.modes(r) or "block" in rs.modes(r):
                free[r.id] = "teilweise belegt"
            else:
                free[r.id] = "belegt"
    categories = sorted({r.category for r in db.scalars(select(Resource).where(Resource.active.is_(True), Resource.public.is_(True))) if r.category})
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                 "properties": {"name": r.name, "url": f"/r/{r.slug}"}} for r in rows if r.lat is not None and r.lon is not None]
    geo_bundle = None
    if features:
        from .routes_maps import map_bundle
        geo_bundle = map_bundle(db, request, None, None, "forms")
    embed = request.url.path.startswith("/r-embed")
    return render(request, "res_catalog.html", None if embed else session_user(request, db), rows=rows, f=f, free=free,
                  categories=categories, features=features, geo_bundle=geo_bundle, price_from=_price_from, money=pay.money,
                  embed=embed)


app.add_api_route("/r-embed", catalog, methods=["GET"], include_in_schema=False)


@app.get("/r/{slug}")
def resource_public(request: Request, slug: str, db: Session = Depends(get_db)):
    res = _public_res(db, slug)
    return render(request, "res_public.html", session_user(request, db), **booking_ctx(db, res), staff=False)


@app.get("/r/{slug}/photo/{pid:int}")
def resource_photo(slug: str, pid: int, db: Session = Depends(get_db)):
    _module_on()
    res = db.scalar(select(Resource).where(Resource.slug == slug))
    photo = db.get(ResourcePhoto, pid)
    if res is None or photo is None or photo.resource_id != res.id:
        raise HTTPException(404)
    return FileResponse(files_dir(res.id) / photo.file, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/r/{slug}/nutzungsordnung.pdf")
def resource_terms(slug: str, db: Session = Depends(get_db)):
    res = _public_res(db, slug)
    if not res.terms_file:
        raise HTTPException(404)
    return FileResponse(files_dir(res.id) / res.terms_file, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="Nutzungsordnung-{res.slug}.pdf"'})


@app.get("/r/{slug}/busy.json")
def resource_busy(slug: str, start: str = "", end: str = "", db: Session = Depends(get_db)):
    res = _public_res(db, slug)
    s, e = _range(start, end)
    return JSONResponse(rs.fc_events(rs.calendar_events(db, [res], s, e, "busy", True)), headers={"Cache-Control": "no-store"})


@app.post("/r/{slug}/quote", dependencies=[Depends(check_csrf)])
async def resource_quote(request: Request, slug: str, db: Session = Depends(get_db)):
    rate_limit(request, "res-quote", limit=120, window=60)
    _module_on()
    user = session_user(request, db)
    res = db.scalar(select(Resource).where(Resource.slug == slug))
    staff = res is not None and request.query_params.get("staff") == "1" and user is not None and rs.level(db, user, res) >= 3
    if not staff:
        res = _public_res(db, slug)
    return JSONResponse(rs.quote_json(rs.quote(db, res, await request.form(), staff=staff)))


@app.post("/r/{slug}/book", dependencies=[Depends(check_csrf)])
async def resource_book(request: Request, slug: str, db: Session = Depends(get_db)):
    res = _public_res(db, slug)
    rate_limit(request, "res-book", limit=10, window=600)
    data = await request.form()
    if data.get("website"):           # Honigtopf
        raise HTTPException(400)
    contact, errors = rs.contact_from(data)
    q = rs.quote(db, res, data)
    errors += q["errors"]
    items = rs.fields(res)
    files = {k: [f for f in data.getlist(k) if getattr(f, "filename", "")] for k in data.keys() if k.startswith("q_")}
    answers, field_errors, uploads = fm.validate(items, data, files)
    tariff = q["tariff"]
    proof = [f for f in data.getlist("proof") if getattr(f, "filename", "")]
    if tariff and tariff.needs_proof and not proof:
        errors.append(f"Für den Tarif „{tariff.name}“ bitte einen Nachweis hochladen.")
    if (res.terms_text or res.terms_file) and data.get("terms") != "1":
        errors.append("Bitte die Nutzungsbedingungen bestätigen.")
    if errors or field_errors:
        for e in errors:
            flash(request, e, "error")
        if field_errors:
            flash(request, "Bitte die markierten Angaben prüfen.", "error")
        ctx = booking_ctx(db, res)
        ctx.update(values=fm_values(items, data), errors=field_errors, draft=data)
        return render(request, "res_public.html", session_user(request, db), **ctx, staff=False)
    b = rs.create(db, res, q, contact, answers)
    target = settings.data_dir / "resources" / "bookings" / str(b.id)
    stored = {}
    if uploads:
        from .workflow import _store
        stored = await _store(target, uploads)
    if proof:
        from .workflow import _store
        stored.update(await _store(target, {"proof": proof[:3]}))
    if stored:
        b.answers_json = json.dumps({**answers, **stored}, ensure_ascii=False)
    rs.send_confirm_mail(db, b)
    db.commit()
    request.session.setdefault("res_tokens", []).append(b.token)
    return redirect(f"/r/b/{b.token}?neu=1")


def fm_values(items, data) -> dict:
    out = {}
    for item in fm.questions(items):
        name = f"q_{item['id']}"
        vals = data.getlist(name)
        out[item["id"]] = vals if item["type"] == "checkbox" else (vals[0] if vals else "")
    return out


# --- Buchung verwalten (buchende Person) ----------------------------------------------------

def _by_token(db, token: str) -> ResourceBooking:
    _module_on()
    b = db.scalar(select(ResourceBooking).where(ResourceBooking.token == token)) if token else None
    if b is None:
        raise HTTPException(404, "Diese Buchung gibt es nicht (mehr).")
    return b


@app.get("/r/b/{token}")
def booking_manage(request: Request, token: str, db: Session = Depends(get_db)):
    b = _by_token(db, token)
    res = b.resource
    return render(request, "res_manage.html", session_user(request, db), b=b, res=res, statuses=rs.STATUSES,
                  when=rs.when_text(b), units=rs.unit_label(res, rs.unit_ids(b)), lines=rs.lines_of(b), money=pay.money,
                  can_cancel=rs.can_self_cancel(b), fee=rs.cancel_fee(b), rules=rs.cancel_rules_text(res),
                  fresh=request.query_params.get("neu") == "1", pay_statuses=pay.STATUSES)


@app.get("/r/b/{token}/confirm/{code}")
def booking_confirm(request: Request, token: str, code: str, db: Session = Depends(get_db)):
    import secrets as _s
    b = _by_token(db, token)
    if not _s.compare_digest(b.confirm_code or "", code):
        raise HTTPException(404, "Dieser Bestätigungslink ist nicht gültig.")
    before = b.status
    status = rs.confirm_email(db, b)
    db.commit()
    if before == "unconfirmed":
        flash(request, {"confirmed": "Danke – Ihre Buchung ist bestätigt." + (" Bitte jetzt bezahlen." if b.payment else ""),
                        "requested": "Danke – Ihre E-Mail-Adresse ist bestätigt. Die Verwaltung prüft Ihre Anfrage.",
                        "expired": "Leider ist der Zeitraum inzwischen vergeben."}.get(status, "Bestätigt."),
              "error" if status == "expired" else "ok")
    return redirect(f"/r/b/{token}")


@app.post("/r/b/{token}/cancel", dependencies=[Depends(check_csrf)])
def booking_cancel_public(request: Request, token: str, db: Session = Depends(get_db)):
    b = _by_token(db, token)
    if not rs.can_self_cancel(b):
        raise HTTPException(403, "Eine Stornierung ist hier nicht (mehr) möglich – bitte wenden Sie sich an die Verwaltung.")
    info = rs.cancel(db, b, b.name or "buchende Person", "durch die buchende Person")
    db.commit()
    flash(request, "Ihre Buchung ist storniert. " + info)
    return redirect(f"/r/b/{token}")


@app.get("/r/b/{token}/pdf")
def booking_pdf_public(token: str, db: Session = Depends(get_db)):
    b = _by_token(db, token)
    if b.status == "unconfirmed":
        raise HTTPException(403, "Bitte zuerst die E-Mail-Adresse bestätigen.")
    return Response(rs.confirmation_pdf(db, b), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Buchung-{b.ref}.pdf"'})


# --- Geteilte Kalender -----------------------------------------------------------------------

def _calendar(db, token: str) -> tuple[ResourceCalendar, list[Resource]]:
    _module_on()
    token = token.removesuffix(".ics").removesuffix(".json")
    cal = db.scalar(select(ResourceCalendar).where(ResourceCalendar.token == token)) if token else None
    if cal is None:
        raise HTTPException(404, "Dieser Kalender-Link ist nicht (mehr) gültig.")
    ids = [int(x) for x in cal.resource_ids.split(",") if x.isdigit()]
    resources = db.scalars(select(Resource).where(Resource.id.in_(ids or [-1]))).all()
    cal.last_access_at = utcnow()
    cal.access_count = (cal.access_count or 0) + 1
    db.commit()
    return cal, resources


@app.get("/r/cal/{token}.ics")
def calendar_ics(token: str, db: Session = Depends(get_db)):
    cal, resources = _calendar(db, token)
    events = rs.calendar_events(db, resources, utcnow() - timedelta(days=90), utcnow() + timedelta(days=730), cal.level, cal.tentative)
    return Response(rs.ics(events, cal.name), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="belegung-{cal.id}.ics"', "Cache-Control": "no-store"})


@app.get("/r/cal/{token}.json")
def calendar_json(token: str, start: str = "", end: str = "", db: Session = Depends(get_db)):
    cal, resources = _calendar(db, token)
    s, e = _range(start, end)
    return JSONResponse(rs.fc_events(rs.calendar_events(db, resources, s, e, cal.level, cal.tentative)),
                        headers={"Cache-Control": "no-store"})


@app.get("/r/cal/{token}")
def calendar_web(request: Request, token: str, db: Session = Depends(get_db)):
    cal, resources = _calendar(db, token)
    embed = request.url.path.startswith("/r-embed")
    if embed and not cal.embed:
        raise HTTPException(404, "Dieser Kalender darf nicht eingebettet werden.")
    return render(request, "res_calendar.html", None if embed else session_user(request, db), cal=cal,
                  resources=resources, embed=embed, base=settings.portal_base_url)


app.add_api_route("/r-embed/cal/{token}", calendar_web, methods=["GET"], include_in_schema=False)
