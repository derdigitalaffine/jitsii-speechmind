"""Ressourcenbuchung: Hausmeister:innen verwalten (Verwaltung) und deren persönliche Seite (Magic Link) mit
Terminliste, Übergabe und Abnahme; Freigabe der Kaution durch die Verwaltung."""

from fastapi import Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import caretakers as ck, payments as pay, resources as rs
from .db import ResourceCaretaker, User, utcnow
from .main import app, check_csrf, current_user, flash, get_db, rate_limit, redirect, render, require
from .routes_resources import _booking, _module_on, _users

res_user = require("resources")


# --- Verwaltung -----------------------------------------------------------------------------

@app.get("/resources/caretakers")
def caretakers_list(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    rows = db.scalars(select(ResourceCaretaker).order_by(ResourceCaretaker.active.desc(), ResourceCaretaker.name)).all()
    from .db import Resource
    resources = db.scalars(select(Resource).order_by(Resource.name)).all()
    return render(request, "resource_caretakers.html", user, rows=rows, users=_users(db), resources=resources)


@app.post("/resources/caretakers", dependencies=[Depends(check_csrf)])
async def caretakers_save(request: Request, user: User = Depends(res_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    action = data.get("action", "save")
    cid = str(data.get("id", ""))
    ct = db.get(ResourceCaretaker, int(cid)) if cid.isdigit() else None
    if action == "delete" and ct:
        db.delete(ct)
        db.commit()
        flash(request, f"„{ct.display_name}“ entfernt.")
        return redirect("/resources/caretakers")
    if action == "send" and ct:
        ok = ck.send_link(db, ct)
        db.commit()
        flash(request, "Persönlicher Link verschickt – frühere Links gelten nicht mehr." if ok
              else "Keine E-Mail-Adresse hinterlegt.", "ok" if ok else "error")
        return redirect("/resources/caretakers")
    if action == "lock" and ct:
        ct.token_hash = ""
        db.commit()
        flash(request, f"Alle Links von „{ct.display_name}“ sind gesperrt.")
        return redirect("/resources/caretakers")
    values, errors = ck.clean(db, data)
    if errors:
        for e in errors:
            flash(request, e, "error")
        return redirect("/resources/caretakers")
    if ct is None:
        ct = ResourceCaretaker()
        db.add(ct)
    for k, v in values.items():
        setattr(ct, k, v)
    from .db import Resource
    ids = {int(x) for x in data.getlist("resources") if str(x).isdigit()}
    ct.resources = [r for r in db.scalars(select(Resource).where(Resource.id.in_(ids)))] if ids else []
    db.commit()
    flash(request, f"„{ct.display_name}“ gespeichert.")
    return redirect("/resources/caretakers")


@app.post("/resources/bookings/{bid:int}/deposit-release", dependencies=[Depends(check_csrf)])
def booking_deposit_release(request: Request, bid: int, keep: str = Form(""), user: User = Depends(current_user),
                            db: Session = Depends(get_db)):
    b, _ = _booking(db, bid, user, 3)
    if not rs.deposit_pending(b):
        flash(request, "Hier wartet keine Kaution auf die Freigabe.", "error")
        return redirect(f"/resources/bookings/{b.id}#uebergabe")
    info = rs.release_deposit(db, b, user, pay.parse_amount(keep) if keep.strip() else None)
    db.commit()
    flash(request, "Kaution freigegeben. " + info)
    return redirect(f"/resources/bookings/{b.id}#uebergabe")


# --- Persönliche Seite der Hausmeister:innen (ohne Anmeldung) ---------------------------------

def _caretaker(request: Request, db, token: str) -> ResourceCaretaker:
    _module_on()
    rate_limit(request, "res-caretaker", limit=300, window=600)
    ct = ck.by_token(db, token)
    if ct is None:
        raise HTTPException(404, "Dieser Link ist nicht (mehr) gültig. Bitte bei der Verwaltung einen neuen anfordern.")
    ct.last_seen_at = utcnow()
    return ct


@app.get("/r/hausmeister/{token}")
def caretaker_home(request: Request, token: str, db: Session = Depends(get_db)):
    ct = _caretaker(request, db, token)
    rows = ck.bookings(db, ct)
    db.commit()
    return render(request, "res_caretaker.html", None, ct=ct, token=token, rows=rows, handover=rs.handover,
                  when=rs.when_text, now=utcnow(), money=pay.money)


@app.get("/r/hausmeister/{token}/{bid:int}")
def caretaker_booking(request: Request, token: str, bid: int, db: Session = Depends(get_db)):
    ct = _caretaker(request, db, token)
    from .db import ResourceBooking
    b = db.get(ResourceBooking, bid)
    if b is None or not ck.may_handle(ct, b):
        raise HTTPException(404, "Buchung nicht gefunden.")
    db.commit()
    return render(request, "res_caretaker_booking.html", None, ct=ct, token=token, b=b, h=rs.handover(b),
                  when=rs.when_text(b), units=rs.unit_label(b.resource, rs.unit_ids(b)), money=pay.money)


@app.post("/r/hausmeister/{token}/{bid:int}", dependencies=[Depends(check_csrf)])
async def caretaker_booking_save(request: Request, token: str, bid: int, db: Session = Depends(get_db)):
    ct = _caretaker(request, db, token)
    from .db import ResourceBooking
    b = db.get(ResourceBooking, bid)
    if b is None or not ck.may_handle(ct, b):
        raise HTTPException(404, "Buchung nicht gefunden.")
    data = await request.form()
    part = "back" if data.get("part") == "back" else "out"
    info = rs.record_handover(db, b, ct.display_name, part, data, by_caretaker=True)
    db.commit()
    flash(request, ("Abnahme gespeichert. " if part == "back" else "Übergabe gespeichert. ") + info)
    return redirect(f"/r/hausmeister/{token}/{b.id}")


@app.get("/resources/bookings/{bid:int}/protokoll.pdf")
def booking_protocol_pdf(bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from fastapi.responses import Response
    b, _ = _booking(db, bid, user, 2)
    return Response(rs.protocol_pdf(db, b), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Protokoll-{b.ref}.pdf"'})
