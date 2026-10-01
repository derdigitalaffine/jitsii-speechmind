"""Freigaben im Portal für Terminumfragen und Buchungsseiten – drei Stufen wie bei Formularen.

Stufe 1 = Ergebnisse einsehen, 2 = zusätzlich einladen, 3 = zusätzlich bearbeiten und löschen.
Besitzer:in und Admins haben immer die volle Stufe 4 (dazu gehört das Verwalten der Freigaben).
"""

from sqlalchemy import select

from .db import BookingPage, BookingShare, GroupMember, Poll, PollShare, User

VIEW, INVITE, EDIT, OWNER = 1, 2, 3, 4

LEVELS = {
    "poll": {
        VIEW: ("Ergebnisse einsehen", "Abstimmungsergebnis, Teilnehmende und Export ansehen"),
        INVITE: ("Einladen", "zusätzlich Personen einladen, erinnern und den Abstimmungslink verwalten"),
        EDIT: ("Bearbeiten", "zusätzlich Terminvorschläge und Einstellungen ändern, Termin festlegen, Umfrage löschen"),
    },
    "booking": {
        VIEW: ("Buchungen einsehen", "Kalender, Terminliste und Exporte ansehen"),
        INVITE: ("Einladen", "zusätzlich Personen zum Buchen einladen und den Buchungslink verwalten"),
        EDIT: ("Bearbeiten", "zusätzlich Zeitbereiche und Einstellungen ändern, Termine verschieben oder absagen, "
                             "Seite löschen"),
    },
}

# Art → (Modell der Freigabe, Spalte mit dem Objekt, Objektmodell)
KINDS = {
    "poll": (PollShare, "poll_id", Poll),
    "booking": (BookingShare, "page_id", BookingPage),
}


def _group_ids(user: User):
    return select(GroupMember.group_id).where(GroupMember.user_id == user.id)


def access_level(db, kind: str, obj, user: User) -> int:
    """0 = kein Zugriff, 1–3 = Freigabestufe, 4 = Besitzer:in oder Admin."""
    if obj is None:
        return 0
    if user.is_admin or obj.owner_id == user.id:
        return OWNER
    model, column, _ = KINDS[kind]
    levels = db.scalars(select(model.level).where(
        getattr(model, column) == obj.id,
        (model.user_id == user.id) | (model.group_id.in_(_group_ids(user)))))
    return max(levels, default=0)


def shared_with(db, kind: str, user: User) -> list[tuple[object, int]]:
    """Objekte, die für die Person (direkt oder über Gruppen) freigegeben sind, mit höchster Stufe."""
    model, column, target = KINDS[kind]
    rows = db.execute(select(getattr(model, column), model.level).where(
        (model.user_id == user.id) | (model.group_id.in_(_group_ids(user))))).all()
    best: dict[int, int] = {}
    for obj_id, level in rows:
        best[obj_id] = max(level, best.get(obj_id, 0))
    if not best:
        return []
    found = db.scalars(select(target).where(target.id.in_(best),
                                            target.owner_id.is_(None) | (target.owner_id != user.id))).all()
    return sorted(((o, best[o.id]) for o in found), key=lambda x: x[0].updated_at, reverse=True)


def has_any(db, kind: str, user: User) -> bool:
    model, _, _ = KINDS[kind]
    return db.scalar(select(model.id).where((model.user_id == user.id) | (model.group_id.in_(_group_ids(user))))
                     .limit(1)) is not None


def add(db, kind: str, obj, data) -> tuple[int, int]:
    """Freigaben aus einem Formular (users, groups, level) anlegen oder anheben. Gibt (Anzahl, Stufe)."""
    model, column, _ = KINDS[kind]
    raw = str(data.get("level", "1"))
    level = int(raw) if raw.isdigit() and int(raw) in LEVELS[kind] else VIEW
    added = 0
    for field, attr in (("users", "user_id"), ("groups", "group_id")):
        for value in data.getlist(field):
            if not str(value).isdigit():
                continue
            target = int(value)
            if attr == "user_id" and target == obj.owner_id:
                continue
            existing = next((sh for sh in obj.shares if getattr(sh, attr) == target), None)
            if existing:
                existing.level = level
            else:
                obj.shares.append(model(**{attr: target, "level": level}))
            added += 1
    return added, level


def update(db, kind: str, obj, share_id: int, action: str, level: int) -> str | None:
    """Freigabe ändern oder entfernen. Gibt eine Meldung zurück, None wenn nicht gefunden."""
    model, column, _ = KINDS[kind]
    share = db.get(model, share_id)
    if share is None or getattr(share, column) != obj.id:
        return None
    if action == "delete":
        db.delete(share)
        return "Freigabe entfernt."
    if level in LEVELS[kind]:
        share.level = level
        return f"Freigabe geändert: {LEVELS[kind][level][0]}."
    return "Unverändert."
