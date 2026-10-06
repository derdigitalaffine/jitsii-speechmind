"""Terminbuchung im erweiterten Umfang: mehrere Terminarten je Buchungsseite.

Jede Terminart hat Dauer, Puffer, Vorlauf, Ort/Videokonferenz, optionale Bestätigung durch Mitarbeitende und eine
oder mehrere zuständige Personen. Wann diese Termine anbieten, legen wiederkehrende Sprechzeiten je Person fest
(Wochenplan, Ortszeit). Keine Termine gibt es
  * an Ausnahmetagen der Seite (für alle oder eine Person),
  * an Feiertagen (holidays.py, abschaltbar),
  * während einer bestätigten Abwesenheit der Person (absence.py),
  * wenn die Person schon einen Termin hat (auf irgendeiner Seite; mit dem Puffer der jeweiligen Terminart).
Bürger:innen wählen erst die Terminart, auf Wunsch die Person, dann einen freien Beginn. Ohne Wahl verteilt das
Portal auf die Person mit den wenigsten Terminen in der Woche.
"""

import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from .db import Absence, Booking, BookingHours, BookingPage, BookingType, User, to_local, utcnow

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
DURATIONS = [10, 15, 20, 30, 45, 60, 75, 90, 120, 180, 240]
STEPS = [5, 10, 15, 20, 30, 60]
PHONE_MODES = {"none": "nicht abfragen", "optional": "freiwillig", "required": "Pflicht"}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ACTIVE = ("booked", "requested")


def _to_utc(local: datetime) -> datetime:
    from .bookings import to_utc
    return to_utc(local)


def _hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def valid_time(value: str) -> str | None:
    v = (value or "").strip()
    if re.match(r"^\d:\d\d$", v):
        v = "0" + v
    return v if TIME_RE.match(v) else None


def active_types(page: BookingPage) -> list[BookingType]:
    return [t for t in page.types if t.active and any(p.active for p in t.providers)]


def _blocked_days(db, page: BookingPage, user_id: int, first: date, last: date) -> set[date]:
    out: set[date] = set()
    for c in page.closures:
        if c.user_id not in (None, user_id):
            continue
        d0, d1 = max(first, date.fromisoformat(c.date_from)), min(last, date.fromisoformat(c.date_to))
        while d0 <= d1:
            out.add(d0)
            d0 += timedelta(days=1)
    for a in db.scalars(select(Absence).where(Absence.user_id == user_id, Absence.status == "confirmed",
                                              Absence.starts_on <= last.isoformat(), Absence.ends_on >= first.isoformat())):
        d0, d1 = max(first, date.fromisoformat(a.starts_on)), min(last, date.fromisoformat(a.ends_on))
        while d0 <= d1:
            out.add(d0)
            d0 += timedelta(days=1)
    return out


def _busy(db, user_id: int, start: datetime, end: datetime, keep: Booking | None = None) -> list[tuple[datetime, datetime]]:
    """Belegte Zeiten der Person (UTC) inkl. Puffer der jeweiligen Terminart."""
    rows = db.scalars(select(Booking).where(Booking.provider_id == user_id, Booking.status.in_(ACTIVE),
                                            Booking.starts_at < end, Booking.ends_at > start - timedelta(hours=8))).all()
    out = []
    for b in rows:
        if keep is not None and b.id == keep.id:
            continue
        buf = timedelta(minutes=b.type.buffer_minutes if b.type else 0)
        out.append((b.starts_at, b.ends_at + buf))
    return out


def slots(db, page: BookingPage, bt: BookingType, provider_id: int | None = None, keep: Booking | None = None,
          until: date | None = None) -> list[dict]:
    """Freie Beginnzeiten der Terminart: [{start, end, providers: [user_id …], free}] (UTC, sortiert)."""
    from . import holidays
    providers = [p for p in bt.providers if p.active and (provider_id is None or p.id == provider_id)]
    if not providers:
        return []
    now = utcnow()
    earliest = now + timedelta(hours=bt.min_notice_hours)
    first = to_local(now).date()
    last = until or (first + timedelta(days=max(1, page.days_ahead)))
    length = timedelta(minutes=bt.duration_minutes)
    buffer = timedelta(minutes=bt.buffer_minutes)
    step = timedelta(minutes=max(5, page.step_minutes or 15))
    specials: set[date] = set()
    if page.holidays_closed:
        for year in range(first.year, last.year + 1):
            specials |= {d for d in holidays.special_days(db, year)}
    found: dict[datetime, dict] = {}
    for p in providers:
        hours = [h for h in page.hours if h.user_id == p.id]
        if not hours:
            continue
        blocked = _blocked_days(db, page, p.id, first, last)
        busy = _busy(db, p.id, _to_utc(datetime.combine(first, time())), _to_utc(datetime.combine(last + timedelta(days=1), time())), keep)
        d = first
        while d <= last:
            if d not in blocked and d not in specials:
                for h in hours:
                    if h.weekday != d.weekday():
                        continue
                    t = _to_utc(datetime.combine(d, _hm(h.start)))
                    stop = _to_utc(datetime.combine(d, _hm(h.end)))
                    while t + length <= stop:
                        if t >= earliest and not any(t < e and t + length + buffer > s for s, e in busy):
                            slot = found.setdefault(t, {"start": t, "end": t + length, "providers": []})
                            slot["providers"].append(p.id)
                        t += step
            d += timedelta(days=1)
    out = sorted(found.values(), key=lambda s: s["start"])
    for s in out:
        s["free"] = len(s["providers"])
    return out


def pick_provider(db, candidates: list[int], start: datetime) -> int:
    """Gleichmäßig verteilen: die Person mit den wenigsten Terminen in derselben Woche (bei Gleichstand die erste)."""
    if len(candidates) == 1:
        return candidates[0]
    local = to_local(start).date()
    week0 = local - timedelta(days=local.weekday())
    a, b = _to_utc(datetime.combine(week0, time())), _to_utc(datetime.combine(week0 + timedelta(days=7), time()))
    counts = {c: 0 for c in candidates}
    for pid in db.scalars(select(Booking.provider_id).where(Booking.provider_id.in_(candidates),
                                                            Booking.status.in_(ACTIVE), Booking.starts_at >= a,
                                                            Booking.starts_at < b)):
        counts[pid] = counts.get(pid, 0) + 1
    return min(candidates, key=lambda c: (counts[c], candidates.index(c)))


def check(db, page: BookingPage, bt: BookingType, start: datetime, provider_id: int | None = None,
          keep: Booking | None = None) -> tuple[dict | None, str]:
    """Ist der Beginn frei? Gibt (Zeitfenster mit gewählter Person, Fehler)."""
    if keep is not None and keep.provider_id and provider_id is None:
        provider_id = keep.provider_id if keep.starts_at != start else None
    day = to_local(start).date()
    slot = next((s for s in slots(db, page, bt, provider_id, keep, until=day) if s["start"] == start), None)
    if slot is None and keep is not None and provider_id is not None:
        slot = next((s for s in slots(db, page, bt, None, keep, until=day) if s["start"] == start), None)
    if slot is None:
        return None, "Dieser Termin ist leider nicht mehr frei. Bitte wählen Sie einen anderen."
    chosen = provider_id if provider_id in slot["providers"] else pick_provider(db, slot["providers"], start)
    return {**slot, "provider_id": chosen}, ""


def weekly_plan(page: BookingPage) -> dict[int, list[BookingHours]]:
    """Person → Sprechzeiten (für die Verwaltung)."""
    out: dict[int, list[BookingHours]] = {}
    for h in page.hours:
        out.setdefault(h.user_id, []).append(h)
    return out


def all_providers(page: BookingPage) -> list[User]:
    seen: dict[int, User] = {}
    for t in page.types:
        for p in t.providers:
            seen[p.id] = p
    return sorted(seen.values(), key=lambda u: u.name)


def summary(bt: BookingType) -> str:
    parts = [f"{bt.duration_minutes} Minuten"]
    if bt.online:
        parts.append("Videokonferenz")
    elif bt.location:
        parts.append(bt.location)
    return " · ".join(parts)


# --- Eigene Felder je Terminart -------------------------------------------------------------------

FIELD_KINDS = {"text": "Text (eine Zeile)", "textarea": "Text (mehrzeilig)", "select": "Auswahl", "checkbox": "Ja/Nein",
               "date": "Datum", "number": "Zahl"}
MAX_FIELDS = 12


def fields(bt: BookingType | None) -> list[dict]:
    """Eigene Felder: [{key, label, kind, options, required, help}]."""
    import json
    if bt is None:
        return []
    try:
        data = json.loads(bt.fields_json or "[]")
    except ValueError:
        return []
    return [f for f in data if isinstance(f, dict) and f.get("label") and f.get("kind") in FIELD_KINDS][:MAX_FIELDS]


def clean_fields(labels, kinds, options, required, helps) -> str:
    """Formularzeilen aus der Verwaltung → JSON (leere Zeilen fallen weg, Schlüssel f1, f2 … bleiben stabil je Reihenfolge)."""
    import json
    out = []
    for i, label in enumerate(labels):
        label = " ".join(str(label or "").split())[:120]
        if not label:
            continue
        kind = kinds[i] if i < len(kinds) and kinds[i] in FIELD_KINDS else "text"
        opts = [o.strip()[:80] for o in str(options[i] if i < len(options) else "").split(";") if o.strip()][:30]
        if kind == "select" and not opts:
            kind = "text"
        out.append({"key": f"f{len(out) + 1}", "label": label, "kind": kind, "options": opts,
                    "required": str(i) in required, "help": " ".join(str(helps[i] if i < len(helps) else "").split())[:200]})
    return json.dumps(out[:MAX_FIELDS], ensure_ascii=False)


def read_answers(bt: BookingType | None, form) -> tuple[list[dict], str]:
    """Antworten aus dem Buchungsformular prüfen: ([{label, value}], Fehler)."""
    out = []
    for f in fields(bt):
        raw = form.get(f"q_{f['key']}")
        if f["kind"] == "checkbox":
            value = "ja" if raw == "1" else ("nein" if not f["required"] else "")
        else:
            value = " ".join(str(raw or "").split()) if f["kind"] != "textarea" else str(raw or "").replace("\r\n", "\n").strip()
            value = value[:2000]
        if f["kind"] == "select" and value and value not in f["options"]:
            return [], f"Bitte bei „{f['label']}“ einen Eintrag aus der Liste wählen."
        if f["kind"] == "number" and value and not re.fullmatch(r"-?\d+(?:[.,]\d+)?", value):
            return [], f"Bitte bei „{f['label']}“ eine Zahl angeben."
        if f["kind"] == "date" and value:
            try:
                value = date.fromisoformat(value).strftime("%d.%m.%Y")
            except ValueError:
                return [], f"Bitte bei „{f['label']}“ ein Datum angeben."
        if f["required"] and not value:
            return [], f"Bitte „{f['label']}“ angeben." if f["kind"] != "checkbox" else f"Bitte „{f['label']}“ bestätigen."
        out.append({"label": f["label"], "value": value})
    return out, ""


def answers_of(b) -> list[dict]:
    import json
    try:
        data = json.loads(getattr(b, "answers_json", "") or "[]")
    except ValueError:
        return []
    return [a for a in data if isinstance(a, dict) and "label" in a] if isinstance(data, list) else []


def answers_text(b) -> str:
    return "\n".join(f"{a['label']}: {a['value'] or '–'}" for a in answers_of(b))
