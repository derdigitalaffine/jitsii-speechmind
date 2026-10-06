"""Abwesenheiten und Vertretungen.

Jede:r trägt eigene planbare Abwesenheiten (z. B. Urlaub) mit Vertretung ein. Personen mit dem Recht „Vertretungen
verwalten“, Admins und Gruppenleitungen (für die Mitglieder ihrer Gruppen) tragen Abwesenheiten auch für andere ein,
etwa bei Krankheit. Ein Grund wird nie gespeichert oder angezeigt – sichtbar ist nur „abwesend bis …, Vertretung: …“.

Wer in seinem Profil „Vertretungen für mich bestätigen“ einschaltet, muss jeder Vertretung zustimmen; bis dahin ist
sie „angefragt“ und wirkt noch nicht. Während einer bestätigten Abwesenheit
  * sieht die Vertretung die Aufgaben und Anträge der abwesenden Person (Meine Aufgaben, Antragseingang),
  * bekommt sie Benachrichtigungen an die abwesende Person in Kopie (notify.enqueue, siehe FORWARD_KINDS).
"""

import re
from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_, select

from .db import Absence, Group, GroupMember, User, to_local, utcnow

STATUS = {"pending": ("angefragt", "warning"), "confirmed": ("bestätigt", "success"), "declined": ("abgelehnt", "danger")}
# Benachrichtigungen an Mitarbeitende, die während einer Abwesenheit in Kopie an die Vertretung gehen
FORWARD_KINDS = ("app_task", "app_task_overdue", "app_request_answered", "app_auto", "booking_owner", "form_response",
                 "meeting_rsvp", "poll_vote", "res_staff")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_DAYS = 400


def today() -> str:
    return to_local(utcnow()).date().isoformat()


def fmt(day: str) -> str:
    try:
        return datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return day or ""


def span(a: Absence) -> str:
    if a.starts_on == a.ends_on:
        return fmt(a.starts_on)
    start = fmt(a.starts_on)
    if a.starts_on[:4] == a.ends_on[:4]:
        start = start[:6]
    return f"{start}–{fmt(a.ends_on)}"


def label(a: Absence) -> str:
    """Öffentliche Kurzform – ohne Grund."""
    text = f"abwesend bis {fmt(a.ends_on)}"
    if a.substitute and a.status == "confirmed":
        text += f", Vertretung: {a.substitute.name}"
    return text


def current(db, user_id: int, day: str | None = None) -> Absence | None:
    """Bestätigte Abwesenheit, die am Tag (Standard: heute) gilt."""
    day = day or today()
    return db.scalar(select(Absence).where(Absence.user_id == user_id, Absence.status == "confirmed",
                                           Absence.starts_on <= day, Absence.ends_on >= day)
                     .order_by(Absence.ends_on.desc()).limit(1))


def current_map(db, user_ids=None, day: str | None = None) -> dict[int, Absence]:
    """Benutzer-ID → heute gültige bestätigte Abwesenheit (für Listen und Auswahlfelder)."""
    day = day or today()
    q = select(Absence).where(Absence.status == "confirmed", Absence.starts_on <= day, Absence.ends_on >= day)
    if user_ids is not None:
        q = q.where(Absence.user_id.in_(list(user_ids) or [-1]))
    return {a.user_id: a for a in db.scalars(q)}


def represented(db, user: User, day: str | None = None) -> list[int]:
    """IDs der Personen, die `user` heute vertritt (bestätigt)."""
    day = day or today()
    return list(db.scalars(select(Absence.user_id).where(
        Absence.substitute_id == user.id, Absence.status == "confirmed", Absence.starts_on <= day,
        Absence.ends_on >= day)).all())


def acting_ids(db, user: User) -> list[int]:
    """Die eigene ID plus alle heute vertretenen Personen – für Aufgaben und Zuständigkeiten."""
    return [user.id, *[i for i in represented(db, user) if i != user.id]]


def acting_group_ids(db, user: User) -> list[int]:
    """Gruppen der Person und der heute vertretenen Personen."""
    return list(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id.in_(acting_ids(db, user)))).all())


def substitutes_for_addresses(db, addresses: list[str]) -> dict[str, tuple[str, str]]:
    """E-Mail einer heute abwesenden Person → (E-Mail der Vertretung, Name der abwesenden Person)."""
    addrs = {a.strip().lower() for a in addresses if a}
    if not addrs:
        return {}
    day = today()
    rows = db.execute(select(User.email, User.name, Absence.substitute_id).join(Absence, Absence.user_id == User.id).where(
        User.email.in_(addrs), Absence.status == "confirmed", Absence.starts_on <= day, Absence.ends_on >= day,
        Absence.substitute_id.is_not(None))).all()
    out = {}
    for email, name, sub_id in rows:
        sub = db.get(User, sub_id)
        if sub is not None and sub.active and sub.email.lower() != email.lower():
            out[email.lower()] = (sub.email, name)
    return out


# --- Wer darf für wen eintragen? -----------------------------------------------------------------

def manages_all(user: User) -> bool:
    return bool(user.is_admin or user.can("absences"))


def led_groups(db, user: User) -> list[Group]:
    return list(db.scalars(select(Group).where(Group.lead_id == user.id).order_by(Group.name)))


def manageable(db, user: User) -> list[User]:
    """Personen, für die `user` Abwesenheiten eintragen darf (ohne sich selbst)."""
    if manages_all(user):
        return list(db.scalars(select(User).where(User.active.is_(True), User.id != user.id).order_by(User.name)))
    ids = select(GroupMember.user_id).join(Group, Group.id == GroupMember.group_id).where(Group.lead_id == user.id)
    return list(db.scalars(select(User).where(User.id.in_(ids), User.active.is_(True), User.id != user.id)
                           .order_by(User.name)))


def may_manage(db, actor: User, target_id: int) -> bool:
    if target_id == actor.id or manages_all(actor):
        return True
    return any(u.id == target_id for u in manageable(db, actor))


def can_manage_others(db, user: User) -> bool:
    return manages_all(user) or bool(led_groups(db, user))


# --- Anlegen, Antworten, Löschen -----------------------------------------------------------------

def parse_day(value: str) -> str | None:
    v = (value or "").strip()
    if not DATE_RE.match(v):
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        return None
    return v


def validate(db, user_id: int, starts_on: str | None, ends_on: str | None, substitute_id: int | None,
             keep_id: int | None = None) -> str:
    if not starts_on or not ends_on:
        return "Bitte Beginn und Ende angeben."
    if ends_on < starts_on:
        return "Das Ende liegt vor dem Beginn."
    if (date.fromisoformat(ends_on) - date.fromisoformat(starts_on)).days > MAX_DAYS:
        return f"Höchstens {MAX_DAYS} Tage am Stück."
    if substitute_id == user_id:
        return "Eine Person kann sich nicht selbst vertreten."
    if substitute_id is not None:
        sub = db.get(User, substitute_id)
        if sub is None or not sub.active:
            return "Die gewählte Vertretung gibt es nicht (mehr)."
    overlap = select(Absence.id).where(Absence.user_id == user_id, Absence.status != "declined",
                                       Absence.starts_on <= ends_on, Absence.ends_on >= starts_on)
    if keep_id:
        overlap = overlap.where(Absence.id != keep_id)
    if db.scalar(overlap.limit(1)):
        return "In diesem Zeitraum ist bereits eine Abwesenheit eingetragen."
    return ""


def create(db, actor: User, user: User, starts_on: str, ends_on: str, substitute: User | None, note: str = "",
           auto_reply: str = "") -> Absence:
    """Neue Abwesenheit. Braucht die Vertretung eine Zustimmung (Profil), ist sie zunächst „angefragt“."""
    needs_ok = substitute is not None and substitute.sub_confirm and substitute.id != actor.id
    a = Absence(user_id=user.id, substitute_id=substitute.id if substitute else None, starts_on=starts_on,
                ends_on=ends_on, status="pending" if needs_ok else "confirmed", note=note.strip()[:2000],
                auto_reply=auto_reply.strip()[:1000], created_by=actor.id)
    db.add(a)
    db.flush()
    if substitute is not None and substitute.id != actor.id:
        _mail(db, a, substitute, "absence_request" if needs_ok else "absence_info", actor)
    return a


def answer(db, a: Absence, accept: bool) -> None:
    a.status = "confirmed" if accept else "declined"
    a.decided_at = utcnow()
    for target in {a.creator, a.user} - {None, a.substitute}:
        if target.active:
            _mail(db, a, target, "absence_answer", a.creator, antwort="zugestimmt" if accept else "abgelehnt")


def _mail(db, a: Absence, to: User, key: str, actor: User | None, **extra) -> None:
    from . import mailtpl, notify
    from .config import settings
    values = {"name": to.name, "abwesend": a.user.name if a.user else "", "zeitraum": span(a),
              "vertretung": a.substitute.name if a.substitute else "", "eingetragen_von": actor.name if actor else "",
              "notiz": f"Notiz: {a.note}" if a.note else "", "link": settings.portal_base_url + "/abwesenheiten", **extra}
    subject, body = mailtpl.render(db, key, values)
    notify.enqueue(db, to.email, subject, body, key)


def visible_list(db, user: User, include_past_days: int = 30) -> dict:
    """Für die Seite „Abwesenheiten“: eigene, Vertretungen für mich, verwaltete Personen."""
    since = (date.fromisoformat(today()) - timedelta(days=include_past_days)).isoformat()
    mine = db.scalars(select(Absence).where(Absence.user_id == user.id, Absence.ends_on >= since)
                      .order_by(Absence.starts_on)).all()
    for_me = db.scalars(select(Absence).where(Absence.substitute_id == user.id, Absence.ends_on >= since)
                        .order_by(Absence.starts_on)).all()
    others = []
    if can_manage_others(db, user):
        ids = [u.id for u in manageable(db, user)]
        others = db.scalars(select(Absence).where(Absence.user_id.in_(ids or [-1]), Absence.ends_on >= since)
                            .order_by(Absence.starts_on)).all()
    return {"mine": mine, "for_me": for_me, "others": others}


def overlaps(day_from: str, day_to: str):
    return and_(Absence.starts_on <= day_to, Absence.ends_on >= day_from)


def dashboard(db, user: User) -> dict:
    """Kachel „Abwesenheit & Vertretung“: eigene laufende/nächste Abwesenheit, wen ich vertrete, offene Anfragen,
    abwesende Kolleg:innen (für Leitungen bzw. eigene Gruppen)."""
    day = today()
    own = db.scalar(select(Absence).where(Absence.user_id == user.id, Absence.status != "declined",
                                          Absence.ends_on >= day).order_by(Absence.starts_on).limit(1))
    representing = db.scalars(select(Absence).where(Absence.substitute_id == user.id, Absence.status == "confirmed",
                                                    Absence.starts_on <= day, Absence.ends_on >= day)).all()
    pending = db.scalars(select(Absence).where(Absence.substitute_id == user.id, Absence.status == "pending",
                                               Absence.ends_on >= day)).all()
    groups = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
    colleagues_ids = select(GroupMember.user_id).where(or_(GroupMember.group_id.in_(groups),
                                                           GroupMember.group_id.in_(select(Group.id).where(Group.lead_id == user.id))))
    away = db.scalars(select(Absence).where(Absence.user_id.in_(colleagues_ids), Absence.user_id != user.id,
                                            Absence.status == "confirmed", Absence.starts_on <= day,
                                            Absence.ends_on >= day).order_by(Absence.ends_on)).all()
    return {"own": own, "representing": representing, "pending": pending, "away": away[:8], "label": label, "span": span}
