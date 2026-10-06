"""Startseite nach der Anmeldung: Kacheln mit allem, was für die Person gerade wichtig ist – je nach Rechten
und eingeschalteten Modulen. Reihenfolge und Sichtbarkeit lassen sich je Person anpassen."""

import json
from datetime import timedelta

from sqlalchemy import func, or_, select

from . import planning
from .db import (
    Booking, BookingPage, Form, FormResponse, Invitee, LawText, Meeting, Poll, PollParticipant, ShortLink, User, Vote,
    to_local, utcnow,
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
    "resources": ("Ressourcen", "fa-building"),
    "krank": ("Krankmeldungen", "fa-notes-medical"),
    "favorites": ("Meine Favoriten", "fa-star"),
    "absence": ("Abwesenheit & Vertretung", "fa-umbrella-beach"),
    "votes": ("Abstimmungen", "fa-check-to-slot"),
    "laws": ("Ortsrecht – zuletzt geändert", "fa-scale-balanced"),
    "shortlinks": ("Kurzlinks", "fa-link"),
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


def _resources(db, user):
    from . import resources as rs
    managed = [r.id for r, lvl in rs.visible(db, user) if lvl >= 3]
    return rs.booking_counts(db, managed) | {"when": rs.when_text}


def _krank(db, user):
    from . import krank
    from .db import KrankReport
    st = krank.stats(db, user)
    items = db.scalars(krank.reports_query(db, user).where(KrankReport.status != "done")
                       .order_by(KrankReport.created_at.desc()).limit(5)).all()
    return {"items": items, "stats": st, "krank": krank}


def _favorites(db, user, ctx=None):
    from . import nav
    if ctx is None:
        return {"items": []}
    entries = {e["id"]: e for g in nav.build(ctx)["groups"] for e in g["items"]}
    return {"items": [entries[i] for i in nav.prefs(user)["fav"] if i in entries]}


def _absence(db, user):
    from . import absence
    return absence.dashboard(db, user)


def _votes(db, user):
    rows = db.scalars(select(Vote).where(Vote.owner_id == user.id, Vote.status != "closed")
                      .order_by(Vote.updated_at.desc()).limit(5)).all()
    return {"items": rows}


def _laws(db, user):
    q = select(LawText).order_by(LawText.updated_at.desc()).limit(5)
    if not user.can("laws"):
        q = q.where(LawText.published.is_(True))
    return {"items": db.scalars(q).all(), "editor": user.can("laws")}


def _shortlinks(db, user):
    rows = db.scalars(select(ShortLink).where(ShortLink.owner_id == user.id)
                      .order_by(ShortLink.visit_count.desc(), ShortLink.created_at.desc()).limit(5)).all()
    total = db.scalar(select(func.coalesce(func.sum(ShortLink.visit_count), 0)).where(ShortLink.owner_id == user.id)) or 0
    return {"items": rows, "total": total}


def quick_actions(user, modules) -> list[tuple[str, str, str]]:
    """Schnellaktionen oben auf der Übersicht: (Adresse, Symbol, Text) – nur, was die Person darf."""
    return _quick(user, modules)["items"]


def _quick(user, modules):
    links = []
    add = lambda cond, href, icon, label: cond and links.append((href, icon, label))  # noqa: E731
    add(user.can("video"), "/meetings", "fa-video", "Meeting starten")
    add(user.can("video"), "/meetings/plan", "fa-calendar-plus", "Besprechung planen")
    add(user.can("polls") and "polls" in modules, "/polls/new", "fa-calendar-check", "Terminumfrage")
    add(user.can("votes") and "polls" in modules, "/votes/new", "fa-check-to-slot", "Abstimmung")
    add(user.can("forms") and "forms" in modules, "/forms", "fa-clipboard-list", "Formular")
    add(user.can("shortlinks") and "shortlinks" in modules, "/shortlinks", "fa-link", "Kurzlink & QR")
    add("krank" in modules, "/krank", "fa-notes-medical", "Krank melden")
    add("laws" in modules, "/recht", "fa-scale-balanced", "Ortsrecht")
    add("maps" in modules, "/karte", "fa-map-location-dot", "Karte")
    return {"items": links}


def _case_worker(db, user) -> bool:
    """Bearbeitet die Person Anträge (Formularrecht, Zuständigkeit, Freigabe oder Aufgabe)?"""
    from . import applications as apps
    if user.can("forms") or user.can("processes"):
        return True
    return db.scalar(apps.inbox_query(db, user).with_only_columns(FormResponse.id).limit(1)) is not None


def tiles(db, user: User, modules: set, ctx=None, cache: dict | None = None) -> list[dict]:
    """Verfügbare Kacheln in der Reihenfolge der Person, mit Daten (ausgeblendete ohne Daten). ctx: Menü-Kontext
    (für die Favoriten), cache: bereits geladene Daten aus overview()."""
    cache = cache if cache is not None else {}
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
    if "resources" in modules:
        from . import resources as rs
        if any(lvl >= 3 for _, lvl in rs.visible(db, user)):
            available.append("resources")
    if "krank" in modules:
        from . import krank
        if krank.uses_module(db, user):
            available.append("krank")
    available.append("absence")
    available.append("favorites")
    if "polls" in modules and user.can("votes"):
        available.append("votes")
    if "laws" in modules:
        available.append("laws")
    if "shortlinks" in modules and user.can("shortlinks"):
        available.append("shortlinks")
    p = prefs(user)
    order = [k for k in p.get("order", []) if k in available] + [k for k in available if k not in p.get("order", [])]
    hidden = set(p.get("hidden", []))
    loaders = {"tasks": _tasks, "applications": _applications, "meetings": _meetings, "polls": _polls,
               "bookings": _bookings, "inbox": _inbox, "responses": _responses, "dms": _dms,
               "resources": _resources, "krank": _krank, "votes": _votes, "laws": _laws, "shortlinks": _shortlinks,
               "favorites": lambda d, u: _favorites(d, u, ctx), "absence": _absence}
    out = []
    for key in order:
        title, icon = TILES[key]
        data = {}
        if key not in hidden:
            data = cache[key] if key in cache else loaders[key](db, user)
        out.append({"key": key, "title": title, "icon": icon, "hidden": key in hidden, "data": data})
    return out


# --- Heute & Handlungsbedarf --------------------------------------------------------------------

def overview(db, user: User, modules: set) -> tuple[dict, dict]:
    """Oberer Bereich der Übersicht: was heute ansteht (Termine, Buchungen, Übergaben) und was erledigt werden muss
    (überfällige Aufgaben, neue Anträge, Anfragen, Abstimmungen …). Gibt (Daten, Zwischenspeicher für tiles()) zurück."""
    cache: dict = {}
    actions: list[dict] = []
    agenda: list[dict] = []

    def act(n, label, url, icon, level="primary"):
        if n:
            actions.append({"count": n, "label": label, "url": url, "icon": icon, "level": level})

    now = utcnow()
    today = to_local(now).date()
    if "applications" in modules and _case_worker(db, user):
        t = cache["tasks"] = _tasks(db, user)
        a = cache["applications"] = _applications(db, user)
        act(t["overdue"], "Aufgaben überfällig", "/tasks", "fa-triangle-exclamation", "danger")
        act(t["count"] - t["overdue"], "offene Aufgaben", "/tasks", "fa-list-check")
        act(a["overdue"], "Anträge mit Frist über", "/forms/applications?status=overdue", "fa-hourglass-end", "danger")
        act(a["new"], "neue Anträge", "/forms/applications?status=received", "fa-file-signature")
        act(a["query"], "Rückfragen offen", "/forms/applications?status=query", "fa-comments", "secondary")
    if "polls" in modules:
        pl = cache["polls"] = _polls(db, user)
        if pl["todo"]:
            act(len(pl["todo"]), "Terminumfragen beantworten", f"/t/p/{pl['todo'][0].edit_token}", "fa-calendar-check",
                "warning")
    if "forms" in modules:
        ib = cache["inbox"] = _inbox(db, user)
        act(ib["count"], "Formulare auszufüllen", "/forms/inbox", "fa-inbox", "warning")
    if "resources" in modules:
        from . import resources as rs
        if any(lvl >= 3 for _, lvl in rs.visible(db, user)):
            r = cache["resources"] = _resources(db, user)
            act(len(r["requested"]), "Raumanfragen entscheiden", "/resources/bookings?status=requested", "fa-building", "warning")
            for b in r["today_out"]:
                agenda.append({"at": b.starts_at, "label": f"Übergabe {b.resource.name}", "sub": b.title or b.name,
                               "url": f"/resources/bookings/{b.id}", "icon": "fa-key"})
            for b in r["today_back"]:
                agenda.append({"at": b.ends_at, "label": f"Rücknahme {b.resource.name}", "sub": b.title or b.name,
                               "url": f"/resources/bookings/{b.id}", "icon": "fa-rotate-left"})
    if "krank" in modules:
        from . import krank
        if krank.uses_module(db, user):
            k = cache["krank"] = _krank(db, user)
            act(k["stats"]["by_status"].get("new", 0), "neue Krankmeldungen", "/krankmelder/liste?status=new", "fa-notes-medical")
    if user.can("video"):
        m = cache["meetings"] = _meetings(db, user)
        for mt in m["items"]:
            if to_local(mt.starts_at).date() == today:
                agenda.append({"at": mt.starts_at, "label": mt.title, "sub": "Meeting" if mt.id in m["own"] else "Einladung",
                               "url": f"/meetings/{mt.id}" if mt.id in m["own"] else f"/join/{mt.room}", "icon": "fa-video"})
    if user.can("bookings") and "bookings" in modules:
        bk = cache["bookings"] = _bookings(db, user)
        for b in bk["items"]:
            if to_local(b.starts_at).date() == today:
                agenda.append({"at": b.starts_at, "label": b.name, "sub": b.page.title, "url": f"/bookings/{b.page_id}",
                               "icon": "fa-calendar-plus"})
    ab = cache["absence"] = _absence(db, user)
    act(len(ab["pending"]), "Bitten um Vertretung", "/abwesenheiten", "fa-people-arrows", "warning")
    order = {"danger": 0, "warning": 1, "primary": 2, "secondary": 3}
    actions.sort(key=lambda x: order.get(x["level"], 9))
    agenda.sort(key=lambda x: x["at"])
    return {"actions": actions, "agenda": agenda, "now": now, "today": today.isoformat()}, cache
