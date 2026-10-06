"""Abwesenheiten und Vertretungen: eigene planen, für andere eintragen (Recht „Vertretungen verwalten“,
Gruppenleitungen, Admins), Vertretungen zustimmen oder ablehnen. Logik in absence.py."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import absence as ab
from .db import Absence, User
from .main import app, check_csrf, current_user, flash, get_db, redirect, render


@app.get("/abwesenheiten")
def absences_page(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lists = ab.visible_list(db, user)
    people = ab.manageable(db, user) if ab.can_manage_others(db, user) else []
    colleagues = [u for u in db.query(User).filter(User.active.is_(True), User.id != user.id).order_by(User.name)]
    away = ab.current_map(db)
    return render(request, "absences.html", user, **lists, people=people, colleagues=colleagues, away=away,
                  status=ab.STATUS, span=ab.span, label=ab.label, fmt=ab.fmt, today=ab.today(),
                  manage_all=ab.manages_all(user), led=ab.led_groups(db, user))


@app.post("/abwesenheiten", dependencies=[Depends(check_csrf)])
async def absences_create(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await request.form()
    target_id = int(data["user_id"]) if str(data.get("user_id", "")).isdigit() else user.id
    if not ab.may_manage(db, user, target_id):
        raise HTTPException(403, "Für diese Person dürfen Sie keine Abwesenheit eintragen.")
    target = db.get(User, target_id)
    if target is None or not target.active:
        raise HTTPException(404)
    start, end = ab.parse_day(data.get("starts_on", "")), ab.parse_day(data.get("ends_on", ""))
    sub_id = int(data["substitute_id"]) if str(data.get("substitute_id", "")).isdigit() else None
    error = ab.validate(db, target.id, start, end, sub_id)
    if error:
        flash(request, error, "error")
        return redirect("/abwesenheiten")
    sub = db.get(User, sub_id) if sub_id else None
    own = target.id == user.id
    a = ab.create(db, user, target, start, end, sub, note=str(data.get("note", "")),
                  auto_reply=str(data.get("auto_reply", "")) if own else "")
    db.commit()
    who = "Ihre Abwesenheit" if own else f"Abwesenheit von {target.name}"
    if a.status == "pending":
        flash(request, f"{who} ist eingetragen. {sub.name} wurde um Zustimmung zur Vertretung gebeten.")
    else:
        flash(request, f"{who} ist eingetragen" + (f" – Vertretung: {sub.name}." if sub else " (ohne Vertretung)."))
    return redirect("/abwesenheiten")


def _absence(db: Session, absence_id: int) -> Absence:
    a = db.get(Absence, absence_id)
    if a is None:
        raise HTTPException(404, "Diese Abwesenheit gibt es nicht.")
    return a


@app.post("/abwesenheiten/{absence_id}/antwort", dependencies=[Depends(check_csrf)])
async def absences_answer(request: Request, absence_id: int, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    a = _absence(db, absence_id)
    if a.substitute_id != user.id or a.status != "pending":
        raise HTTPException(403, "Diese Anfrage können Sie nicht beantworten.")
    accept = (await request.form()).get("accept") == "1"
    ab.answer(db, a, accept)
    db.commit()
    flash(request, f"Vertretung für {a.user.name} " + ("zugestimmt." if accept else "abgelehnt."))
    return redirect("/abwesenheiten")


@app.post("/abwesenheiten/{absence_id}/loeschen", dependencies=[Depends(check_csrf)])
def absences_delete(request: Request, absence_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _absence(db, absence_id)
    if not (a.created_by == user.id or ab.may_manage(db, user, a.user_id)):
        raise HTTPException(403, "Diese Abwesenheit dürfen Sie nicht löschen.")
    name = a.user.name
    db.delete(a)
    db.commit()
    flash(request, f"Abwesenheit von {name} gelöscht." if a.user_id != user.id else "Abwesenheit gelöscht.")
    return redirect("/abwesenheiten")


@app.post("/abwesenheiten/ende/{absence_id}", dependencies=[Depends(check_csrf)])
def absences_end_today(request: Request, absence_id: int, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Früher zurück: Abwesenheit endet gestern (bzw. wird gelöscht, wenn sie heute erst begonnen hätte)."""
    from datetime import date, timedelta
    a = _absence(db, absence_id)
    if not (a.created_by == user.id or ab.may_manage(db, user, a.user_id)):
        raise HTTPException(403)
    yesterday = (date.fromisoformat(ab.today()) - timedelta(days=1)).isoformat()
    if a.starts_on > yesterday:
        db.delete(a)
    else:
        a.ends_on = min(a.ends_on, yesterday)
    db.commit()
    flash(request, "Die Abwesenheit ist beendet.")
    return redirect("/abwesenheiten")
