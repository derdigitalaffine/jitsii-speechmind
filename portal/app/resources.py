"""Ressourcenbuchung: Bürgerhäuser, Räume, Grillplätze, Spülmobile …

Gebucht wird tageweise (auch mehrere Tage), in festen Zeitblöcken oder stundenweise – je Ressource einstellbar.
Teilräume lassen sich einzeln buchen; die ganze Ressource belegt alle Teilräume. Preise je Ressource bzw.
Teilraum, mit eigenen Preisen für Wochenende und Feiertage (siehe holidays.py), Tarifgruppen in Prozent,
Zusatzleistungen (pauschal, je Tag/Stunde/Stück, mit Bestand, auch Pflicht) und Kaution. Ablauf: Buchende
bestätigen ihre E-Mail-Adresse (Double-Opt-in), dann ist die Buchung je nach Ressource sofort fest oder wartet
auf die Freigabe der Verwaltung; bezahlt wird danach mit Frist (sonst verfällt die Reservierung).
"""

import io
import json
import math
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select

from . import holidays, links, mailtpl, notify, payments as pay, shares as sh
from .config import settings
from .db import (
    LOCAL_TZ, Group, GroupMember, Resource, ResourceBooking, ResourceClosure, ResourceExtra, SessionLocal, User,
    get_settings, to_local, utcnow,
)
from .planning import EMAIL_RE

MODES = {"day": ("Ganze Tage", "fa-calendar-day"), "block": ("Zeitblöcke", "fa-clock"), "hour": ("Stundenweise", "fa-hourglass-half")}
STATUSES = {
    "unconfirmed": ("E-Mail unbestätigt", "secondary", "fa-envelope"),
    "requested": ("Anfrage", "warning", "fa-hourglass-half"),
    "confirmed": ("bestätigt", "success", "fa-circle-check"),
    "rejected": ("abgelehnt", "danger", "fa-circle-xmark"),
    "cancelled": ("storniert", "dark", "fa-ban"),
    "expired": ("verfallen", "secondary", "fa-clock-rotate-left"),
}
ACTIVE = ("unconfirmed", "requested", "confirmed")
EXTRA_PER = {"once": "pauschal", "day": "je Tag", "hour": "je Stunde", "piece": "je Stück"}
UNCONFIRMED_HOURS = 24
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# --- Grundlagen -------------------------------------------------------------------------------

def _json(text, default):
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def blocks(res: Resource) -> list[dict]:
    return [b for b in _json(res.blocks_json, []) if isinstance(b, dict) and TIME_RE.match(str(b.get("start", "")))
            and TIME_RE.match(str(b.get("end", "")))]


def hours(res: Resource) -> dict:
    return _json(res.hours_json, {})


def modes(res: Resource) -> list[str]:
    return [m for m in (res.units or "").split(",") if m in MODES] or ["day"]


def fields(res: Resource) -> list[dict]:
    return _json(res.fields_json, [])


def unit_ids(b: ResourceBooking) -> set[int] | None:
    """None = ganze Ressource."""
    ids = {int(x) for x in (b.unit_ids or "").split(",") if x.isdigit()}
    return ids or None


def unit_label(res: Resource, ids: set[int] | None) -> str:
    if not res.parts or ids is None:
        return "gesamte Ressource" if res.parts else ""
    return ", ".join(u.name for u in res.parts if u.id in ids)


def extras_of(b: ResourceBooking) -> list[dict]:
    return _json(b.extras_json, [])


def lines_of(b: ResourceBooking) -> list[dict]:
    return _json(b.lines_json, [])


def answers_of(b: ResourceBooking) -> dict:
    return _json(b.answers_json, {})


def handover(b: ResourceBooking) -> dict:
    return _json(b.handover_json, {})


def _utc(local: datetime) -> datetime:
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _hm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def slug(text: str) -> str:
    s = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "ressource"


RESERVED = {"b", "cal"}


def unique_slug(db, text: str, own_id: int | None = None) -> str:
    base, n = slug(text), 1
    if base in RESERVED:
        base += "-1"
    candidate = base
    while True:
        other = db.scalar(select(Resource.id).where(Resource.slug == candidate))
        if other is None or other == own_id:
            return candidate
        n += 1
        candidate = f"{base}-{n}"


def when_text(b: ResourceBooking) -> str:
    s, e = to_local(b.starts_at), to_local(b.ends_at)
    if b.mode == "day":
        last = (e - timedelta(seconds=1)).date()
        return s.strftime("%d.%m.%Y") if last == s.date() else f"{s:%d.%m.%Y} bis {last:%d.%m.%Y}"
    return f"{s:%d.%m.%Y}, {s:%H:%M}–{e:%H:%M} Uhr"


# --- Rechte ----------------------------------------------------------------------------------

def level(db, user: User | None, res: Resource) -> int:
    """0 = kein Zugriff, 1 Belegung, 2 mit Kontaktdaten, 3 verwalten, 4 Besitzer:in/Admin."""
    if user is None or res is None:
        return 0
    lvl = sh.access_level(db, "resource", res, user)
    if lvl < 3 and (res.manager_user_id == user.id or (res.manager_group_id and db.scalar(
            select(GroupMember.user_id).where(GroupMember.group_id == res.manager_group_id, GroupMember.user_id == user.id)))):
        lvl = 3
    return lvl


def visible(db, user: User) -> list[tuple[Resource, int]]:
    out = []
    for res in db.scalars(select(Resource).order_by(Resource.position, Resource.name)):
        lvl = level(db, user, res)
        if lvl:
            out.append((res, lvl))
    return out


def staff_addresses(db, res: Resource) -> list[str]:
    out = []
    if res.manager_user and res.manager_user.active:
        out.append(res.manager_user.email)
    if res.manager_group:
        out += [u.email for u in res.manager_group.members if u.active]
    if res.mailbox:
        out.append(res.mailbox)
    if not out and res.owner and res.owner.active:
        out.append(res.owner.email)
    return list(dict.fromkeys(a.lower() for a in out if a))


# --- Zeitraum, Belegung, Preise ----------------------------------------------------------------

def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def span(res: Resource, data) -> dict:
    """Zeitraum aus den Eingaben. Gibt {mode, start, end (UTC), days, blocks, minutes, errors} zurück."""
    mode = str(data.get("mode") or modes(res)[0])
    out = {"mode": mode, "start": None, "end": None, "days": [], "blocks": [], "minutes": 0, "errors": []}
    if mode not in modes(res):
        out["errors"].append("Diese Buchungsart ist hier nicht möglich.")
        return out
    open_hours = hours(res)
    if mode == "day":
        d1 = _date(data.get("date_from") or data.get("date"))
        d2 = _date(data.get("date_to")) or d1
        if not d1:
            out["errors"].append("Bitte den Tag bzw. den ersten Tag wählen.")
            return out
        if d2 < d1:
            d1, d2 = d2, d1
        n = (d2 - d1).days + 1
        if n > max(1, res.max_days):
            out["errors"].append(f"Höchstens {max(1, res.max_days)} Tag(e) am Stück.")
        out["days"] = [d1 + timedelta(days=i) for i in range(n)]
        out["start"], out["end"] = _utc(datetime.combine(d1, time())), _utc(datetime.combine(d2 + timedelta(days=1), time()))
        out["minutes"] = n * 24 * 60
    elif mode == "block":
        d = _date(data.get("date"))
        all_blocks = blocks(res)
        ids = [str(x) for x in (data.getlist("blocks") if hasattr(data, "getlist") else data.get("blocks", []))]
        chosen = [i for i, b in enumerate(all_blocks) if str(b.get("id")) in ids]
        if not d or not chosen:
            out["errors"].append("Bitte Tag und mindestens einen Zeitblock wählen.")
            return out
        if chosen != list(range(chosen[0], chosen[-1] + 1)):
            out["errors"].append("Bitte aufeinanderfolgende Zeitblöcke wählen.")
        first, last = all_blocks[chosen[0]], all_blocks[chosen[-1]]
        start, end = datetime.combine(d, _hm(first["start"])), datetime.combine(d, _hm(last["end"]))
        if end <= start:
            end += timedelta(days=1)
        out["days"], out["blocks"] = [d], [all_blocks[i] for i in chosen]
        out["start"], out["end"] = _utc(start), _utc(end)
        out["minutes"] = int((end - start).total_seconds() // 60)
    else:
        d = _date(data.get("date"))
        t1, t2 = str(data.get("time_from", "")), str(data.get("time_to", ""))
        if not d or not TIME_RE.match(t1) or not TIME_RE.match(t2):
            out["errors"].append("Bitte Tag, Beginn und Ende angeben.")
            return out
        start, end = datetime.combine(d, _hm(t1)), datetime.combine(d, _hm(t2))
        if end <= start:
            out["errors"].append("Das Ende muss nach dem Beginn liegen.")
            return out
        minutes = int((end - start).total_seconds() // 60)
        slot = max(5, res.slot_minutes or 60)
        if (start.hour * 60 + start.minute) % slot or minutes % slot:
            out["errors"].append(f"Bitte im Raster von {slot} Minuten buchen.")
        if minutes < (res.min_minutes or 0):
            out["errors"].append(f"Mindestens {res.min_minutes} Minuten.")
        if res.max_minutes and minutes > res.max_minutes:
            out["errors"].append(f"Höchstens {res.max_minutes} Minuten.")
        ranges = open_hours.get(str(d.weekday()))
        if ranges is not None and not any(_hm(a) <= start.time() and (end.time() <= _hm(b) or b == "24:00")
                                          for a, b in ranges if TIME_RE.match(a) and (TIME_RE.match(b) or b == "24:00")):
            out["errors"].append("Außerhalb der Buchungszeiten.")
        out["days"], out["minutes"] = [d], minutes
        out["start"], out["end"] = _utc(start), _utc(end)
    for d in out["days"]:
        if open_hours.get(str(d.weekday())) == []:
            out["errors"].append(f"Am {d:%d.%m.%Y} ({['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'][d.weekday()]}) kann nicht gebucht werden.")
            break
    return out


def _blocking(db, res: Resource, start: datetime, end: datetime, exclude_id: int | None = None) -> list[ResourceBooking]:
    before, after = timedelta(minutes=res.buffer_before or 0), timedelta(minutes=res.buffer_after or 0)
    stale = utcnow() - timedelta(hours=UNCONFIRMED_HOURS)
    # (s - davor) < (Ende + danach) und (e + danach) > (Beginn - davor) – Puffer auf der Python-Seite (SQLite)
    q = select(ResourceBooking).where(
        ResourceBooking.resource_id == res.id, ResourceBooking.status.in_(ACTIVE),
        ResourceBooking.starts_at < end + after + before, ResourceBooking.ends_at > start - before - after,
        or_(ResourceBooking.status != "unconfirmed", ResourceBooking.created_at > stale))
    if exclude_id:
        q = q.where(ResourceBooking.id != exclude_id)
    return db.scalars(q).all()


def _overlap_units(a: set[int] | None, b: set[int] | None) -> bool:
    return a is None or b is None or bool(a & b)


def conflicts(db, res: Resource, ids: set[int] | None, start: datetime, end: datetime,
              exclude_id: int | None = None) -> list[str]:
    out = []
    for other in _blocking(db, res, start, end, exclude_id):
        if _overlap_units(ids, unit_ids(other)):
            out.append(f"Belegt: {when_text(other)}{' (' + unit_label(res, unit_ids(other)) + ')' if res.parts else ''}"
                       + (" – vorgemerkt" if other.status != "confirmed" else ""))
    for c in db.scalars(select(ResourceClosure).where(ResourceClosure.resource_id == res.id,
                                                      ResourceClosure.starts_at < end, ResourceClosure.ends_at > start)):
        if _overlap_units(ids, {c.unit_id} if c.unit_id else None):
            out.append(f"Gesperrt{': ' + c.reason if c.reason else ''} ({to_local(c.starts_at):%d.%m.%Y}–{to_local(c.ends_at):%d.%m.%Y})")
    return out


def _stock_used(db, res: Resource, extra: ResourceExtra, start: datetime, end: datetime, exclude_id: int | None) -> int:
    used = 0
    for other in _blocking(db, res, start, end, exclude_id):
        for e in extras_of(other):
            if e.get("id") == extra.id:
                used += int(e.get("qty", 0))
    return used


def _price(target, mode: str, special: bool) -> int:
    base = {"day": target.price_day, "block": target.price_block, "hour": target.price_hour}[mode] or 0
    wkd = {"day": target.wkd_day, "block": target.wkd_block, "hour": target.wkd_hour}[mode] or 0
    return wkd if special and wkd else base


def quote(db, res: Resource, data, staff: bool = False, exclude_id: int | None = None) -> dict:
    """Verfügbarkeit prüfen und Preis berechnen (eine Quelle für Vorschau, Buchung und Verwaltung)."""
    sp = span(res, data)
    errors = list(sp["errors"])
    raw_units = [int(x) for x in (data.getlist("units") if hasattr(data, "getlist") else data.get("units", []))
                 if str(x).isdigit()]
    known = {u.id: u for u in res.parts}
    ids = {u for u in raw_units if u in known} or None
    if res.parts and ids is not None and len(ids) == len(known):
        ids = None
    tariff = None
    tid = str(data.get("tariff", ""))
    if res.tariffs:
        tariff = next((t for t in res.tariffs if str(t.id) == tid), None)
        if tariff is None:
            if not staff and len(res.tariffs) > 1:
                errors.append("Bitte einen Tarif wählen.")
            tariff = res.tariffs[0]
    pct = tariff.percent if tariff else 100
    lines, warnings = [], []
    if sp["start"] and not sp["errors"]:
        now = utcnow()
        if not staff:
            if sp["start"] < now + timedelta(hours=res.min_notice_hours or 0):
                errors.append(f"Bitte mindestens {res.min_notice_hours} Stunden im Voraus buchen.")
            if sp["start"] > now + timedelta(days=res.max_advance_days or 365):
                errors.append(f"Höchstens {res.max_advance_days} Tage im Voraus buchbar.")
        errors += conflicts(db, res, ids, sp["start"], sp["end"], exclude_id)
        years = {d.year for d in sp["days"]}
        specials = {}
        for y in years:
            specials.update(holidays.special_days(db, y))
        targets = [known[i] for i in sorted(ids)] if ids else [res]
        hours_n = sp["minutes"] / 60
        for t in targets:
            name = t.name if ids else (f"{res.name} (gesamt)" if res.parts else res.name)
            tariff_txt = f" – {tariff.name}" if tariff and len(res.tariffs) > 1 else ""
            if sp["mode"] == "day":
                groups: dict[int, int] = {}
                for d in sp["days"]:
                    c = _price(t, "day", holidays.is_special(d, specials))
                    groups[c] = groups.get(c, 0) + 1
                for c, n in groups.items():
                    unit = round(c * pct / 100)
                    special = c != (t.price_day or 0)
                    lines.append({"label": f"{name}{tariff_txt}{' (Wochenende/Feiertag)' if special else ''}", "qty": n,
                                  "unit_cents": unit, "cents": unit * n, "kind": "rent", "unit": "Tag"})
            elif sp["mode"] == "block":
                special = holidays.is_special(sp["days"][0], specials)
                unit = round(_price(t, "block", special) * pct / 100)
                lines.append({"label": f"{name}{tariff_txt}: {', '.join(b['label'] for b in sp['blocks'])}"
                              + (" (Wochenende/Feiertag)" if special and t.wkd_block else ""),
                              "qty": len(sp["blocks"]), "unit_cents": unit, "cents": unit * len(sp["blocks"]), "kind": "rent",
                              "unit": "Block"})
            else:
                special = holidays.is_special(sp["days"][0], specials)
                unit = round(_price(t, "hour", special) * pct / 100)
                lines.append({"label": f"{name}{tariff_txt}" + (" (Wochenende/Feiertag)" if special and t.wkd_hour else ""),
                              "qty": round(hours_n, 2), "unit_cents": unit, "cents": round(unit * hours_n), "kind": "rent",
                              "unit": "Std."})
        days_n = len(sp["days"]) if sp["mode"] == "day" else 1
        chosen_extras = []
        for ex in res.extras:
            if not ex.active:
                continue
            raw = str(data.get(f"extra_{ex.id}", "") or "0")
            qty = int(raw) if raw.isdigit() else 0
            if ex.mandatory:
                qty = max(qty, 1)
            if not qty:
                continue
            if ex.per == "once":
                qty = 1
            qty = min(qty, max(1, ex.max_qty or 1))
            if ex.stock is not None:
                free = ex.stock - _stock_used(db, res, ex, sp["start"], sp["end"], exclude_id)
                if qty > free:
                    errors.append(f"„{ex.name}“: nur noch {max(0, free)} verfügbar.")
            factor = {"once": 1, "piece": qty, "day": qty * days_n, "hour": qty * hours_n}[ex.per]
            cents = round(ex.price_cents * factor)
            per = {"once": "", "piece": "", "day": f" × {days_n} Tag(e)", "hour": f" × {round(hours_n, 2)} Std."}[ex.per]
            lines.append({"label": f"{ex.name}{per}", "qty": qty, "unit_cents": ex.price_cents, "cents": cents, "kind": "extra"})
            chosen_extras.append({"id": ex.id, "name": ex.name, "qty": qty})
        if res.deposit_cents:
            lines.append({"label": "Kaution (wird nach der Rückgabe erstattet)", "qty": 1, "unit_cents": res.deposit_cents,
                          "cents": res.deposit_cents, "kind": "deposit"})
    else:
        chosen_extras = []
    persons = str(data.get("persons", "") or "0")
    cap = sum(known[i].capacity for i in ids) if ids else res.capacity
    if persons.isdigit() and cap and int(persons) > cap:
        warnings.append(f"Für bis zu {cap} Personen ausgelegt.")
    total = sum(line["cents"] for line in lines)
    deposit = sum(line["cents"] for line in lines if line["kind"] == "deposit")
    return {"ok": not errors and sp["start"] is not None, "errors": errors, "warnings": warnings, "lines": lines,
            "total": total, "deposit": deposit, "start": sp["start"], "end": sp["end"], "mode": sp["mode"],
            "unit_ids": ids, "tariff": tariff, "extras": chosen_extras,
            "when": when_text(ResourceBooking(starts_at=sp["start"], ends_at=sp["end"], mode=sp["mode"])) if sp["start"] else ""}


def quote_json(q: dict) -> dict:
    return {"ok": q["ok"], "errors": q["errors"], "warnings": q["warnings"], "when": q["when"],
            "lines": [{"label": ln["label"], "qty": ln["qty"], "cents": ln["cents"], "unit_cents": ln["unit_cents"],
                       "money": pay.money(ln["cents"]), "kind": ln["kind"]} for ln in q["lines"]],
            "total": pay.money(q["total"]), "deposit": pay.money(q["deposit"]), "total_cents": q["total"]}


# --- Buchung anlegen und Statuswechsel --------------------------------------------------------

def _next_ref(db) -> str:
    year = to_local(utcnow()).year
    head = f"RB-{year}-"
    n = db.scalar(select(func.count(ResourceBooking.id)).where(ResourceBooking.ref.like(head + "%"))) or 0
    while True:
        n += 1
        ref = f"{head}{n:05d}"
        if db.scalar(select(ResourceBooking.id).where(ResourceBooking.ref == ref)) is None:
            return ref


def contact_from(data) -> tuple[dict, list[str]]:
    c = {"name": " ".join(str(data.get("name", "")).split())[:255],
         "email": str(data.get("email", "")).strip().lower()[:255],
         "phone": " ".join(str(data.get("phone", "")).split())[:60],
         "street": " ".join(str(data.get("street", "")).split())[:255],
         "zip": re.sub(r"\D", "", str(data.get("zip", "")))[:10],
         "city": " ".join(str(data.get("city", "")).split())[:200],
         "title": " ".join(str(data.get("title", "")).split())[:255],
         "organizer": " ".join(str(data.get("organizer", "")).split())[:255]}
    persons = str(data.get("persons", "") or "0")
    c["persons"] = int(persons) if persons.isdigit() else 0
    errors = []
    if not c["name"]:
        errors.append("Bitte Ihren Namen angeben.")
    if not EMAIL_RE.match(c["email"] or "-"):
        errors.append("Bitte eine gültige E-Mail-Adresse angeben.")
    if not c["title"]:
        errors.append("Bitte den Anlass angeben.")
    return c, errors


def create(db, res: Resource, q: dict, contact: dict, answers: dict, *, internal: bool = False, by: str = "",
           free: bool = False, series_id: str = "") -> ResourceBooking:
    lines = [] if free else q["lines"]
    b = ResourceBooking(ref=_next_ref(db), resource_id=res.id, mode=q["mode"], starts_at=q["start"], ends_at=q["end"],
                        unit_ids=",".join(str(i) for i in sorted(q["unit_ids"])) if q["unit_ids"] else "",
                        tariff_id=q["tariff"].id if q["tariff"] else None, tariff_name=q["tariff"].name if q["tariff"] else "",
                        extras_json=json.dumps(q["extras"], ensure_ascii=False), answers_json=json.dumps(answers, ensure_ascii=False),
                        lines_json=json.dumps(lines, ensure_ascii=False), total_cents=0 if free else q["total"],
                        deposit_cents=0 if free else q["deposit"], token=secrets.token_urlsafe(24),
                        confirm_code=secrets.token_urlsafe(12), internal=internal, created_by=by[:255], series_id=series_id,
                        status="confirmed" if internal else "unconfirmed", **contact)
    db.add(b)
    db.flush()
    return b


def manage_link(b: ResourceBooking) -> str:
    return f"{links.base('resources')}/r/b/{b.token}"


def _values(db, b: ResourceBooking, extra: dict | None = None) -> dict:
    res = b.resource
    cfg = get_settings(db)
    lines = "\n".join(f"– {ln['label']}: {pay.money(ln['cents'])}" for ln in lines_of(b))
    return {"name": b.name, "ressource": res.name, "teilraeume": unit_label(res, unit_ids(b)), "zeitraum": when_text(b),
            "anlass": b.title, "buchungsnummer": b.ref, "link": manage_link(b), "betrag": pay.money(b.total_cents),
            "positionen": lines, "ort": res.location, "nachricht": b.message,
            "bestaetigen_link": f"{manage_link(b)}/confirm/{b.confirm_code}",
            "zahl_link": pay.link(b.payment) if b.payment else "", "zahlbar_bis":
            to_local(b.payment.due_at).strftime("%d.%m.%Y") if b.payment and b.payment.due_at else "",
            "storno": cancel_rules_text(res), "organisation_mail": cfg.get("mail_from", ""), **(extra or {})}


def _mail(db, b: ResourceBooking, key: str, extra: dict | None = None, attach_pdf: bool = False) -> bool:
    if not b.email:
        return False
    subject, body = mailtpl.render(db, key, _values(db, b, extra))
    attachments = None
    if attach_pdf:
        import base64
        attachments = [{"filename": f"Buchung-{b.ref}.pdf", "mime": "application/pdf",
                        "content_b64": base64.b64encode(confirmation_pdf(db, b)).decode("ascii")}]
    return notify.enqueue(db, b.email, subject, body, key, attachments=attachments)


def _staff_mail(db, b: ResourceBooking, event: str) -> int:
    n = 0
    for addr in staff_addresses(db, b.resource):
        subject, body = mailtpl.render(db, "res_staff", _values(db, b, {
            "ereignis": event, "verwalten_link": f"{settings.portal_base_url}/resources/bookings/{b.id}",
            "kontakt": f"{b.name} <{b.email}>{', ' + b.phone if b.phone else ''}"}))
        n += notify.enqueue(db, addr, subject, body, "res_staff", reply_to=b.email or None)
    return n


def send_confirm_mail(db, b: ResourceBooking) -> bool:
    return _mail(db, b, "res_confirm_email")


def confirm_email(db, b: ResourceBooking) -> str:
    """Klick auf den Link aus der Mail. Gibt den neuen Status zurück."""
    if b.status != "unconfirmed":
        return b.status
    res = b.resource
    if conflicts(db, res, unit_ids(b), b.starts_at, b.ends_at, exclude_id=b.id):
        b.status = "expired"
        _note(b, "Bei der Bestätigung war der Zeitraum inzwischen belegt.")
        return b.status
    if res.mode == "instant":
        b.status = "confirmed"
        b.decided_at, b.decided_by = utcnow(), "automatisch (Sofortbuchung)"
        _finalize(db, b)
        _staff_mail(db, b, "Neue Buchung (sofort bestätigt)")
    else:
        b.status = "requested"
        _mail(db, b, "res_received")
        _staff_mail(db, b, "Neue Anfrage – bitte bestätigen oder ablehnen")
    sync_dms(db, b)
    return b.status


def _note(b: ResourceBooking, text: str) -> None:
    stamp = to_local(utcnow()).strftime("%d.%m.%Y %H:%M")
    b.note = (b.note + f"\n[{stamp}] {text}").strip()


def _finalize(db, b: ResourceBooking) -> None:
    """Bestätigt: Zahlung anlegen (mit Frist), Bestätigung mit PDF schicken, ablegen."""
    res = b.resource
    if b.total_cents > 0 and b.payment_id is None:
        days_left = max(1, (to_local(b.starts_at).date() - to_local(utcnow()).date()).days - 1)
        p = pay.create(db, kind="resource", subject_id=b.id, purpose=f"{res.name}, {when_text(b)} ({b.ref})",
                       lines=[{"label": ln["label"], "qty": 1, "unit_cents": ln["cents"]} for ln in lines_of(b)],
                       payer_name=b.name, payer_email=b.email, methods=res.pay_methods or "paypal,transfer",
                       cost_center=res.cost_center, due_days=min(res.pay_days or 7, days_left),
                       back_url=f"/r/b/{b.token}", deposit_cents=b.deposit_cents)
        b.payment_id = p.id
        db.flush()
        db.refresh(b, ["payment"])
    _mail(db, b, "res_confirmed", attach_pdf=True)
    sync_dms(db, b, with_pdf=True)


def decide(db, b: ResourceBooking, user: User, accept: bool, message: str = "") -> bool:
    if b.status not in ("requested", "unconfirmed"):
        return False
    b.message = message.strip()[:2000]
    b.decided_at, b.decided_by = utcnow(), user.name
    if accept:
        if conflicts(db, b.resource, unit_ids(b), b.starts_at, b.ends_at, exclude_id=b.id):
            return False
        b.status = "confirmed"
        _finalize(db, b)
    else:
        b.status = "rejected"
        _mail(db, b, "res_rejected")
        sync_dms(db, b)
    return True


def cancel_rules_text(res: Resource) -> str:
    if not res.self_cancel:
        return "Eine Stornierung ist nur über die Verwaltung möglich."
    if not res.cancel_fee_percent:
        return "Sie können bis zum Beginn kostenlos stornieren."
    return (f"Bis {res.cancel_free_days} Tage vor Beginn kostenlos, danach werden {res.cancel_fee_percent} % der Kosten "
            "(ohne Kaution) einbehalten.")


def cancel_fee(b: ResourceBooking) -> int:
    res = b.resource
    if not res.cancel_fee_percent or b.status != "confirmed":
        return 0
    days = (to_local(b.starts_at).date() - to_local(utcnow()).date()).days
    if days >= (res.cancel_free_days or 0):
        return 0
    return round((b.total_cents - b.deposit_cents) * res.cancel_fee_percent / 100)


def can_self_cancel(b: ResourceBooking) -> bool:
    return b.resource.self_cancel and b.status in ACTIVE and b.starts_at > utcnow()


def cancel(db, b: ResourceBooking, by: str, reason: str = "", staff: bool = False, waive_fee: bool = False) -> str:
    """Stornieren. Bezahltes wird (abzüglich Gebühr) erstattet, Offenes storniert. Gibt einen Hinweistext zurück."""
    if b.status not in ACTIVE:
        return ""
    fee = 0 if (staff and waive_fee) or staff else cancel_fee(b)
    info = ""
    p = b.payment
    if p is not None:
        if p.status in ("paid", "partially_refunded"):
            back = p.amount_cents - p.refunded_cents - fee
            if back > 0:
                err = pay.refund(db, p, back, by, f"Stornierung {b.ref}", fire=False)
                info = f"Erstattet werden {pay.money(back)}." if not err else f"Erstattung bitte von Hand prüfen: {err}"
            if fee:
                info += f" Einbehalten: {pay.money(fee)} Stornogebühr."
        elif p.status in ("open", "pending"):
            pay.cancel(db, p, by, f"Buchung {b.ref} storniert", fire=False)
            if fee:
                fp = pay.create(db, kind="resource", subject_id=b.id, purpose=f"Stornogebühr {b.ref}",
                                lines=[{"label": f"Stornogebühr ({b.resource.cancel_fee_percent} %)", "unit_cents": fee}],
                                payer_name=b.name, payer_email=b.email, methods=b.resource.pay_methods,
                                cost_center=b.resource.cost_center, back_url=f"/r/b/{b.token}")
                b.payment_id = fp.id
                pay.request_payment(db, fp)
                info = f"Stornogebühr: {pay.money(fee)} (Zahlungsaufforderung folgt)."
    b.status, b.cancelled_at = "cancelled", utcnow()
    _note(b, f"Storniert von {by}{': ' + reason if reason else ''}. {info}".strip())
    _mail(db, b, "res_cancelled", {"grund": reason, "erstattung": info})
    if not staff:
        _staff_mail(db, b, "Storniert durch die buchende Person")
    sync_dms(db, b)
    return info


def record_handover(db, b: ResourceBooking, user: User, part: str, data) -> str:
    """Übergabe (Schlüssel, Zustand) und Abnahme (Schäden, Kaution zurück/einbehalten)."""
    h = handover(b)
    entry = {"at": utcnow().isoformat(timespec="minutes"), "by": user.name,
             "note": str(data.get("note", "")).strip()[:2000]}
    info = ""
    if part == "out":
        entry["keys"] = " ".join(str(data.get("keys", "")).split())[:200]
        h["out"] = entry
    else:
        entry["damages"] = str(data.get("damages", "")).strip()[:2000]
        keep = pay.parse_amount(data.get("keep", "")) or 0
        entry["keep_cents"] = min(keep, b.deposit_cents)
        h["back"] = entry
        p = b.payment
        back = b.deposit_cents - entry["keep_cents"]
        if back > 0 and p is not None and p.status in ("paid", "partially_refunded") and not h.get("deposit_done"):
            err = pay.refund(db, p, back, user.name, f"Kaution {b.ref}" + (f", {pay.money(entry['keep_cents'])} einbehalten" if entry["keep_cents"] else ""), fire=False)
            info = err or f"Kaution {pay.money(back)} erstattet."
            if not err:
                h["deposit_done"] = True
        elif b.deposit_cents and (p is None or p.status not in ("paid", "partially_refunded")):
            info = "Kaution war nicht bezahlt – nichts zu erstatten."
    b.handover_json = json.dumps(h, ensure_ascii=False)
    _note(b, ("Übergabe" if part == "out" else "Abnahme") + f" durch {user.name}. {info}".strip())
    sync_dms(db, b)
    return info


def on_payment(db, p, event: str) -> None:
    b = db.get(ResourceBooking, p.subject_id) if p.subject_id else None
    if b is None or b.payment_id != p.id:
        return
    if event == "paid":
        _note(b, f"Zahlung {p.ref} eingegangen ({pay.METHODS.get(p.method, ('',))[0]}).")
        sync_dms(db, b)
    elif event == "overdue" and b.status == "confirmed" and b.starts_at > utcnow() - timedelta(days=1):
        pay.cancel(db, p, "Portal", "Zahlfrist abgelaufen", fire=False)
        b.status = "expired"
        _note(b, "Zahlfrist abgelaufen – Reservierung verfallen.")
        _mail(db, b, "res_expired")
        _staff_mail(db, b, "Nicht bezahlt – Reservierung verfallen")
        sync_dms(db, b)


def _can_manage_payment(db, user, p) -> bool:
    b = db.get(ResourceBooking, p.subject_id) if p.subject_id else None
    return b is not None and level(db, user, b.resource) >= 3


pay.register("resource", event=on_payment, can_manage=_can_manage_payment,
             link=lambda p: f"/resources/bookings/{p.subject_id}")


def expire_unconfirmed() -> int:
    """Hintergrunddienst: nicht bestätigte Buchungen nach 24 Stunden verfallen lassen."""
    n = 0
    with SessionLocal() as db:
        for b in db.scalars(select(ResourceBooking).where(
                ResourceBooking.status == "unconfirmed",
                ResourceBooking.created_at < utcnow() - timedelta(hours=UNCONFIRMED_HOURS))):
            b.status = "expired"
            _note(b, "E-Mail-Adresse nicht innerhalb von 24 Stunden bestätigt.")
            n += 1
        db.commit()
    return n


# --- Ablage (DMS) ------------------------------------------------------------------------------

def sync_dms(db, b: ResourceBooking, with_pdf: bool = False) -> None:
    from . import dms
    from .db import DmsArea, DmsRecord
    if b.internal and not b.email or not dms.enabled(db):
        return
    res = b.resource
    record = db.scalar(select(DmsRecord).where(DmsRecord.booking_id == b.id))
    if record is None:
        if b.status == "unconfirmed":
            return
        area_id = res.dms_area_id if res.dms_area_id and db.get(DmsArea, res.dms_area_id) else dms.unsorted(db).id
        record = DmsRecord(area_id=area_id, kind="buchung", booking_id=b.id, received_at=b.created_at,
                           created_by="Ressourcenbuchung")
        db.add(record)
    record.title = f"Buchung {res.name}: {b.title}"[:300]
    record.ref_no, record.form_title = b.ref, f"Buchung {res.name}"[:255]
    record.applicant, record.applicant_email = b.name, b.email
    record.status = STATUSES[b.status][0][:16]
    record.street, record.zip, record.city = b.street, b.zip, b.city
    record.lat, record.lon = res.lat, res.lon
    record.note = f"{when_text(b)} · {unit_label(res, unit_ids(b)) or res.name} · {pay.money(b.total_cents)}"
    record.text = " ".join([b.ref, res.name, b.title, b.organizer, b.name, b.email, b.street, b.zip, b.city,
                            when_text(b), b.note or ""]).lower()
    if b.status in ("rejected", "cancelled", "expired"):
        record.closed_at = b.cancelled_at or b.decided_at or utcnow()
    elif b.status == "confirmed":
        record.closed_at = b.ends_at
    if record.closed_at:
        by_id = {a.id: a for a in dms.areas(db)}
        area = by_id.get(record.area_id)
        record.retention_until = dms.retention_date(record.closed_at, dms.retention_years(area, by_id)) if area else None
    if record.person_id is None:
        record.person = dms.match_person(db, b.name, b.email, b.street, b.zip, b.city, phone=b.phone)
        db.flush()
        b.person_id = record.person_id
    if with_pdf:
        db.flush()
        dms._store(record, f"Buchungsbestätigung {b.ref}.pdf", confirmation_pdf(db, b), "dokument", "Ressourcenbuchung",
                   "bei Bestätigung", "application/pdf")
    record.updated_at = utcnow()


# --- PDF ---------------------------------------------------------------------------------------

def confirmation_pdf(db, b: ResourceBooking) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from . import branding
    res = b.resource
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title=f"Buchung {b.ref}")
    P = lambda t, s="Normal": Paragraph(escape(str(t)).replace("\n", "<br/>"), styles[s])  # noqa: E731
    title = "Buchungsbestätigung" if b.status == "confirmed" else f"Buchung ({STATUSES[b.status][0]})"
    story = [P(branding.load()["name"]), P(title, "Title"),
             P(f"{b.name}" + (f"\n{b.organizer}" if b.organizer else "") + (f"\n{b.street}\n{b.zip} {b.city}" if b.street else ""))]
    meta = [["Buchungsnummer", b.ref], ["Ressource", res.name + (f" – {unit_label(res, unit_ids(b))}" if res.parts else "")],
            ["Zeitraum", when_text(b)], ["Anlass", b.title or "–"]]
    if res.location:
        meta.append(["Ort", res.location])
    if b.persons:
        meta.append(["Personen", str(b.persons)])
    if b.tariff_name:
        meta.append(["Tarif", b.tariff_name])
    t = Table(meta, colWidths=[40 * mm, 130 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TEXTCOLOR", (0, 0), (0, -1), colors.grey)]))
    story += [Spacer(1, 4 * mm), t, Spacer(1, 6 * mm)]
    rows = [["Posten", "Betrag"]] + [[Paragraph(escape(ln["label"]), styles["Normal"]), pay.money(ln["cents"])]
                                      for ln in lines_of(b)] + [["Summe", pay.money(b.total_cents)]]
    t = Table(rows, colWidths=[140 * mm, 30 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey), ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]))
    story.append(t)
    p = b.payment
    if p is not None:
        cfg = get_settings(db)
        state = pay.STATUSES.get(p.status, (p.status,))[0]
        txt = f"Zahlung {p.ref}: {state}."
        if p.status in ("open", "pending"):
            txt += f" Bitte bis {to_local(p.due_at):%d.%m.%Y} bezahlen: {pay.link(p)}" if p.due_at else f" {pay.link(p)}"
            if pay.transfer_ready(cfg) and "transfer" in (p.methods or ""):
                txt += f"\nÜberweisung an {cfg.get('pay_recipient', '')}, IBAN {cfg.get('pay_iban')}, Verwendungszweck {p.ref}."
        story += [Spacer(1, 4 * mm), P(txt)]
    story += [Spacer(1, 4 * mm), P("Stornierung: " + cancel_rules_text(res))]
    if res.terms_text:
        story += [Spacer(1, 3 * mm), P("Nutzungsbedingungen:", "Heading4"), P(res.terms_text[:4000])]
    story += [Spacer(1, 6 * mm), P(f"Ihre Buchung online: {manage_link(b)}")]
    doc.build(story)
    return buf.getvalue()


# --- Kalender (Portal, Web-Ansicht, iCal) ----------------------------------------------------

def calendar_events(db, resources: list[Resource], start: datetime, end: datetime, detail: str,
                    tentative: bool = True, staff_links: bool = False) -> list[dict]:
    """detail: busy | title | full"""
    by_id = {r.id: r for r in resources}
    if not by_id:
        return []
    states = ("requested", "confirmed") if tentative else ("confirmed",)
    out = []
    q = select(ResourceBooking).where(ResourceBooking.resource_id.in_(by_id), ResourceBooking.status.in_(states),
                                      ResourceBooking.starts_at < end, ResourceBooking.ends_at > start)
    for b in db.scalars(q.order_by(ResourceBooking.starts_at)):
        res = by_id[b.resource_id]
        units = unit_label(res, unit_ids(b))
        prefix = " · ".join(x for x in ((res.name if len(by_id) > 1 else ""), (units if res.parts else "")) if x)
        if detail == "busy":
            title = "belegt" if b.status == "confirmed" else "vorgemerkt"
        else:
            title = b.title or "belegt"
            if b.organizer:
                title += f" ({b.organizer})"
        if prefix:
            title = f"{prefix}: {title}".lstrip(": ")
        ev = {"id": b.id, "title": title, "start": b.starts_at, "end": b.ends_at, "allDay": b.mode == "day",
              "tentative": b.status != "confirmed", "resource": res.name, "units": units, "ref": b.ref}
        if detail == "full":
            ev["description"] = "\n".join(x for x in (
                f"Buchung {b.ref}", f"{b.name}" + (f", {b.organizer}" if b.organizer else ""), b.phone, b.email,
                f"{b.street}, {b.zip} {b.city}".strip(", "), f"Personen: {b.persons}" if b.persons else "",
                ("Zusatzleistungen: " + ", ".join(f"{e['qty']}× {e['name']}" for e in extras_of(b))) if extras_of(b) else "",
            ) if x)
        if staff_links:
            ev["url"] = f"/resources/bookings/{b.id}"
        out.append(ev)
    for c in db.scalars(select(ResourceClosure).where(ResourceClosure.resource_id.in_(by_id),
                                                      ResourceClosure.starts_at < end, ResourceClosure.ends_at > start)):
        out.append({"id": f"c{c.id}", "title": f"gesperrt{': ' + c.reason if c.reason and detail != 'busy' else ''}",
                    "start": c.starts_at, "end": c.ends_at, "allDay": False, "closure": True, "tentative": False,
                    "resource": by_id[c.resource_id].name, "units": "", "ref": ""})
    return out


def fc_events(events: list[dict]) -> list[dict]:
    """Für FullCalendar (lokale Zeit, ISO)."""
    out = []
    for e in events:
        s, en = to_local(e["start"]), to_local(e["end"])
        item = {"id": str(e["id"]), "title": e["title"], "allDay": e["allDay"],
                "start": s.date().isoformat() if e["allDay"] else s.isoformat(timespec="minutes"),
                "end": en.date().isoformat() if e["allDay"] else en.isoformat(timespec="minutes"),
                "classNames": ["res-ev"] + (["res-tentative"] if e.get("tentative") else []) + (["res-closure"] if e.get("closure") else [])}
        if e.get("url"):
            item["url"] = e["url"]
        if e.get("description"):
            item["extendedProps"] = {"description": e["description"]}
        out.append(item)
    return out


def ics(events: list[dict], name: str) -> bytes:
    from icalendar import Calendar, Event
    cal = Calendar()
    cal.add("prodid", "-//jitsii-speechmind//Ressourcen//DE")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", name)
    cal.add("refresh-interval;value=duration", "PT1H")
    host = settings.portal_base_url.split("//", 1)[-1].split("/")[0]
    for e in events:
        ev = Event()
        ev.add("uid", f"res-{e['id']}@{host}")
        ev.add("summary", e["title"])
        if e["allDay"]:
            ev.add("dtstart", to_local(e["start"]).date())
            ev.add("dtend", to_local(e["end"]).date())
        else:
            ev.add("dtstart", e["start"].replace(tzinfo=timezone.utc))
            ev.add("dtend", e["end"].replace(tzinfo=timezone.utc))
        ev.add("dtstamp", utcnow().replace(tzinfo=timezone.utc))
        ev.add("status", "TENTATIVE" if e.get("tentative") else "CONFIRMED")
        ev.add("transp", "OPAQUE")
        loc = e["resource"] + (f" – {e['units']}" if e.get("units") else "")
        ev.add("location", loc)
        if e.get("description"):
            ev.add("description", e["description"])
        cal.add_component(ev)
    return cal.to_ical()


def money_input(cents: int | None) -> str:
    return f"{(cents or 0) / 100:.2f}".replace(".", ",") if cents else ""


def parse_cents(value) -> int:
    return pay.parse_amount(value) or 0


def users_in_groups(db, group_id: int) -> list[User]:
    g = db.get(Group, group_id)
    return list(g.members) if g else []


def booking_counts(db, res_ids: list[int]) -> dict:
    now = utcnow()
    if not res_ids:
        return {"requested": [], "today_out": [], "today_back": [], "unpaid": 0}
    today = to_local(now).date()
    day_start, day_end = _utc(datetime.combine(today, time())), _utc(datetime.combine(today + timedelta(days=1), time()))
    base = select(ResourceBooking).where(ResourceBooking.resource_id.in_(res_ids))
    requested = db.scalars(base.where(ResourceBooking.status == "requested").order_by(ResourceBooking.starts_at)).all()
    out = db.scalars(base.where(ResourceBooking.status == "confirmed", ResourceBooking.starts_at >= day_start,
                                ResourceBooking.starts_at < day_end)).all()
    back = db.scalars(base.where(ResourceBooking.status == "confirmed", ResourceBooking.ends_at > day_start,
                                 ResourceBooking.ends_at <= day_end)).all()
    from .db import Payment
    unpaid = db.scalar(select(func.count(ResourceBooking.id)).join(Payment, Payment.id == ResourceBooking.payment_id).where(
        ResourceBooking.resource_id.in_(res_ids), ResourceBooking.status == "confirmed",
        Payment.status.in_(("open", "pending")))) or 0
    return {"requested": requested, "today_out": out, "today_back": back, "unpaid": unpaid}


def ceil_div(a: int, b: int) -> int:
    return math.ceil(a / b) if b else 0
