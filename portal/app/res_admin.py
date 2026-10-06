"""Ressourcenbuchung – Werkzeuge der Verwaltung: Auswertung, CSV-Export, Ressource kopieren, als Datei
ex- und importieren und Vorlagen für neue Ressourcen."""

import base64
import csv
import io
import json
import secrets
from calendar import monthrange
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from . import payments as pay, resources as rs
from .config import settings
from .db import (
    Resource, ResourceBooking, ResourceExtra, ResourcePhoto, ResourceTariff, ResourceUnit, to_local, utcnow,
)

FORMAT = "jitsii-ressource-1"
FIELDS = ("name", "category", "description", "location", "lat", "lon", "capacity", "equipment", "public", "mode",
          "units", "blocks_json", "hours_json", "slot_minutes", "min_minutes", "max_minutes", "max_days",
          "min_notice_hours", "max_advance_days", "buffer_before", "buffer_after", "price_day", "price_block",
          "price_hour", "wkd_day", "wkd_block", "wkd_hour", "deposit_cents", "pay_methods", "pay_days", "cost_center",
          "self_cancel", "cancel_free_days", "cancel_fee_percent", "fields_json", "terms_text", "remind_days",
          "remind_staff_days", "remind_text", "waitlist")
UNIT_FIELDS = ("name", "description", "capacity", "position", "price_day", "price_block", "price_hour", "wkd_day",
               "wkd_block", "wkd_hour")
TARIFF_FIELDS = ("name", "percent", "description", "needs_proof", "position")
EXTRA_FIELDS = ("name", "description", "price_cents", "per", "stock", "max_qty", "mandatory", "active", "position")

# Vorlagen für den Einrichtungsassistenten: sinnvolle Startwerte je Art
PRESETS = {
    "hall": {"label": "Bürgerhaus / Saal", "icon": "fa-building-columns", "category": "Bürgerhaus",
             "hint": "tageweise, mit Freigabe, Kaution, Endreinigung",
             "values": {"units": "day", "mode": "request", "max_days": 3, "min_notice_hours": 72, "max_advance_days": 540,
                        "price_day": 25000, "deposit_cents": 20000, "remind_days": 3},
             "extras": [("Endreinigung", "once", 8000, True), ("Geschirr und Besteck", "once", 3000, False)]},
    "room": {"label": "Besprechungs- / Gruppenraum", "icon": "fa-door-open", "category": "Veranstaltungsraum",
             "hint": "stundenweise 8–22 Uhr, sofort buchbar",
             "values": {"units": "hour", "mode": "instant", "slot_minutes": 30, "min_minutes": 60, "max_minutes": 480,
                        "min_notice_hours": 24, "price_hour": 1500, "remind_days": 1,
                        "hours_json": json.dumps({str(d): [["08:00", "22:00"]] for d in range(7)})}},
    "grill": {"label": "Grillplatz / Außenanlage", "icon": "fa-fire-burner", "category": "Grillplatz",
              "hint": "Zeitblöcke (Mittag, Abend) oder ganzer Tag",
              "values": {"units": "block,day", "mode": "request", "max_days": 1, "price_block": 4000, "price_day": 7000,
                         "deposit_cents": 5000,
                         "blocks_json": json.dumps([{"id": "mittag", "label": "Mittag", "start": "10:00", "end": "16:00"},
                                                    {"id": "abend", "label": "Abend", "start": "16:00", "end": "23:00"}])}},
    "device": {"label": "Gerät / Spülmobil / Ausleihe", "icon": "fa-truck-ramp-box", "category": "Gerät",
               "hint": "tageweise, Abholung und Rückgabe, Kaution",
               "values": {"units": "day", "mode": "request", "max_days": 7, "price_day": 5000, "deposit_cents": 10000,
                          "remind_days": 2, "remind_text": "Bitte holen Sie das Gerät zur vereinbarten Zeit ab."}},
    "vehicle": {"label": "Fahrzeug / Dienstwagen (intern)", "icon": "fa-car", "category": "Fahrzeug",
                "hint": "stundenweise, nur intern, kostenlos",
                "values": {"units": "hour,day", "mode": "instant", "public": False, "slot_minutes": 30, "min_minutes": 30,
                           "min_notice_hours": 0, "max_days": 5, "remind_days": 1}},
    "empty": {"label": "Leer beginnen", "icon": "fa-file", "category": "", "hint": "alle Einstellungen selbst festlegen",
              "values": {}},
}


def apply_preset(res: Resource, key: str) -> None:
    preset = PRESETS.get(key) or PRESETS["empty"]
    for k, v in preset["values"].items():
        setattr(res, k, v)
    if preset["category"] and not res.category:
        res.category = preset["category"]
    for pos, (name, per, cents, mandatory) in enumerate(preset.get("extras", [])):
        res.extras.append(ResourceExtra(name=name, per=per, price_cents=cents, mandatory=mandatory, position=pos))


def checklist(res: Resource) -> list[tuple[str, bool, str]]:
    """Was vor dem Freischalten erledigt sein sollte: (Text, erledigt, Reiter)."""
    priced = any((res.price_day, res.price_block, res.price_hour)) or any(
        (u.price_day or u.price_block or u.price_hour) for u in res.parts)
    return [
        ("Beschreibung und Ort", bool(res.description and res.location), "allgemein"),
        ("Fotos", bool(res.photos), "fotos"),
        ("Buchungsart und Regeln", bool(res.units), "zeiten"),
        ("Zeitblöcke festgelegt", "block" not in rs.modes(res) or bool(rs.blocks(res)), "zeiten"),
        ("Preise (oder bewusst kostenlos)", priced, "preise"),
        ("Zuständigkeit (Person, Gruppe oder Postfach)", bool(res.manager_user_id or res.manager_group_id or res.mailbox), "zustaendig"),
        ("Nutzungsbedingungen", bool(res.terms_text or res.terms_file), "fotos"),
        ("Freigeschaltet", res.active, "allgemein"),
    ]


# --- Auswertung --------------------------------------------------------------------------------

def stats(db, resources: list[Resource], year: int) -> dict:
    """Je Ressource und Monat: Buchungen, Belegungstage, Auslastung, Einnahmen (ohne Kaution), Stornos."""
    start = rs._utc(datetime.combine(date(year, 1, 1), time()))
    end = rs._utc(datetime.combine(date(year + 1, 1, 1), time()))
    ids = [r.id for r in resources]
    rows = db.scalars(select(ResourceBooking).where(ResourceBooking.resource_id.in_(ids or [-1]),
                                                    ResourceBooking.starts_at >= start, ResourceBooking.starts_at < end)).all()
    out = {r.id: {"months": [{"bookings": 0, "days": set(), "hours": 0.0, "revenue": 0, "cancelled": 0} for _ in range(12)],
                  "resource": r} for r in resources}
    for b in rows:
        m = out[b.resource_id]["months"][to_local(b.starts_at).month - 1]
        if b.status in ("cancelled", "rejected", "expired"):
            m["cancelled"] += b.status == "cancelled"
            continue
        if b.status != "confirmed":
            continue
        m["bookings"] += 1
        m["revenue"] += b.total_cents - b.deposit_cents
        s, e = to_local(b.starts_at), to_local(b.ends_at)
        m["hours"] += (e - s).total_seconds() / 3600
        d = s.date()
        while datetime.combine(d, time()) < e.replace(tzinfo=None):
            if d.year == year:
                out[b.resource_id]["months"][d.month - 1]["days"].add(d)
            d += timedelta(days=1)
    totals = {"bookings": 0, "revenue": 0, "cancelled": 0}
    for item in out.values():
        for n, m in enumerate(item["months"]):
            days_in = monthrange(year, n + 1)[1]
            m["days"] = len(m["days"])
            m["load"] = round(100 * m["days"] / days_in)
            m["hours"] = round(m["hours"], 1)
        item["sum"] = {k: sum(m[k] for m in item["months"]) for k in ("bookings", "days", "revenue", "cancelled")}
        item["sum"]["load"] = round(100 * item["sum"]["days"] / (366 if year % 4 == 0 else 365))
        for k in totals:
            totals[k] += item["sum"][k]
    return {"items": list(out.values()), "totals": totals}


def stats_csv(data: dict, year: int) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Ressource", "Monat", "Buchungen", "Belegungstage", "Auslastung %", "Stunden", "Einnahmen (EUR)", "Stornos"])
    for item in data["items"]:
        for n, m in enumerate(item["months"]):
            w.writerow([item["resource"].name, f"{year}-{n + 1:02d}", m["bookings"], m["days"], m["load"],
                        str(m["hours"]).replace(".", ","), f"{m['revenue'] / 100:.2f}".replace(".", ","), m["cancelled"]])
    return "﻿" + buf.getvalue()


def bookings_csv(rows: list[ResourceBooking], with_contact: dict[int, bool]) -> str:
    """Buchungsliste für Kasse/Buchhaltung (Excel-freundlich: Semikolon, BOM)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Buchungsnummer", "Ressource", "Räume", "Beginn", "Ende", "Status", "Anlass", "Veranstalter", "Personen",
                "Name", "E-Mail", "Telefon", "Anschrift", "Tarif", "Betrag (EUR)", "Kaution (EUR)", "Zahlung", "Zahlungsnr.",
                "Kostenstelle", "Verein", "Abrechnung", "Sammelbuchung", "Serie", "intern", "angelegt"])
    for b in rows:
        res, contact = b.resource, with_contact.get(b.resource_id, False)
        p = b.payment
        w.writerow([b.ref, res.name, rs.unit_label(res, rs.unit_ids(b)), to_local(b.starts_at).strftime("%d.%m.%Y %H:%M"),
                    to_local(b.ends_at).strftime("%d.%m.%Y %H:%M"), rs.STATUSES[b.status][0], b.title, b.organizer,
                    b.persons or "", b.name if contact else "", b.email if contact else "", b.phone if contact else "",
                    f"{b.street}, {b.zip} {b.city}".strip(", ") if contact else "", b.tariff_name,
                    f"{b.total_cents / 100:.2f}".replace(".", ","), f"{b.deposit_cents / 100:.2f}".replace(".", ","),
                    pay.STATUSES.get(p.status, (p.status,))[0] if p else "", p.ref if p else "", res.cost_center,
                    b.club.name if b.club else "", {"invoice": "Rechnung", "monthly": "Sammelrechnung"}.get(b.billing, ""),
                    b.group_ref, b.series_id, "ja" if b.internal else "", to_local(b.created_at).strftime("%d.%m.%Y %H:%M")])
    return "﻿" + buf.getvalue()


# --- Kopieren, Export, Import ------------------------------------------------------------------

def _copy_children(src: Resource, dst: Resource) -> None:
    for u in src.parts:
        dst.parts.append(ResourceUnit(**{k: getattr(u, k) for k in UNIT_FIELDS}))
    for t in src.tariffs:
        dst.tariffs.append(ResourceTariff(**{k: getattr(t, k) for k in TARIFF_FIELDS}))
    for x in src.extras:
        dst.extras.append(ResourceExtra(**{k: getattr(x, k) for k in EXTRA_FIELDS}))


def photos_dir(resource_id: int):
    return settings.data_dir / "resources" / str(resource_id)


def copy(db, src: Resource, owner) -> Resource:
    """Kopie als Vorlage (z. B. weiterer Raum mit gleichen Preisen): ohne Buchungen, Sperrzeiten und Freigaben,
    zunächst nicht freigeschaltet."""
    dst = Resource(owner_id=owner.id, slug=rs.unique_slug(db, src.name + " Kopie"), active=False,
                   manager_user_id=src.manager_user_id, manager_group_id=src.manager_group_id, mailbox=src.mailbox,
                   dms_area_id=src.dms_area_id, position=src.position + 1,
                   **{k: getattr(src, k) for k in FIELDS})
    dst.name = (src.name + " (Kopie)")[:200]
    db.add(dst)
    _copy_children(src, dst)
    db.flush()
    for p in src.photos:
        path = photos_dir(src.id) / p.file
        if path.is_file():
            photos_dir(dst.id).mkdir(parents=True, exist_ok=True)
            name = secrets.token_hex(10) + path.suffix
            (photos_dir(dst.id) / name).write_bytes(path.read_bytes())
            dst.photos.append(ResourcePhoto(file=name, name=p.name, position=p.position))
    if src.terms_file and (photos_dir(src.id) / src.terms_file).is_file():
        photos_dir(dst.id).mkdir(parents=True, exist_ok=True)
        dst.terms_file = secrets.token_hex(10) + ".pdf"
        (photos_dir(dst.id) / dst.terms_file).write_bytes((photos_dir(src.id) / src.terms_file).read_bytes())
    return dst


def export(res: Resource) -> bytes:
    data = {"format": FORMAT, "exported_at": utcnow().isoformat(timespec="seconds"),
            "resource": {k: getattr(res, k) for k in FIELDS},
            "parts": [{k: getattr(u, k) for k in UNIT_FIELDS} for u in res.parts],
            "tariffs": [{k: getattr(t, k) for k in TARIFF_FIELDS} for t in res.tariffs],
            "extras": [{k: getattr(x, k) for k in EXTRA_FIELDS} for x in res.extras],
            "photos": [], "terms_pdf": ""}
    for p in res.photos:
        path = photos_dir(res.id) / p.file
        if path.is_file():
            data["photos"].append({"name": p.name, "ext": path.suffix, "data": base64.b64encode(path.read_bytes()).decode()})
    if res.terms_file and (photos_dir(res.id) / res.terms_file).is_file():
        data["terms_pdf"] = base64.b64encode((photos_dir(res.id) / res.terms_file).read_bytes()).decode()
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


class ResImportError(ValueError):
    pass


def _coerce(model, field: str, value):
    column = model.__table__.c[field]
    default = column.default.arg if column.default is not None else None
    py = column.type.python_type if hasattr(column.type, "python_type") else str
    if value is None:
        return None if column.nullable else default
    try:
        if py is bool:
            return bool(value)
        if py is int:
            return max(-10**9, min(10**9, int(value)))
        if py is float:
            return float(value)
        return str(value)[:column.type.length or 100000]
    except (TypeError, ValueError):
        return default


def import_(db, raw: bytes, owner) -> Resource:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ResImportError("Die Datei ist keine exportierte Ressource.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("resource"), dict):
        raise ResImportError("Die Datei ist keine exportierte Ressource.")
    src = data["resource"]
    res = Resource(owner_id=owner.id, manager_user_id=owner.id, active=False,
                   **{k: _coerce(Resource, k, src.get(k)) for k in FIELDS if k in src})
    res.name = " ".join(str(res.name or "Importierte Ressource").split())[:200]
    res.slug = rs.unique_slug(db, res.name)
    res.mode = res.mode if res.mode in ("request", "instant") else "request"
    res.units = ",".join(m for m in rs.MODES if m in str(res.units or "").split(",")) or "day"
    for key, default in (("blocks_json", "[]"), ("hours_json", "{}"), ("fields_json", "[]")):
        try:
            json.loads(getattr(res, key) or default)
        except ValueError:
            setattr(res, key, default)
    from .workflow import clean_request_items
    res.fields_json = json.dumps(clean_request_items(json.loads(res.fields_json or "[]")), ensure_ascii=False)
    db.add(res)
    for model, key, fields in ((ResourceUnit, "parts", UNIT_FIELDS), (ResourceTariff, "tariffs", TARIFF_FIELDS),
                               (ResourceExtra, "extras", EXTRA_FIELDS)):
        for row in (data.get(key) or [])[:60]:
            if isinstance(row, dict) and str(row.get("name") or "").strip():
                getattr(res, key).append(model(**{k: _coerce(model, k, row.get(k)) for k in fields if k in row}))
    for x in res.extras:
        x.per = x.per if x.per in rs.EXTRA_PER else "once"
    if not res.tariffs:
        res.tariffs.append(ResourceTariff(name="Standard", percent=100))
    db.flush()
    for n, photo in enumerate((data.get("photos") or [])[:30]):
        try:
            content = base64.b64decode(photo.get("data") or "", validate=True)
        except (ValueError, AttributeError):
            continue
        kind = _image_type(content)
        if kind and len(content) <= 8 * 1024 * 1024:
            photos_dir(res.id).mkdir(parents=True, exist_ok=True)
            name = secrets.token_hex(10) + kind
            (photos_dir(res.id) / name).write_bytes(content)
            res.photos.append(ResourcePhoto(file=name, name=str(photo.get("name") or "")[:200], position=n))
    try:
        pdf = base64.b64decode(data.get("terms_pdf") or "", validate=True)
    except ValueError:
        pdf = b""
    if pdf.startswith(b"%PDF") and len(pdf) <= 20 * 1024 * 1024:
        photos_dir(res.id).mkdir(parents=True, exist_ok=True)
        res.terms_file = secrets.token_hex(10) + ".pdf"
        (photos_dir(res.id) / res.terms_file).write_bytes(pdf)
    return res


def _image_type(content: bytes) -> str | None:
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None
