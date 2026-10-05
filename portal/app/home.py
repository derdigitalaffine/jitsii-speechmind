"""Startseite nach der Anmeldung: Kacheln mit allem, was für die Person gerade wichtig ist – je nach Rechten
und eingeschalteten Modulen. Reihenfolge und Sichtbarkeit lassen sich je Person anpassen."""

import json
from datetime import timedelta

from sqlalchemy import func, or_, select

from . import planning
from .db import (
    Booking, BookingPage, Form, FormResponse, Invitee, Meeting, Poll, PollParticipant, User, to_local, utcnow,
)

TILES = {
    "tasks": ("Meine Aufgaben", "fa-list-check"),
    "applications": ("Antragseingang", "fa-file-signature"),
    "meetings": ("Termine & Meetings", "fa-video"),
    "polls": ("Terminumfragen", "fa-calendar-check"),
    "bookings": ("Buchungen", "fa-calendar-plus"),
    "inbox": ("Zum Ausfüllen", "fa-inbox"),
    "responses": ("Neue Antworten", "fa-clipboard-list"),
    "dms": ("Ablage", "fa-box-archive"),
    "quick": ("Schnellzugriff", "fa-bolt"),
}


def prefs(user: User) -> dict:
    try:
        data = json.loads(user.dashboard_json or "{}")
    except (ValueError, TypeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _tasks(db, user):
    from . import workflow
    tasks = workflow.my_tasks(db, user)
    now = utcnow()
    waiting = workflow.waiting_requests(db, user)
    return {"items": tasks[:6], "count": len(tasks), "overdue": sum(1 for t in tasks if t.due_at and t.due_at < now),
            "waiting": len(waiting), "now": now}


def _applications(db, user):
    from . import applications as apps
    rows = db.scalars(apps.inbox_query(db, user).where(FormResponse.closed_at.is_(None))
                      .order_by(FormResponse.created_at.desc())).all()
    now = utcnow()
    return {"items": rows[:5], "open": len(rows), "overdue": sum(1 for r in rows if r.due_at and r.due_at < now),
            "query": sum(1 for r in rows if r.status == "query"),
            "new": sum(1 for r in rows if r.status == "received"), "statuses": apps.STATUSES}


def _meetings(db, user):
    now = utcnow()
    own = db.scalars(select(Meeting).where(Meeting.owner_id == user.id, Meeting.cancelled_at.is_(None),
                                           Meeting.starts_at.is_not(None), Meeting.starts_at > now - timedelta(hours=2))
                     .order_by(Meeting.starts_at).limit(6)).all()
    invited = db.scalars(select(Meeting).join(Invitee).where(Invitee.email == user.email, Meeting.owner_id != user.id,
                                                             Meeting.cancelled_at.is_(None), Meeting.starts_at.is_not(None),
                                                             Meeting.starts_at > now - timedelta(hours=2))
                         .order_by(Meeting.starts_at).limit(6)).all()
    items = sorted({m.id: m for m in [*own, *invited]}.values(), key=lambda m: m.starts_at)[:6]
    today = to_local(now).date()
    return {"items": items, "today": sum(1 for m in items if to_local(m.starts_at).date() == today),
            "own": {m.id for m in own}, "is_live": planning.is_upcoming}


def _polls(db, user):
    polls = db.scalars(select(Poll).where(Poll.owner_id == user.id, Poll.closed.is_(False), Poll.final_option_id.is_(None))
                       .order_by(Poll.updated_at.desc()).limit(5)).all()
    todo = db.scalars(select(PollParticipant).join(Poll).where(
        or_(PollParticipant.user_id == user.id, PollParticipant.email == user.email),
        PollParticipant.answered_at.is_(None), Poll.closed.is_(False))).all()
    return {"items": polls, "todo": todo[:5]}


def _bookings(db, user):
    now = utcnow()
    rows = db.scalars(select(Booking).join(BookingPage).where(BookingPage.owner_id == user.id, Booking.starts_at > now,
                                                              Booking.cancelled_at.is_(None))
                      .order_by(Booking.starts_at).limit(6)).all()
    week = db.scalar(select(func.count(Booking.id)).join(BookingPage).where(
        BookingPage.owner_id == user.id, Booking.starts_at > now, Booking.starts_at < now + timedelta(days=7),
        Booking.cancelled_at.is_(None))) or 0
    return {"items": rows, "week": week}


def _inbox(db, user):
    from . import forms as fm
    invites = [i for i in fm.user_invites(db, user) if not i.submitted_at and fm.is_open(i.form)]
    return {"items": invites[:6], "count": len(invites)}


def _responses(db, user):
    since = utcnow() - timedelta(days=7)
    rows = db.execute(select(Form, func.count(FormResponse.id), func.max(FormResponse.created_at))
                      .join(FormResponse).where(Form.owner_id == user.id, FormResponse.created_at > since)
                      .group_by(Form.id).order_by(func.max(FormResponse.created_at).desc()).limit(6)).all()
    return {"items": rows, "total": sum(r[1] for r in rows)}


def _dms(db, user):
    from . import dms
    from .db import DmsRecord
    lv = dms.levels(db, user)
    q = select(DmsRecord).order_by(DmsRecord.updated_at.desc()).limit(6)
    if not user.is_admin:
        q = q.where(DmsRecord.area_id.in_(list(lv) or [-1]))
    return {"items": db.scalars(q).all(), "can_write": any(v >= 2 for v in lv.values())}


def _quick(user, modules):
    links = []
    add = lambda cond, href, icon, label: cond and links.append((href, icon, label))  # noqa: E731
    add(user.can("video"), "/meetings/plan", "fa-calendar-plus", "Besprechung planen")
    add(user.can("video"), "/meetings", "fa-video", "Meeting starten")
    add(user.can("forms") and "forms" in modules, "/forms", "fa-clipboard-list", "Formular anlegen")
    add(user.can("polls") and "polls" in modules, "/polls", "fa-calendar-check", "Terminumfrage")
    add(user.can("shortlinks") and "shortlinks" in modules, "/shortlinks", "fa-link", "Kurzlink")
    add("maps" in modules, "/karte", "fa-map-location-dot", "Kartenbrowser")
    add("laws" in modules, "/recht", "fa-scale-balanced", "Ortsrecht")
    add(user.can("processes") and "applications" in modules, "/processes", "fa-diagram-project", "Prozesse")
    add(True, "/profile", "fa-user-gear", "Profil & Sicherheit")
    return {"items": links}


def _case_worker(db, user) -> bool:
    """Bearbeitet die Person Anträge (Formularrecht, Zuständigkeit, Freigabe oder Aufgabe)?"""
    from . import applications as apps
    if user.can("forms") or user.can("processes"):
        return True
    return db.scalar(apps.inbox_query(db, user).with_only_columns(FormResponse.id).limit(1)) is not None


def tiles(db, user: User, modules: set) -> list[dict]:
    """Verfügbare Kacheln in der Reihenfolge der Person, mit Daten (ausgeblendete ohne Daten)."""
    from . import dms
    available = []
    if "applications" in modules and _case_worker(db, user):
        available += ["tasks", "applications"]
    if user.can("video"):
        available.append("meetings")
    if "polls" in modules and (user.can("polls") or _polls(db, user)["todo"]):
        available.append("polls")
    if user.can("bookings") and "bookings" in modules:
        available.append("bookings")
    if "forms" in modules:
        available.append("inbox")
        if user.can("forms"):
            available.append("responses")
    if "dms" in modules and (user.is_admin or dms.levels(db, user)):
        available.append("dms")
    available.append("quick")
    p = prefs(user)
    order = [k for k in p.get("order", []) if k in available] + [k for k in available if k not in p.get("order", [])]
    hidden = set(p.get("hidden", []))
    loaders = {"tasks": _tasks, "applications": _applications, "meetings": _meetings, "polls": _polls,
               "bookings": _bookings, "inbox": _inbox, "responses": _responses, "dms": _dms}
    out = []
    for key in order:
        title, icon = TILES[key]
        data = {}
        if key not in hidden:
            data = _quick(user, modules) if key == "quick" else loaders[key](db, user)
        out.append({"key": key, "title": title, "icon": icon, "hidden": key in hidden, "data": data})
    return out
