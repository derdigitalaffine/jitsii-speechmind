"""Vereine und Dauernutzer der Ressourcenbuchung.

Ein Verein meldet sich ohne Passwort an: E-Mail-Adresse eingeben, Link aus der Mail anklicken (30 Minuten gültig),
danach bleibt er 30 Tage angemeldet (eigenes, signiertes Cookie). Angemeldet bucht er ohne erneute Angaben und ohne
Bestätigungsmail, mit seinem Tarif (Tarif gleichen Namens an der Ressource) und seiner Zahlweise:

  instant   wie alle: Zahlung mit Frist nach der Bestätigung
  invoice   Rechnung je Buchung (Überweisung), die Reservierung verfällt nicht bei Verzug
  monthly   Sammelrechnung: Buchungen eines Monats werden gemeinsam abgerechnet (Verwaltung › Vereine)
"""

import hashlib
import re
import secrets
from datetime import date, datetime, time, timedelta

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select

from . import links, mailtpl, notify, payments as pay, resources as rs
from .config import settings
from .db import ResourceBooking, ResourceClub, utcnow
from .planning import EMAIL_RE

COOKIE = "jsm_res_club"
LOGIN_DAYS = 30
LINK_MINUTES = 30
BILLING = {"instant": "sofort (wie alle)", "invoice": "Rechnung je Buchung", "monthly": "Sammelrechnung je Monat"}
_signer = URLSafeTimedSerializer(settings.secret_key, salt="res-club-login")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean(data, club: ResourceClub | None = None) -> tuple[dict, list[str]]:
    text = lambda k, n=255: " ".join(str(data.get(k, "")).split())[:n]  # noqa: E731
    values = {"name": text("club_name", 200), "contact_name": text("contact_name"),
              "email": str(data.get("email", "")).strip().lower()[:255], "phone": text("phone", 60),
              "street": text("street"), "zip": re.sub(r"\D", "", str(data.get("zip", "")))[:10], "city": text("city", 200)}
    errors = []
    if not values["name"]:
        errors.append("Bitte den Namen des Vereins bzw. der Einrichtung angeben.")
    if not EMAIL_RE.match(values["email"] or "-"):
        errors.append("Bitte eine gültige E-Mail-Adresse angeben.")
    return values, errors


def by_email(db, email: str) -> ResourceClub | None:
    return db.scalar(select(ResourceClub).where(ResourceClub.email == email.strip().lower()))


def send_login(db, email: str) -> bool:
    """Anmeldelink verschicken – nur für freigegebene, aktive Vereine. Antwortet nach außen immer gleich."""
    club = by_email(db, email)
    if club is None or not club.active or club.pending:
        return False
    token = secrets.token_urlsafe(32)
    club.token_hash, club.token_expires = _hash(token), utcnow() + timedelta(minutes=LINK_MINUTES)
    subject, body = mailtpl.render(db, "res_club_login", {"name": club.contact_name or club.name, "verein": club.name,
                                                          "link": f"{links.base('resources')}/r/login/{token}"})
    return notify.enqueue(db, club.email, subject, body, "res_club_login")


def consume(db, token: str) -> ResourceClub | None:
    club = db.scalar(select(ResourceClub).where(ResourceClub.token_hash == _hash(token))) if token else None
    if club is None or not club.active or club.pending or not club.token_expires or club.token_expires < utcnow():
        return None
    club.token_hash, club.token_expires, club.last_login_at = None, None, utcnow()
    return club


def set_cookie(response, club: ResourceClub) -> None:
    response.set_cookie(COOKIE, _signer.dumps({"id": club.id, "g": club.login_gen or 0}), max_age=LOGIN_DAYS * 86400, httponly=True,
                        samesite="lax", secure=settings.secure_cookies)


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE)


def current(request, db) -> ResourceClub | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _signer.loads(raw, max_age=LOGIN_DAYS * 86400)
    except BadSignature:
        return None
    club = db.get(ResourceClub, data.get("id")) if isinstance(data, dict) else None
    if club is None or not club.active or club.pending or data.get("g", 0) != (club.login_gen or 0):
        return None   # gesperrt, gelöscht oder von der Verwaltung auf allen Geräten abgemeldet
    return club


def logout_everywhere(club: ResourceClub) -> None:
    club.login_gen = (club.login_gen or 0) + 1
    club.token_hash = club.token_expires = None


def contact(club: ResourceClub) -> dict:
    """Kontaktangaben für eine Buchung des Vereins."""
    return {"name": club.contact_name or club.name, "email": club.email, "phone": club.phone, "street": club.street,
            "zip": club.zip, "city": club.city, "organizer": club.name}


def bookings(db, club: ResourceClub, upcoming: bool = True) -> list[ResourceBooking]:
    q = select(ResourceBooking).where(ResourceBooking.club_id == club.id)
    if upcoming:
        q = q.where(ResourceBooking.ends_at > utcnow(), ResourceBooking.status.in_(rs.ACTIVE)).order_by(ResourceBooking.starts_at)
    else:
        q = q.where(ResourceBooking.ends_at <= utcnow()).order_by(ResourceBooking.starts_at.desc()).limit(100)
    return list(db.scalars(q))


# --- Sammelrechnung ---------------------------------------------------------------------------

def month_range(month: str) -> tuple[datetime, datetime] | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})", month or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    first = date(int(m.group(1)), int(m.group(2)), 1)
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return rs._utc(datetime.combine(first, time())), rs._utc(datetime.combine(nxt, time()))


def open_items(db, club: ResourceClub, month: str) -> list[ResourceBooking]:
    """Bestätigte, noch nicht abgerechnete Buchungen mit Sammelrechnung, die im Monat beginnen."""
    span = month_range(month)
    if span is None:
        return []
    return list(db.scalars(select(ResourceBooking).where(
        ResourceBooking.club_id == club.id, ResourceBooking.billing == "monthly", ResourceBooking.status == "confirmed",
        ResourceBooking.billed_payment_id.is_(None), ResourceBooking.total_cents > 0,
        ResourceBooking.starts_at >= span[0], ResourceBooking.starts_at < span[1]).order_by(ResourceBooking.starts_at)))


def months_with_items(db, club: ResourceClub) -> list[str]:
    rows = db.scalars(select(ResourceBooking).where(
        ResourceBooking.club_id == club.id, ResourceBooking.billing == "monthly", ResourceBooking.status == "confirmed",
        ResourceBooking.billed_payment_id.is_(None), ResourceBooking.total_cents > 0)).all()
    return sorted({rs.to_local(b.starts_at).strftime("%Y-%m") for b in rows})


def bill(db, club: ResourceClub, month: str, user) -> object | None:
    items = open_items(db, club, month)
    if not items:
        return None
    first = items[0].resource
    label = datetime.strptime(month, "%Y-%m").strftime("%m/%Y")
    p = pay.create(db, kind="resource_club", subject_id=club.id, purpose=f"Sammelrechnung {label} {club.name}"[:255],
                   lines=[{"label": f"{b.ref} {b.resource.name}, {rs.when_text(b)}", "qty": 1, "unit_cents": b.total_cents - (b.deposit_cents if b.deposit_payment_id else 0)}
                          for b in items],
                   payer_name=club.name, payer_email=club.email, methods="transfer", cost_center=first.cost_center,
                   due_days=14, deposit_cents=sum(b.deposit_cents for b in items if not b.deposit_payment_id))
    for b in items:
        b.billed_payment_id = p.id
        rs._note(b, f"Abgerechnet mit Sammelrechnung {p.ref} durch {user.name}.")
    subject, body = mailtpl.render(db, "res_club_statement", {
        "name": club.contact_name or club.name, "verein": club.name, "monat": label,
        "positionen": "\n".join(f"– {b.ref} {b.resource.name}, {rs.when_text(b)}: {pay.money(b.total_cents)}" for b in items),
        "betrag": pay.money(p.amount_cents), "zahl_link": pay.link(p),
        "zahlbar_bis": rs.to_local(p.due_at).strftime("%d.%m.%Y") if p.due_at else ""})
    notify.enqueue(db, club.email, subject, body, "res_club_statement")
    return p


def _on_payment(db, p, event: str) -> None:
    if event == "paid":
        for b in db.scalars(select(ResourceBooking).where(ResourceBooking.billed_payment_id == p.id)):
            rs._note(b, f"Sammelrechnung {p.ref} bezahlt.")


pay.register("resource_club", event=_on_payment, can_manage=lambda db, user, p: user.can("resources"),
             link=lambda p: f"/resources/clubs/{p.subject_id}")
