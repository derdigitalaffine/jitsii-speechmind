"""Ressourcenbuchung – öffentlich: Katalog mit Karte und Verfügbarkeitssuche, Buchen (auch mehrere Ressourcen in
einer Buchung über die Merkliste), Warteliste, Vereinszugang, Buchung verwalten, geteilte Belegungskalender."""

import json
import secrets
from datetime import datetime, time, timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import forms as fm, links, notify, payments as pay, res_clubs, res_wait, resources as rs
from .config import settings
from .db import (
    Resource, ResourceBooking, ResourceCalendar, ResourceClub, ResourcePhoto, ResourceWait, User, get_settings,
    to_local, utcnow,
)
from .main import app, check_csrf, enabled_modules, flash, get_db, rate_limit, redirect, render, session_user
from .routes_resources import _range, files_dir

CART = "res_cart"   # Sitzung: {"group": …, "contact": {…}} solange eine Sammelbuchung zusammengestellt wird


def _module_on() -> None:
    if "resources" not in enabled_modules():
        raise HTTPException(404, "Die Ressourcenbuchung ist auf diesem Server nicht eingeschaltet.")


def _public_res(db, slug: str) -> Resource:
    _module_on()
    res = db.scalar(select(Resource).where(Resource.slug == slug))
    if res is None or not res.active or not res.public:
        raise HTTPException(404, "Diese Ressource gibt es nicht oder sie ist nicht buchbar.")
    return res


def _cart(request, db) -> list[ResourceBooking]:
    """Vorgemerkte Teile der Sammelbuchung, die gerade zusammengestellt wird."""
    group = (request.session.get(CART) or {}).get("group")
    if not group:
        return []
    rows = db.scalars(select(ResourceBooking).where(ResourceBooking.group_ref == group,
                                                    ResourceBooking.status == "unconfirmed").order_by(ResourceBooking.id)).all()
    if not rows:
        request.session.pop(CART, None)
    return list(rows)


def booking_ctx(db, res: Resource, request=None, club=None) -> dict:
    cart = _cart(request, db) if request is not None else []
    return {"res": res, "modes": rs.MODES, "res_modes": rs.modes(res), "blocks": rs.blocks(res), "hours": rs.hours(res),
            "extra_per": rs.EXTRA_PER, "money": pay.money, "items": rs.fields(res), "values": {}, "errors": {},
            "other": {}, "cancel_rules": rs.cancel_rules_text(res), "club": club, "cart": cart,
            "club_tariff": next((t for t in res.tariffs if club and club.tariff_name
                                 and t.name.strip().lower() == club.tariff_name.strip().lower()), None),
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
                  embed=embed, cart=[] if embed else _cart(request, db), club=None if embed else res_clubs.current(request, db),
                  signup=get_settings(db).get("res_club_signup") == "1")


app.add_api_route("/r-embed", catalog, methods=["GET"], include_in_schema=False)


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


@app.get("/r/{slug}/day.json")
def resource_day(request: Request, slug: str, date: str = "", wait: str = "", db: Session = Depends(get_db)):
    """Freie Zeiten eines Tages (zum Antippen im Buchungsformular)."""
    rate_limit(request, "res-day", limit=240, window=60)
    user = session_user(request, db)
    _module_on()
    res = db.scalar(select(Resource).where(Resource.slug == slug))
    if res is None or not (res.active and res.public or user is not None and rs.level(db, user, res) >= 3):
        raise HTTPException(404)
    day = rs._date(date)
    if day is None:
        raise HTTPException(400)
    known = {u.id for u in res.parts}
    ids = {int(x) for x in request.query_params.getlist("units") if x.isdigit() and int(x) in known} or None
    if ids is not None and len(ids) == len(known):
        ids = None
    return JSONResponse(rs.day_free(db, res, day, ids, wait), headers={"Cache-Control": "no-store"})


@app.post("/r/{slug}/quote", dependencies=[Depends(check_csrf)])
async def resource_quote(request: Request, slug: str, db: Session = Depends(get_db)):
    rate_limit(request, "res-quote", limit=120, window=60)
    _module_on()
    user = session_user(request, db)
    res = db.scalar(select(Resource).where(Resource.slug == slug))
    staff = res is not None and request.query_params.get("staff") == "1" and user is not None and rs.level(db, user, res) >= 3
    if not staff:
        res = _public_res(db, slug)
    data = await request.form()
    exclude = request.query_params.get("exclude", "")
    q = rs.quote(db, res, data, staff=staff, exclude_id=int(exclude) if staff and exclude.isdigit() else None,
                 club=None if staff else res_clubs.current(request, db), wait_token=str(data.get("wait_token", "")))
    out = rs.quote_json(q)
    out["waitlist"] = bool(not staff and res.waitlist and q["busy"])
    return JSONResponse(out)


def fm_values(items, data) -> dict:
    out = {}
    for item in fm.questions(items):
        name = f"q_{item['id']}"
        vals = data.getlist(name)
        out[item["id"]] = vals if item["type"] == "checkbox" else (vals[0] if vals else "")
    return out


def _wait_of(db, token: str, res: Resource) -> ResourceWait | None:
    w = db.scalar(select(ResourceWait).where(ResourceWait.token == token)) if token else None
    if w is None or w.resource_id != res.id or w.status != "offered" or not w.offer_until or w.offer_until < utcnow():
        return None
    return w


@app.post("/r/{slug}/book", dependencies=[Depends(check_csrf)])
async def resource_book(request: Request, slug: str, db: Session = Depends(get_db)):
    res = _public_res(db, slug)
    rate_limit(request, "res-book", limit=20, window=600)
    data = await request.form()
    if data.get("website"):           # Honigtopf
        raise HTTPException(400)
    club = res_clubs.current(request, db)
    wait = _wait_of(db, str(data.get("wait_token", "")), res)
    if club is not None:
        contact = {**res_clubs.contact(club), "title": " ".join(str(data.get("title", "")).split())[:255]}
        persons = str(data.get("persons", "") or "0")
        contact["persons"] = int(persons) if persons.isdigit() else 0
        errors = [] if contact["title"] else ["Bitte den Anlass angeben."]
    else:
        contact, errors = rs.contact_from(data)
    q = rs.quote(db, res, data, club=club, wait_token=wait.token if wait else "")
    errors += q["errors"]
    if data.get("action") == "wait":
        return _join_waitlist(request, db, res, q, data, contact, errors, club)
    items = rs.fields(res)
    files = {k: [f for f in data.getlist(k) if getattr(f, "filename", "")] for k in data.keys() if k.startswith("q_")}
    answers, field_errors, uploads = fm.validate(items, data, files)
    tariff = q["tariff"]
    proof = [f for f in data.getlist("proof") if getattr(f, "filename", "")]
    if tariff and tariff.needs_proof and not proof and club is None:
        errors.append(f"Für den Tarif „{tariff.name}“ bitte einen Nachweis hochladen.")
    if (res.terms_text or res.terms_file) and data.get("terms") != "1":
        errors.append("Bitte die Nutzungsbedingungen bestätigen.")
    if errors or field_errors:
        for e in errors:
            flash(request, e, "error")
        if field_errors:
            flash(request, "Bitte die markierten Angaben prüfen.", "error")
        ctx = booking_ctx(db, res, request, club)
        ctx.update(values=fm_values(items, data), errors=field_errors, draft=data, wait=wait)
        return render(request, "res_public.html", session_user(request, db), **ctx, staff=False)
    cart = request.session.get(CART) or {}
    more = data.get("action") == "add"
    group = cart.get("group") if _cart(request, db) else ""
    if more and not group:
        group = "S" + secrets.token_hex(5).upper()
    b = rs.create(db, res, q, contact, answers, group_ref=group, club=club)
    target = settings.data_dir / "resources" / "bookings" / str(b.id)
    stored = {}
    if uploads or proof:
        from .workflow import _store
        stored = await _store(target, uploads) if uploads else {}
        if proof:
            stored.update(await _store(target, {"proof": proof[:3]}))
    if stored:
        b.answers_json = json.dumps({**answers, **stored}, ensure_ascii=False)
    if wait is not None:
        res_wait.booked(db, wait, b)
    if more:
        request.session[CART] = {"group": group, "contact": {k: contact.get(k, "") for k in
                                                             ("name", "email", "phone", "street", "zip", "city", "title",
                                                              "organizer")} | {"persons": str(contact.get("persons") or "")}}
        db.commit()
        flash(request, f"{res.name} ist vorgemerkt. Wählen Sie jetzt die nächste Ressource – Ihre Angaben werden übernommen.")
        return redirect("/r?merkliste=1")
    request.session.pop(CART, None)
    _send_or_confirm(db, b, club, wait)
    db.commit()
    request.session.setdefault("res_tokens", []).append(b.token)
    return redirect(f"/r/b/{b.token}?neu=1")


def _send_or_confirm(db, b: ResourceBooking, club, wait) -> None:
    """Vereine (über den Anmeldelink bestätigt) und Angebote aus der Warteliste (Adresse schon bestätigt) brauchen
    keine Bestätigungsmail; alle anderen bekommen eine – bei einer Sammelbuchung eine für alle Teile."""
    if club is not None or (wait is not None and wait.email == b.email):
        rs.confirm_email(db, b)
    else:
        rs._mail_many(db, rs.group_members(db, b), "res_confirm_email")


def _join_waitlist(request, db, res, q, data, contact, errors, club):
    blocking = [e for e in errors if not e.startswith(("Belegt", "Vorgemerkt"))]
    if not res.waitlist or not q["start"] or not q["busy"] or blocking:
        for e in blocking or ["Für diesen Zeitraum ist keine Warteliste möglich."]:
            flash(request, e, "error")
        ctx = booking_ctx(db, res, request, club)
        ctx.update(draft=data)
        return render(request, "res_public.html", session_user(request, db), **ctx, staff=False)
    w = res_wait.add(db, res, q, data, contact, club)
    db.commit()
    return redirect(f"/r/w/{w.token}?neu=1")


# --- Merkliste (mehrere Ressourcen in einer Buchung) ------------------------------------------

@app.get("/r/merkliste")
def cart_page(request: Request, db: Session = Depends(get_db)):
    _module_on()
    rows = _cart(request, db)
    return render(request, "res_cart.html", session_user(request, db), rows=rows, when=rs.when_text, money=pay.money,
                  lines=rs.lines_of, units=lambda b: rs.unit_label(b.resource, rs.unit_ids(b)),
                  club=res_clubs.current(request, db), total=sum(b.total_cents for b in rows))


@app.post("/r/merkliste", dependencies=[Depends(check_csrf)])
async def cart_action(request: Request, db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    action, token = str(data.get("action", "")), str(data.get("token", ""))
    rows = _cart(request, db)
    if action == "remove":
        for b in rows:
            if secrets.compare_digest(b.token, token):
                b.status = "cancelled"
                b.cancelled_at = utcnow()
                rs._note(b, "Aus der Merkliste entfernt.")
                rs.release(db, b)
        db.commit()
        if len(rows) <= 1:
            request.session.pop(CART, None)
        return redirect("/r/merkliste")
    if action == "send" and rows:
        request.session.pop(CART, None)
        _send_or_confirm(db, rows[0], res_clubs.current(request, db), None)
        db.commit()
        return redirect(f"/r/b/{rows[0].token}?neu=1")
    if action == "discard":
        for b in rows:
            b.status, b.cancelled_at = "cancelled", utcnow()
            rs._note(b, "Merkliste verworfen.")
            rs.release(db, b)
        request.session.pop(CART, None)
        db.commit()
        flash(request, "Merkliste verworfen.")
        return redirect("/r")
    return redirect("/r/merkliste")


# --- Warteliste --------------------------------------------------------------------------------

def _wait(db, token: str) -> ResourceWait:
    _module_on()
    w = db.scalar(select(ResourceWait).where(ResourceWait.token == token)) if token else None
    if w is None:
        raise HTTPException(404, "Diesen Eintrag auf der Warteliste gibt es nicht (mehr).")
    return w


@app.get("/r/w/{token}")
def wait_page(request: Request, token: str, db: Session = Depends(get_db)):
    w = _wait(db, token)
    res = w.resource
    offer = w.status == "offered" and w.offer_until and w.offer_until > utcnow() and res.active and res.public
    if offer:
        club = res_clubs.current(request, db)
        ctx = booking_ctx(db, res, request, club)
        draft = res_wait.data_of(w)
        draft.update(name=w.name, email=w.email)
        ctx.update(draft=draft, wait=w)
        return render(request, "res_public.html", session_user(request, db), **ctx, staff=False)
    return render(request, "res_wait.html", session_user(request, db), w=w, res=res, when=res_wait.when(w),
                  statuses=res_wait.STATUSES, position=res_wait.position(db, w) if w.status == "waiting" else 0,
                  fresh=request.query_params.get("neu") == "1")


@app.get("/r/w/{token}/confirm/{code}")
def wait_confirm(request: Request, token: str, code: str, db: Session = Depends(get_db)):
    w = _wait(db, token)
    if not secrets.compare_digest(w.confirm_code or "", code):
        raise HTTPException(404, "Dieser Bestätigungslink ist nicht gültig.")
    res_wait.confirm(db, w)
    db.commit()
    flash(request, "Danke – Sie stehen auf der Warteliste." if w.status == "waiting" else
          "Danke – der Zeitraum ist gerade frei geworden, Sie können jetzt buchen.")
    return redirect(f"/r/w/{token}")


@app.post("/r/w/{token}/cancel", dependencies=[Depends(check_csrf)])
def wait_cancel(request: Request, token: str, db: Session = Depends(get_db)):
    w = _wait(db, token)
    if w.status in ("unconfirmed", "waiting", "offered"):
        offered = w.status == "offered"
        w.status = "cancelled"
        if offered:
            res_wait.offer_next(db, w.resource, w.starts_at, w.ends_at)
        db.commit()
        flash(request, "Sie stehen nicht mehr auf der Warteliste.")
    return redirect(f"/r/w/{token}")


# --- Vereinszugang -----------------------------------------------------------------------------

@app.get("/r/login")
def club_login_page(request: Request, db: Session = Depends(get_db)):
    _module_on()
    return render(request, "res_club_login.html", session_user(request, db), club=res_clubs.current(request, db),
                  signup=get_settings(db).get("res_club_signup") == "1", sent=request.query_params.get("gesendet") == "1")


@app.post("/r/login/send", dependencies=[Depends(check_csrf)])
async def club_login_submit(request: Request, db: Session = Depends(get_db)):
    _module_on()
    rate_limit(request, "res-club-login", limit=5, window=600)
    data = await request.form()
    email = str(data.get("email", "")).strip().lower()[:255]
    rate_limit(request, "res-club-login-mail", limit=3, window=3600, key=email)
    res_clubs.send_login(db, email)
    db.commit()
    return redirect("/r/login?gesendet=1")


@app.get("/r/login/{token}")
def club_login_confirm(request: Request, token: str, db: Session = Depends(get_db)):
    """Nur Anzeige: Mail-Scanner rufen Links automatisch auf und würden den Einmal-Link sonst verbrauchen.
    Angemeldet wird erst mit dem Knopf (POST)."""
    _module_on()
    return render(request, "res_club_login.html", session_user(request, db), club=None, confirm_token=token,
                  signup=False, sent=False)


@app.post("/r/login/{token}", dependencies=[Depends(check_csrf)])
def club_login_link(request: Request, token: str, db: Session = Depends(get_db)):
    _module_on()
    rate_limit(request, "res-club-token", limit=20, window=600)
    club = res_clubs.consume(db, token)
    if club is None:
        db.rollback()
        flash(request, "Dieser Anmeldelink ist abgelaufen oder wurde schon benutzt. Bitte fordern Sie einen neuen an.", "error")
        return redirect("/r/login")
    db.commit()
    response = redirect("/r/mein")
    res_clubs.set_cookie(response, club)
    return response


@app.post("/r/logout", dependencies=[Depends(check_csrf)])
def club_logout(request: Request):
    response = redirect("/r")
    res_clubs.clear_cookie(response)
    return response


@app.get("/r/mein")
def club_home(request: Request, db: Session = Depends(get_db)):
    _module_on()
    club = res_clubs.current(request, db)
    if club is None:
        return redirect("/r/login")
    resources = db.scalars(select(Resource).where(Resource.active.is_(True), Resource.public.is_(True))
                           .order_by(Resource.position, Resource.name)).all()
    return render(request, "res_club_home.html", session_user(request, db), club=club, resources=resources,
                  upcoming=res_clubs.bookings(db, club), past=res_clubs.bookings(db, club, upcoming=False),
                  statuses=rs.STATUSES, when=rs.when_text, money=pay.money, billing=res_clubs.BILLING,
                  units=lambda b: rs.unit_label(b.resource, rs.unit_ids(b)))


@app.post("/r/mein", dependencies=[Depends(check_csrf)])
async def club_profile(request: Request, db: Session = Depends(get_db)):
    _module_on()
    club = res_clubs.current(request, db)
    if club is None:
        return redirect("/r/login")
    data = dict(await request.form())
    data["email"] = club.email   # die Adresse ändert nur die Verwaltung (sie ist der Zugang)
    data["club_name"] = club.name
    values, errors = res_clubs.clean(data, club)
    for e in errors:
        flash(request, e, "error")
    if not errors:
        for k in ("contact_name", "phone", "street", "zip", "city"):
            setattr(club, k, values[k])
        db.commit()
        flash(request, "Angaben gespeichert.")
    return redirect("/r/mein#angaben")


@app.get("/r/verein")
def club_signup_page(request: Request, db: Session = Depends(get_db)):
    _module_on()
    if get_settings(db).get("res_club_signup") != "1":
        raise HTTPException(404)
    return render(request, "res_club_signup.html", session_user(request, db), draft={})


@app.post("/r/verein", dependencies=[Depends(check_csrf)])
async def club_signup(request: Request, db: Session = Depends(get_db)):
    _module_on()
    cfg = get_settings(db)
    if cfg.get("res_club_signup") != "1":
        raise HTTPException(404)
    rate_limit(request, "res-club-signup", limit=5, window=3600)
    data = await request.form()
    if data.get("website"):
        raise HTTPException(400)
    values, errors = res_clubs.clean(data)
    if data.get("privacy") != "1":
        errors.append("Bitte der Verarbeitung Ihrer Angaben zustimmen.")
    if errors:
        for e in errors:
            flash(request, e, "error")
        return render(request, "res_club_signup.html", session_user(request, db), draft=data)
    if res_clubs.by_email(db, values["email"]) is None:
        db.add(ResourceClub(**values, pending=True, note=str(data.get("note", "")).strip()[:2000]))
        if cfg.get("res_club_mailbox"):
            notify.enqueue(db, cfg["res_club_mailbox"], f"Neue Registrierung: {values['name']}",
                           f"{values['name']} ({values['contact_name']}, {values['email']}) möchte als Verein bzw. "
                           f"Dauernutzer buchen.\n\nFreigeben: {settings.portal_base_url}/resources/clubs", "res_staff")
        db.commit()
    flash(request, "Danke! Die Verwaltung prüft Ihre Angaben. Nach der Freigabe bekommen Sie einen Anmeldelink per E-Mail.")
    return redirect("/r")


# Erst nach den festen Pfaden (/r/login, /r/mein …) registrieren, sonst fängt {slug} sie ab.
@app.get("/r/{slug}")
def resource_public(request: Request, slug: str, db: Session = Depends(get_db)):
    res = _public_res(db, slug)
    club = res_clubs.current(request, db)
    ctx = booking_ctx(db, res, request, club)
    contact = (request.session.get(CART) or {}).get("contact") or {}
    if contact and ctx["cart"]:
        ctx["draft"] = rs.FormData(contact)
    return render(request, "res_public.html", session_user(request, db), **ctx, staff=False)


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
    group = [m for m in rs.group_members(db, b) if m.id != b.id] if b.group_ref else []
    return render(request, "res_manage.html", session_user(request, db), b=b, res=res, statuses=rs.STATUSES,
                  when=rs.when_text(b), units=rs.unit_label(res, rs.unit_ids(b)), lines=rs.lines_of(b), money=pay.money,
                  can_cancel=rs.can_self_cancel(b), fee=rs.cancel_fee(b), rules=rs.cancel_rules_text(res),
                  fresh=request.query_params.get("neu") == "1", pay_statuses=pay.STATUSES, group=group,
                  when_of=rs.when_text, ics_ok=b.status == "confirmed")


@app.get("/r/b/{token}/termin.ics")
def booking_ics(token: str, db: Session = Depends(get_db)):
    """Die eigene Buchung als Kalendereintrag."""
    b = _by_token(db, token)
    if b.status != "confirmed":
        raise HTTPException(404)
    res = b.resource
    ev = {"id": f"b{b.id}", "title": f"{res.name}: {b.title}", "start": b.starts_at, "end": b.ends_at,
          "allDay": b.mode == "day", "tentative": False, "resource": res.name + (f", {res.location}" if res.location else ""),
          "units": rs.unit_label(res, rs.unit_ids(b)), "description": f"Buchung {b.ref}\n{rs.manage_link(b)}"}
    return Response(rs.ics([ev], res.name), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="buchung-{b.ref}.ics"'})


@app.get("/r/b/{token}/confirm/{code}")
def booking_confirm(request: Request, token: str, code: str, db: Session = Depends(get_db)):
    b = _by_token(db, token)
    if not secrets.compare_digest(b.confirm_code or "", code):
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
    # Der Link gilt nur, solange die anlegende Person die Ressourcen in dieser Detailstufe noch sehen darf
    creator = db.get(User, cal.created_by_id) if cal.created_by_id else None
    if creator is None or not creator.active:
        raise HTTPException(404, "Dieser Kalender-Link ist nicht (mehr) gültig.")
    need = 2 if cal.level == "full" else 1
    allowed = {r.id for r, lvl in rs.visible(db, creator) if lvl >= need}
    resources = db.scalars(select(Resource).where(Resource.id.in_([i for i in ids if i in allowed] or [-1]))).all()
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
                  resources=resources, embed=embed, base=links.base("resources"))


app.add_api_route("/r-embed/cal/{token}", calendar_web, methods=["GET"], include_in_schema=False)
