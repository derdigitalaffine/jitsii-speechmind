"""Terminbuchung im erweiterten Umfang: Terminarten, zuständige Mitarbeitende, Sprechzeiten und Ausnahmen
verwalten (Stufe „Bearbeiten“ der Buchungsseite). Logik in btypes.py."""

from datetime import date

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import bookings as bk, btypes, shares as sh
from .db import BookingClosure, BookingHours, BookingType, User
from .main import app, check_csrf, current_user, flash, get_db, redirect, render
from .routes_bookings import _bpage, _int


def _users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)))


@app.get("/bookings/{page_id}/arten")
def btypes_page(request: Request, page_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    page, level = _bpage(db, page_id, user, sh.EDIT)
    providers = btypes.all_providers(page)
    return render(request, "booking_types.html", user, page=page, users=_users(db), providers=providers,
                  plan=btypes.weekly_plan(page), weekdays=btypes.WEEKDAYS, durations=btypes.DURATIONS,
                  phone_modes=btypes.PHONE_MODES, summary=btypes.summary, field_kinds=btypes.FIELD_KINDS,
                  fields=btypes.fields, max_fields=btypes.MAX_FIELDS, can_video=user.can("video"),
                  previews={t.id: btypes.slots(db, page, t)[:3] for t in page.types}, label=bk.label)


@app.post("/bookings/{page_id}/arten", dependencies=[Depends(check_csrf)])
async def btypes_save(request: Request, page_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Terminart anlegen (type_id leer) oder ändern."""
    page, _level = _bpage(db, page_id, user, sh.EDIT)
    data = await request.form()
    tid = str(data.get("type_id", ""))
    bt = next((t for t in page.types if str(t.id) == tid), None) if tid else None
    if tid and bt is None:
        raise HTTPException(404)
    name = " ".join(str(data.get("name", "")).split())[:160]
    if not name:
        flash(request, "Bitte einen Namen für die Terminart angeben.", "error")
        return redirect(f"/bookings/{page.id}/arten")
    if bt is None:
        bt = BookingType(page_id=page.id, position=len(page.types))
        db.add(bt)
    bt.name = name
    bt.description = str(data.get("description", "")).replace("\r\n", "\n").strip()[:3000]
    bt.docs_hint = str(data.get("docs_hint", "")).replace("\r\n", "\n").strip()[:2000]
    bt.duration_minutes = _int(data.get("duration_minutes"), 5, 480, 30)
    bt.buffer_minutes = _int(data.get("buffer_minutes"), 0, 240, 0)
    bt.min_notice_hours = _int(data.get("min_notice_hours"), 0, 24 * 60, 24)
    bt.location = " ".join(str(data.get("location", "")).split())[:255]
    bt.online = data.get("online") == "1" and user.can("video")
    bt.approval = data.get("approval") == "1"
    bt.choose_provider = data.get("choose_provider") == "1"
    bt.active = data.get("active", "1") == "1"
    bt.phone_mode = data.get("phone_mode") if data.get("phone_mode") in btypes.PHONE_MODES else "optional"
    bt.fields_json = btypes.clean_fields(data.getlist("f_label"), data.getlist("f_kind"), data.getlist("f_options"),
                                         set(data.getlist("f_required")), data.getlist("f_help"))
    ids = {int(x) for x in data.getlist("providers") if str(x).isdigit()}
    bt.providers = list(db.scalars(select(User).where(User.id.in_(ids), User.active.is_(True)))) if ids else []
    db.commit()
    missing = [p.name for p in bt.providers if not any(h.user_id == p.id for h in page.hours)]
    flash(request, f"Terminart „{bt.name}“ gespeichert." + (
        f" Noch ohne Sprechzeiten: {', '.join(missing)} – bitte unten eintragen." if missing else "")
        + ("" if bt.providers else " Ohne zuständige Person wird sie nicht angeboten."))
    return redirect(f"/bookings/{page.id}/arten#art-{bt.id}")


@app.post("/bookings/{page_id}/arten/{type_id}/loeschen", dependencies=[Depends(check_csrf)])
def btypes_delete(request: Request, page_id: int, type_id: int, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    page, _level = _bpage(db, page_id, user, sh.EDIT)
    bt = db.get(BookingType, type_id)
    if bt is None or bt.page_id != page.id:
        raise HTTPException(404)
    if any(b.type_id == bt.id and b.status in ("booked", "requested") for b in page.bookings):
        bt.active = False
        flash(request, f"„{bt.name}“ hat noch Termine und wurde deshalb nur abgeschaltet.")
    else:
        db.delete(bt)
        flash(request, f"Terminart „{bt.name}“ gelöscht.")
    db.commit()
    return redirect(f"/bookings/{page.id}/arten")


@app.post("/bookings/{page_id}/sprechzeiten", dependencies=[Depends(check_csrf)])
async def btypes_hours_add(request: Request, page_id: int, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    page, _level = _bpage(db, page_id, user, sh.EDIT)
    data = await request.form()
    uid = int(data["user_id"]) if str(data.get("user_id", "")).isdigit() else None
    start, end = btypes.valid_time(str(data.get("start", ""))), btypes.valid_time(str(data.get("end", "")))
    days = [int(d) for d in data.getlist("weekday") if str(d).isdigit() and 0 <= int(d) <= 6]
    if uid is None or not db.get(User, uid) or not start or not end or end <= start or not days:
        flash(request, "Bitte Person, Wochentag(e) sowie Beginn und Ende (HH:MM, Ende nach Beginn) angeben.", "error")
        return redirect(f"/bookings/{page.id}/arten#sprechzeiten")
    added = 0
    for d in days:
        if any(h.user_id == uid and h.weekday == d and h.start < end and start < h.end for h in page.hours):
            continue
        page.hours.append(BookingHours(page_id=page.id, user_id=uid, weekday=d, start=start, end=end))
        added += 1
    db.commit()
    flash(request, f"{added} Sprechzeit(en) eingetragen." if added else "Überschneidet sich mit vorhandenen Sprechzeiten.",
          "ok" if added else "error")
    return redirect(f"/bookings/{page.id}/arten#sprechzeiten")


@app.post("/bookings/{page_id}/sprechzeiten/{hid}/loeschen", dependencies=[Depends(check_csrf)])
def btypes_hours_delete(request: Request, page_id: int, hid: int, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    page, _level = _bpage(db, page_id, user, sh.EDIT)
    h = db.get(BookingHours, hid)
    if h is None or h.page_id != page.id:
        raise HTTPException(404)
    db.delete(h)
    db.commit()
    return redirect(f"/bookings/{page.id}/arten#sprechzeiten")


@app.post("/bookings/{page_id}/ausnahmen", dependencies=[Depends(check_csrf)])
async def btypes_closure_add(request: Request, page_id: int, user: User = Depends(current_user),
                             db: Session = Depends(get_db)):
    page, _level = _bpage(db, page_id, user, sh.EDIT)
    data = await request.form()

    def day(v):
        try:
            return date.fromisoformat(str(v or "")).isoformat()
        except ValueError:
            return None
    d0, d1 = day(data.get("date_from")), day(data.get("date_to")) or day(data.get("date_from"))
    uid = int(data["user_id"]) if str(data.get("user_id", "")).isdigit() else None
    if not d0 or not d1 or d1 < d0:
        flash(request, "Bitte einen gültigen Zeitraum angeben.", "error")
        return redirect(f"/bookings/{page.id}/arten#ausnahmen")
    page.closures.append(BookingClosure(page_id=page.id, user_id=uid, date_from=d0, date_to=d1,
                                        note=" ".join(str(data.get("note", "")).split())[:200]))
    db.commit()
    flash(request, "Ausnahme eingetragen – an diesen Tagen werden keine Termine angeboten.")
    return redirect(f"/bookings/{page.id}/arten#ausnahmen")


@app.post("/bookings/{page_id}/ausnahmen/{cid}/loeschen", dependencies=[Depends(check_csrf)])
def btypes_closure_delete(request: Request, page_id: int, cid: int, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    page, _level = _bpage(db, page_id, user, sh.EDIT)
    c = db.get(BookingClosure, cid)
    if c is None or c.page_id != page.id:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    return redirect(f"/bookings/{page.id}/arten#ausnahmen")
