"""Warteliste der Ressourcenbuchung.

Ist ein Zeitraum belegt, können sich Interessierte auf die Warteliste setzen (mit Bestätigung der E-Mail-Adresse;
angemeldete Vereine ohne). Wird der Zeitraum frei (Storno, Ablehnung, Verfall, Verschieben), bekommt der oder die
Erste auf der Liste eine Mail und kann 24 Stunden lang exklusiv buchen – solange ist der Zeitraum für alle anderen
gesperrt. Läuft die Frist ab, geht das Angebot an den oder die Nächste.
"""

import json
import secrets
from datetime import timedelta

from sqlalchemy import select

from . import links, mailtpl, notify, resources as rs
from .db import Resource, ResourceWait, SessionLocal, to_local, utcnow

OFFER_HOURS = 24
STATUSES = {
    "unconfirmed": ("E-Mail unbestätigt", "secondary"),
    "waiting": ("wartet", "info"),
    "offered": ("Angebot läuft", "warning"),
    "booked": ("gebucht", "success"),
    "expired": ("abgelaufen", "secondary"),
    "cancelled": ("zurückgezogen", "dark"),
}
KEEP = ("mode", "date_from", "date_to", "date", "time_from", "time_to", "tariff", "title", "organizer", "persons",
        "phone", "street", "zip", "city")


def _units(w: ResourceWait) -> set[int] | None:
    ids = {int(x) for x in (w.unit_ids or "").split(",") if x.isdigit()}
    return ids or None


def when(w: ResourceWait) -> str:
    return rs.when_text(rs.ResourceBooking(starts_at=w.starts_at, ends_at=w.ends_at, mode=w.mode))


def link(w: ResourceWait) -> str:
    return f"{links.base('resources')}/r/w/{w.token}"


def data_of(w: ResourceWait) -> rs.FormData:
    try:
        raw = json.loads(w.data_json or "{}")
    except ValueError:
        raw = {}
    return rs.FormData(raw if isinstance(raw, dict) else {})


def holds(db, res: Resource, ids: set[int] | None, start, end, own_token: str = "") -> list[str]:
    """Laufende Angebote aus der Warteliste, die den Zeitraum für andere sperren."""
    out = []
    for w in db.scalars(select(ResourceWait).where(
            ResourceWait.resource_id == res.id, ResourceWait.status == "offered", ResourceWait.offer_until > utcnow(),
            ResourceWait.starts_at < end, ResourceWait.ends_at > start)):
        if w.token != own_token and rs._overlap_units(ids, _units(w)):
            out.append(f"Vorgemerkt für die Warteliste bis {to_local(w.offer_until):%d.%m.%Y %H:%M} Uhr")
    return out


def add(db, res: Resource, q: dict, data, contact: dict, club=None) -> ResourceWait:
    keep = {k: str(data.get(k, "")) for k in KEEP if data.get(k)}
    for k in ("blocks", "units"):
        keep[k] = [str(x) for x in (data.getlist(k) if hasattr(data, "getlist") else data.get(k, []))]
    keep.update({k: str(v) for k, v in (data.items() if hasattr(data, "items") else []) if k.startswith("extra_") and str(v).isdigit()})
    w = ResourceWait(resource_id=res.id, token=secrets.token_urlsafe(24), confirm_code=secrets.token_urlsafe(12),
                     mode=q["mode"], starts_at=q["start"], ends_at=q["end"],
                     unit_ids=",".join(str(i) for i in sorted(q["unit_ids"])) if q["unit_ids"] else "",
                     data_json=json.dumps(keep, ensure_ascii=False), name=contact["name"], email=contact["email"],
                     club_id=club.id if club is not None else None, status="waiting" if club is not None else "unconfirmed")
    db.add(w)
    db.flush()
    if club is None:
        subject, body = mailtpl.render(db, "res_wait_confirm", {
            "name": w.name, "ressource": res.name, "zeitraum": when(w), "link": link(w),
            "bestaetigen_link": f"{link(w)}/confirm/{w.confirm_code}"})
        notify.enqueue(db, w.email, subject, body, "res_wait_confirm")
    else:
        offer_next(db, res, w.starts_at, w.ends_at)   # falls inzwischen frei
    return w


def confirm(db, w: ResourceWait) -> None:
    if w.status == "unconfirmed":
        w.status = "waiting"
        db.flush()
        offer_next(db, w.resource, w.starts_at, w.ends_at)


def position(db, w: ResourceWait) -> int:
    """Platz auf der Warteliste (unter allen, die auf einen überschneidenden Zeitraum warten)."""
    ahead = db.scalars(select(ResourceWait).where(
        ResourceWait.resource_id == w.resource_id, ResourceWait.status.in_(("waiting", "offered")),
        ResourceWait.created_at < w.created_at, ResourceWait.starts_at < w.ends_at, ResourceWait.ends_at > w.starts_at)).all()
    return len(ahead) + 1


def offer_next(db, res: Resource, start, end) -> int:
    """Für einen frei gewordenen Zeitraum: Wartende der Reihe nach prüfen und dem oder der Ersten anbieten,
    deren Zeitraum jetzt ganz frei ist."""
    if not res.waitlist:
        return 0
    db.flush()
    now = utcnow()
    n = 0
    for w in db.scalars(select(ResourceWait).where(
            ResourceWait.resource_id == res.id, ResourceWait.status == "waiting",
            ResourceWait.starts_at < end, ResourceWait.ends_at > start).order_by(ResourceWait.created_at)):
        if w.starts_at <= now:
            w.status = "expired"
            continue
        if rs.conflicts(db, res, _units(w), w.starts_at, w.ends_at) or holds(db, res, _units(w), w.starts_at, w.ends_at, w.token):
            continue
        w.status, w.offered_at = "offered", now
        w.offer_until = min(now + timedelta(hours=OFFER_HOURS), w.starts_at)
        db.flush()
        subject, body = mailtpl.render(db, "res_wait_offer", {
            "name": w.name, "ressource": res.name, "zeitraum": when(w), "link": link(w),
            "frist": to_local(w.offer_until).strftime("%d.%m.%Y, %H:%M Uhr")})
        notify.enqueue(db, w.email, subject, body, "res_wait_offer")
        n += 1
    return n


def expire_offers() -> int:
    """Hintergrunddienst: abgelaufene Angebote weiterreichen, vergangene Einträge schließen."""
    n = 0
    now = utcnow()
    with SessionLocal() as db:
        for w in db.scalars(select(ResourceWait).where(ResourceWait.status == "offered", ResourceWait.offer_until < now)).all():
            w.status = "expired"
            n += offer_next(db, w.resource, w.starts_at, w.ends_at)
        for w in db.scalars(select(ResourceWait).where(ResourceWait.status.in_(("unconfirmed", "waiting")),
                                                       ResourceWait.starts_at < now)).all():
            w.status = "expired"
        db.commit()
    return n


def booked(db, w: ResourceWait, booking) -> None:
    w.status, w.booking_id = "booked", booking.id
