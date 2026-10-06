"""Öffentliche Darstellung der Ressourcen: Farben je Art, Ausstattung als Symbole, Preisübersicht und
Verfügbarkeit je Tag (Monatskalender beim Buchen)."""

import calendar
import json
import re
from datetime import date, datetime, time, timedelta

from . import resources as rs
from .db import Resource, get_settings, to_local, utcnow

# Gut unterscheidbare Farben (auch für Farbsehschwäche), in dieser Reihenfolge an die Arten vergeben
PALETTE = ("#2563eb", "#16a34a", "#ea580c", "#9333ea", "#0891b2", "#ca8a04", "#db2777", "#475569", "#65a30d", "#dc2626")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Ausstattung (eine Zeile je Merkmal) → Symbol; erstes passendes Stichwort gewinnt
FACT_ICONS = (
    (("barrierefrei", "rollstuhl", "behindert"), "fa-wheelchair"),
    (("küche", "kueche", "kochen", "theke"), "fa-kitchen-set"),
    (("bühne", "buehne"), "fa-masks-theater"),
    (("beamer", "projektor", "leinwand"), "fa-video"),
    (("musik", "lautsprecher", "beschallung", "mikrofon", "ton"), "fa-volume-high"),
    (("wlan", "wifi", "internet"), "fa-wifi"),
    (("park",), "fa-square-parking"),
    (("toilette", "wc", "sanitär", "dusche"), "fa-restroom"),
    (("heizung", "heizbar"), "fa-temperature-arrow-up"),
    (("strom", "steckdose"), "fa-plug"),
    (("wasser",), "fa-faucet"),
    (("grill", "feuer"), "fa-fire-burner"),
    (("tisch", "stuhl", "stühle", "bestuhlung", "garnitur"), "fa-chair"),
    (("geschirr", "besteck", "gläser"), "fa-utensils"),
    (("spielplatz", "kinder"), "fa-children"),
    (("überdacht", "ueberdacht", "dach", "pavillon"), "fa-umbrella"),
    (("garten", "wiese", "außen", "aussen", "terrasse"), "fa-tree"),
    (("bar", "ausschank", "kühl", "kuehl"), "fa-champagne-glasses"),
)


def category_colors(db, categories) -> dict[str, str]:
    """Art → Farbe. Eingestellte Farben (Ressourcen › Einstellungen) gewinnen, die übrigen Arten bekommen
    nacheinander Farben aus der Palette (stabil nach Name sortiert)."""
    try:
        chosen = json.loads(get_settings(db).get("res_category_colors") or "{}")
    except ValueError:
        chosen = {}
    out, used = {}, set()
    for cat, color in chosen.items():
        if isinstance(color, str) and COLOR_RE.match(color):
            out[cat] = color
            used.add(color.lower())
    free = [c for c in PALETTE if c not in used] or list(PALETTE)
    for i, cat in enumerate(sorted({c for c in categories if c and c not in out})):
        out[cat] = free[i % len(free)]
    out.setdefault("", "#475569")
    return out


def facts(res: Resource) -> list[tuple[str, str]]:
    """Ausstattung als (Symbol, Text) – aus dem Feld „Ausstattung“, eine Zeile je Merkmal."""
    out = []
    for line in (res.equipment or "").splitlines():
        text = line.strip().lstrip("-*• ").strip()
        if not text:
            continue
        low = text.lower()
        icon = next((i for words, i in FACT_ICONS if any(w in low for w in words)), "fa-circle-check")
        out.append((icon, text))
    return out[:24]


def price_rows(res: Resource) -> list[dict]:
    """Preisübersicht je Buchungsart: gesamte Ressource und Teilräume, mit Wochenend-/Feiertagspreis."""
    unit = {"day": "Tag", "block": "Zeitblock", "hour": "Stunde"}
    rows = []
    for m in rs.modes(res):
        for t in [res] + list(res.parts):
            base, wkd = getattr(t, f"price_{m}") or 0, getattr(t, f"wkd_{m}") or 0
            name = (res.name + (" (gesamt)" if res.parts else "")) if t is res else t.name
            rows.append({"mode": m, "unit": unit[m], "name": name, "base": base,
                         "weekend": wkd if wkd and wkd != base else 0, "is_part": t is not res})
    return rows


def _prices(res: Resource) -> list[tuple[int, str]]:
    """(Preis, Buchungsart) nur für die eingeschalteten Buchungsarten – auch die der Teilräume. Preise einer
    abgeschalteten Buchungsart (z. B. noch eingetragener Blockpreis) zählen nicht."""
    return [(getattr(t, f"price_{m}"), m) for m in rs.modes(res) for t in [res, *res.parts] if getattr(t, f"price_{m}")]


def price_from(res: Resource) -> int:
    values = _prices(res)
    return min(v for v, _ in values) if values else 0


def price_from_unit(res: Resource) -> str:
    values = _prices(res)
    if not values:
        return ""
    return {"hour": "Std.", "block": "Block", "day": "Tag"}[min(values)[1]]


def booking_window(res: Resource) -> tuple[date, date]:
    now = to_local(utcnow())
    first = (now + timedelta(hours=res.min_notice_hours or 0)).date()
    last = (now + timedelta(days=res.max_advance_days or 365)).date()
    return first, last


def month_status(db, res: Resource, year: int, month: int, ids: set[int] | None = None, mode: str = "") -> dict:
    """Verfügbarkeit je Tag eines Monats für den Buchungskalender:
    free (ganz frei), partial (teilweise frei – Zeiten wählbar), busy (belegt), closed (Ruhetag),
    off (vergangen bzw. außerhalb von Vorlauf und Vorausbuchung)."""
    mode = mode if mode in rs.modes(res) else rs.modes(res)[0]
    days_n = calendar.monthrange(year, month)[1]
    d0, d1 = date(year, month, 1), date(year, month, days_n)
    start, end = rs._utc(datetime.combine(d0, time())), rs._utc(datetime.combine(d1 + timedelta(days=1), time()))
    local = lambda t: to_local(t).replace(tzinfo=None)  # noqa: E731
    spans = [(local(a), local(b)) for a, b in rs.busy_spans(db, res, start, end, ids)]
    first, last = booking_window(res)
    open_hours = rs.hours(res)
    min_len = timedelta(minutes=max(res.min_minutes or 0, res.slot_minutes or 0, 1))
    out = {}
    for n in range(1, days_n + 1):
        d = date(year, month, n)
        if d < first or d > last:
            out[d.isoformat()] = "off"
            continue
        ranges = open_hours.get(str(d.weekday()))
        if ranges == []:
            out[d.isoformat()] = "closed"
            continue
        day0, day1 = datetime.combine(d, time()), datetime.combine(d + timedelta(days=1), time())
        busy = sorted((max(a, day0), min(b, day1)) for a, b in spans if a < day1 and b > day0)
        if not busy:
            out[d.isoformat()] = "free"
            continue
        if mode == "day":
            out[d.isoformat()] = "busy"
            continue
        if mode == "block":
            free_blocks = 0
            for blk in rs.blocks(res):
                bs, be = datetime.combine(d, rs._hm(blk["start"])), datetime.combine(d, rs._hm(blk["end"]))
                if be <= bs:
                    be += timedelta(days=1)
                free_blocks += not any(x < be and y > bs for x, y in busy)
            out[d.isoformat()] = "partial" if free_blocks else "busy"
            continue
        opening = [(datetime.combine(d, rs._hm(a)), day1 if b == "24:00" else datetime.combine(d, rs._hm(b)))
                   for a, b in (ranges if ranges is not None else [["00:00", "24:00"]])]
        has_gap = False
        for a, b in opening:
            cur = a
            for x, y in busy:
                if y <= cur or x >= b:
                    continue
                if x - cur >= min_len:
                    has_gap = True
                cur = max(cur, y)
            if b - cur >= min_len:
                has_gap = True
        out[d.isoformat()] = "partial" if has_gap else "busy"
    return {"month": f"{year:04d}-{month:02d}", "days": out, "first": first.isoformat(), "last": last.isoformat(),
            "mode": mode, "max_days": max(1, res.max_days or 1)}
