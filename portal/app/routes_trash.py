"""Verwaltung › Löschen & Papierkorb: einzelne Einträge suchen und löschen, ganze Bereiche leeren (mit Vorschau der
Anzahl und doppelter Bestätigung), Papierkorb mit Wiederherstellen (30 Tage) und Protokoll. Nur für Admins."""

from datetime import date

from fastapi import Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import trash
from .db import DeletionLog, TrashItem, User
from .main import admin_user, app, check_csrf, flash, get_db, redirect, render

CONFIRM_WORD = "LÖSCHEN"


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@app.get("/admin/loeschen")
def deletion_page(request: Request, kind: str = "booking", q: str = "", before: str = "", status: str = "",
                  user: User = Depends(admin_user), db: Session = Depends(get_db)):
    kind = kind if kind in trash.KINDS else "booking"
    hits = trash.search(db, kind, q) if q else []
    cutoff = _date(before)
    preview = trash.bulk_count(db, kind, cutoff, status) if (cutoff or status) else None
    items = db.scalars(select(TrashItem).order_by(TrashItem.deleted_at.desc()).limit(300)).all()
    total = db.scalar(select(func.count(TrashItem.id))) or 0
    logs = db.scalars(select(DeletionLog).order_by(DeletionLog.at.desc()).limit(100)).all()
    return render(request, "admin_trash.html", user, kinds=trash.KINDS, kind=kind, q=q, hits=hits, before=before,
                  status=status, preview=preview, items=items, total=total, logs=logs, keep=trash.KEEP_DAYS,
                  confirm_word=CONFIRM_WORD, show=trash.KINDS[kind]["show"])


@app.post("/admin/loeschen/eintrag", dependencies=[Depends(check_csrf)])
def deletion_one(request: Request, kind: str = Form(...), obj_id: int = Form(...), back: str = Form(""),
                 user: User = Depends(admin_user), db: Session = Depends(get_db)):
    if kind not in trash.KINDS:
        raise HTTPException(400)
    item = trash.delete_one(db, kind, obj_id, user.name)
    db.commit()
    flash(request, f"„{item.label}“ liegt jetzt im Papierkorb ({trash.KEEP_DAYS} Tage wiederherstellbar)." if item
          else "Eintrag nicht gefunden.", "ok" if item else "error")
    return redirect("/admin/loeschen?" + (back if back.startswith("kind=") else f"kind={kind}"))


@app.post("/admin/loeschen/bereich", dependencies=[Depends(check_csrf)])
def deletion_bulk(request: Request, kind: str = Form(...), before: str = Form(""), status: str = Form(""),
                  expected: int = Form(-1), confirm: str = Form(""), user: User = Depends(admin_user),
                  db: Session = Depends(get_db)):
    """Bereich leeren: nur mit Bedingung, nur wenn die Vorschau-Anzahl noch stimmt und das Bestätigungswort passt."""
    if kind not in trash.KINDS:
        raise HTTPException(400)
    cutoff = _date(before)
    status = status if status in trash.KINDS[kind].get("statuses", {}) else ""
    back = f"/admin/loeschen?kind={kind}&before={before}&status={status}#bereich"
    if confirm.strip().upper() != CONFIRM_WORD:
        flash(request, f"Zur Sicherheit bitte „{CONFIRM_WORD}“ eintippen.", "error")
        return redirect(back)
    n = trash.bulk_count(db, kind, cutoff, status)
    if not n or n != expected:
        flash(request, "Die Anzahl hat sich seit der Vorschau geändert – bitte erneut prüfen." if n else "Nichts zu löschen.", "error")
        return redirect(back)
    done = trash.delete_bulk(db, kind, cutoff, status, user.name)
    db.commit()
    flash(request, f"{done} Einträge in den Papierkorb verschoben ({trash.KEEP_DAYS} Tage wiederherstellbar).")
    return redirect(f"/admin/loeschen?kind={kind}#papierkorb")


@app.post("/admin/loeschen/papierkorb/{item_id:int}", dependencies=[Depends(check_csrf)])
def trash_action(request: Request, item_id: int, action: str = Form(...), user: User = Depends(admin_user),
                 db: Session = Depends(get_db)):
    item = db.get(TrashItem, item_id)
    if item is None:
        raise HTTPException(404)
    label = item.label
    if action == "restore":
        error = trash.restore(db, item, user.name)
        if error:
            db.rollback()
            flash(request, error, "error")
            return redirect("/admin/loeschen#papierkorb")
        db.commit()
        flash(request, f"„{label}“ wiederhergestellt.")
    elif action == "purge":
        trash.purge(db, item, user.name)
        db.commit()
        flash(request, f"„{label}“ endgültig gelöscht.")
    return redirect("/admin/loeschen#papierkorb")
