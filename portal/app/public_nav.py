"""Öffentliches Menü (Kopfzeile ohne Anmeldung) und Startseite für Bürger:innen.

Alle öffentlichen Bereiche der eingeschalteten Module erscheinen automatisch – Anträge, Räume & Plätze, Termine
buchen, Karte, Ortsrecht und der Krankmelder (nur wenn er ohne Konto erreichbar ist). Unter Verwaltung ›
Öffentliches Menü legen Admins Reihenfolge und Auswahl fest und ergänzen eigene Links (z. B. zur Homepage).
"""

import json
import re
import time

from sqlalchemy import func, select

from .db import BookingPage, SessionLocal, get_settings

# Schlüssel: (Bezeichnung, Symbol, Modul, Pfad, Beschreibung für die Startseite)
ITEMS = {
    "antraege": ("Anträge", "fa-file-signature", "applications", "/antraege",
                 "Online-Anträge stellen und den Bearbeitungsstand verfolgen"),
    "raeume": ("Räume & Plätze", "fa-building", "resources", "/r",
               "Bürgerhäuser, Grillhütten, Plätze und Geräte ansehen und buchen"),
    "termine": ("Termine buchen", "fa-calendar-plus", "bookings", "/b",
                "Gesprächs- und Sprechstundentermine selbst buchen"),
    "karte": ("Karte", "fa-map-location-dot", "maps", "/karte", "Stadtplan, Luftbilder und Fachkarten"),
    "recht": ("Ortsrecht", "fa-scale-balanced", "laws", "/recht", "Satzungen, Verordnungen und Gesetze lesen und durchsuchen"),
    "krank": ("Krankmeldung", "fa-briefcase-medical", "krank", "/krank", "Krankmeldung für Beschäftigte"),
}
MAX_LINKS = 8
_URL_RE = re.compile(r"^(https?://[^\s<>\"']+|/(?!/)[^\s<>\"']*)$")
_cache: dict = {"at": 0.0, "key": None, "items": []}


def invalidate() -> None:
    _cache["at"] = 0.0


def config(cfg: dict[str, str]) -> dict:
    """Gespeicherte Auswahl: {"order": [...], "hidden": [...], "links": [{"label", "url"}]}."""
    try:
        data = json.loads(cfg.get("public_nav") or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    order = [k for k in data.get("order", []) if k in ITEMS]
    order += [k for k in ITEMS if k not in order]
    links = [lk for lk in data.get("links", []) if isinstance(lk, dict) and lk.get("label") and lk.get("url")]
    return {"order": order, "hidden": [k for k in data.get("hidden", []) if k in ITEMS], "links": links[:MAX_LINKS]}


def clean_link(label: str, url: str) -> dict | None:
    label, url = " ".join(str(label or "").split())[:40], str(url or "").strip()[:500]
    if not label or not _URL_RE.match(url):
        return None
    return {"label": label, "url": url}


def listed_bookings(db) -> int:
    return db.scalar(select(func.count(BookingPage.id)).where(
        BookingPage.listed.is_(True), BookingPage.active.is_(True), BookingPage.invite_only.is_(False))) or 0


def available(db, cfg: dict[str, str], modules: set[str]) -> dict[str, bool]:
    """Welche Bereiche gibt es gerade öffentlich? (Modul an; Termine nur mit freigegebener Buchungsseite,
    Krankmelder nur mit Zugang ohne Konto.)"""
    from . import krank
    out = {}
    for key, (_label, _icon, module, _path, _text) in ITEMS.items():
        ok = module in modules
        if ok and key == "termine":
            ok = listed_bookings(db) > 0
        if ok and key == "krank":
            ok = krank.public_open(cfg)
        out[key] = ok
    return out


def entries(db, cfg: dict[str, str], modules: set[str]) -> list[dict]:
    """Alle Bereiche in eingestellter Reihenfolge – für die Verwaltung (mit Status)."""
    conf, avail = config(cfg), available(db, cfg, modules)
    return [{"key": k, "label": ITEMS[k][0], "icon": ITEMS[k][1], "url": ITEMS[k][3], "text": ITEMS[k][4],
             "available": avail[k], "hidden": k in conf["hidden"]} for k in conf["order"]]


def items(modules: set[str]) -> list[dict]:
    """Sichtbare Einträge der öffentlichen Kopfzeile (für einige Sekunden zwischengespeichert)."""
    key = tuple(sorted(modules))
    if time.monotonic() - _cache["at"] < 10 and _cache["key"] == key:
        return _cache["items"]
    with SessionLocal() as db:
        cfg = get_settings(db)
        out = [e for e in entries(db, cfg, modules) if e["available"] and not e["hidden"]]
        out += [{"key": "", "label": lk["label"], "icon": "fa-arrow-up-right-from-square", "url": lk["url"], "text": "",
                 "external": lk["url"].startswith("http")} for lk in config(cfg)["links"]]
    _cache.update(at=time.monotonic(), key=key, items=out)
    return out


def active(item: dict, path: str) -> bool:
    url = item["url"]
    return not item.get("external") and url != "/" and (path == url or path.startswith(url.rstrip("/") + "/"))
