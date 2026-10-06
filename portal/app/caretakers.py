"""Hausmeister:innen / Platzwart:innen der Ressourcenbuchung: persönlicher Link (Magic Link) ohne Portal-Konto,
Terminliste der zugeordneten Ressourcen, Übergabe und Abnahme erfassen, optional Erinnerung vor Beginn."""

import hashlib
import re
import secrets
from datetime import timedelta

from sqlalchemy import select

from . import links, mailtpl, notify, resources as rs
from .db import Resource, ResourceBooking, ResourceCaretaker, User, to_local, utcnow

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PATH = "/r/hausmeister/"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


KEEP_LINKS = 5   # so viele zuletzt verschickte Links bleiben gültig (Erinnerungen erzeugen jeweils einen neuen)


def new_token(ct: ResourceCaretaker, reset: bool = False) -> str:
    """Neuer Link. reset=True: alle bisherigen Links werden ungültig (z. B. Gerät verloren)."""
    raw = secrets.token_urlsafe(32)
    old = [] if reset else (ct.token_hash or "").split()
    ct.token_hash = " ".join((old + [_hash(raw)])[-KEEP_LINKS:])
    return raw


def by_token(db, raw: str) -> ResourceCaretaker | None:
    if not raw or len(raw) > 100:
        return None
    h = _hash(raw)
    for ct in db.scalars(select(ResourceCaretaker).where(ResourceCaretaker.token_hash.contains(h))):
        if h in (ct.token_hash or "").split() and ct.active:
            return ct
    return None


def link(raw: str) -> str:
    return f"{links.base('resources')}{PATH}{raw}"


def clean(db, data) -> tuple[dict, list[str]]:
    """Formular → Werte. Mit Portal-Konto kommen Name und E-Mail von dort, Telefon bleibt eintragbar."""
    uid = str(data.get("user_id", ""))
    user = db.get(User, int(uid)) if uid.isdigit() else None
    values = {"name": " ".join(str(data.get("name", "")).split())[:200], "email": str(data.get("email", "")).strip().lower()[:255],
              "phone": " ".join(str(data.get("phone", "")).split())[:60], "note": " ".join(str(data.get("note", "")).split())[:500],
              "user_id": user.id if user else None, "active": data.get("active") == "1"}
    errors = []
    if user is None and not values["name"]:
        errors.append("Bitte einen Namen angeben oder ein Portal-Konto wählen.")
    if user is None and values["email"] and not EMAIL_RE.match(values["email"]):
        errors.append("Die E-Mail-Adresse ist ungültig.")
    return values, errors


def bookings(db, ct: ResourceCaretaker, past_days: int = 21, ahead_days: int = 60) -> list[ResourceBooking]:
    """Bestätigte Buchungen der zugeordneten Ressourcen: anstehende und kürzlich beendete (Abnahme offen)."""
    ids = [r.id for r in ct.resources]
    if not ids:
        return []
    now = utcnow()
    rows = db.scalars(select(ResourceBooking).where(
        ResourceBooking.resource_id.in_(ids), ResourceBooking.status == "confirmed",
        ResourceBooking.ends_at > now - timedelta(days=past_days), ResourceBooking.starts_at < now + timedelta(days=ahead_days))
        .order_by(ResourceBooking.starts_at)).all()
    # Vergangene nur, solange die Abnahme fehlt
    return [b for b in rows if b.ends_at > now or not rs.handover(b).get("back")]


def may_handle(ct: ResourceCaretaker, b: ResourceBooking) -> bool:
    return b.status == "confirmed" and any(r.id == b.resource_id for r in ct.resources)


def send_link(db, ct: ResourceCaretaker) -> bool:
    to = ct.contact_email
    if not to:
        return False
    raw = new_token(ct, reset=True)
    subject, body = mailtpl.render(db, "res_caretaker_link", {
        "name": ct.display_name, "link": link(raw), "ressourcen": ", ".join(r.name for r in ct.resources) or "–"})
    return notify.enqueue(db, to, subject, body, "res_caretaker_link")


def contact_text(res: Resource) -> str:
    """Ansprechperson vor Ort für Buchende (nur wenn an der Ressource eingeschaltet)."""
    if not res.caretaker_public:
        return ""
    parts = []
    for ct in res.caretakers:
        if ct.active:
            phone = ct.phone or (getattr(ct.user, "phone", "") if ct.user else "")
            parts.append(ct.display_name + (f", Telefon {phone}" if phone else ""))
    return "; ".join(parts)


def remind(db, b: ResourceBooking) -> int:
    """Erinnerung vor Beginn an die Hausmeister:innen der Ressource (wenn eingeschaltet), mit eigenem Link."""
    res, n = b.resource, 0
    if not res.caretaker_remind:
        return 0
    for ct in res.caretakers:
        if not ct.active or not ct.contact_email:
            continue
        raw = new_token(ct)
        subject, body = mailtpl.render(db, "res_caretaker_reminder", {
            "name": ct.display_name, "ressource": res.name, "zeitraum": rs.when_text(b), "buchende": b.name,
            "telefon": b.phone or "–", "anlass": b.title or "–", "personen": str(b.persons or "–"), "link": link(raw),
            "beginn": to_local(b.starts_at).strftime("%d.%m.%Y %H:%M")})
        n += notify.enqueue(db, ct.contact_email, subject, body, "res_caretaker_reminder")
    return n
