"""Adress- und Ortssuche über Nominatim (OpenStreetMap) – immer über den Server.

Der Browser fragt nur das Portal; das Portal fragt den Geocoder, merkt sich Antworten 30 Tage und hält
den Abstand von mindestens einer Sekunde zwischen Anfragen ein (Nutzungsrichtlinie des öffentlichen
Nominatim-Dienstes). Ein eigener Nominatim-Server lässt sich in den Karteneinstellungen eintragen.
"""

import hashlib
import json
import re
import threading
import time
from datetime import timedelta
from urllib.parse import urlparse
from .geo_services import paced

import httpx
from sqlalchemy import delete, select

from .config import settings
from .db import GeoCache, SessionLocal, get_settings, utcnow

DEFAULT_URL = "https://nominatim.openstreetmap.org"
CACHE_DAYS = 30
_lock = threading.Lock()
_last = [0.0]
ZIP_RE = re.compile(r"^\d{5}$")


def config() -> dict:
    with SessionLocal() as db:
        cfg = get_settings(db)
    return {"url": (cfg.get("geocoder_url") or DEFAULT_URL).rstrip("/"),
            "countries": cfg.get("geocoder_countries", "de") or "",
            "contact": cfg.get("geocoder_contact") or cfg.get("mail_from") or ""}


def _fetch(path: str, params: dict) -> list | dict | None:
    cfg = config()
    params = {**params, "format": "jsonv2", "addressdetails": 1}
    if cfg["countries"] and path == "/search":
        params["countrycodes"] = cfg["countries"]
    key = hashlib.sha256((cfg["url"] + path + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    with SessionLocal() as db:
        hit = db.get(GeoCache, key)
        if hit and hit.created_at > utcnow() - timedelta(days=CACHE_DAYS):
            return json.loads(hit.value_json)
    headers = {"User-Agent": f"Verwaltungsportal ({settings.portal_base_url}{'; ' + cfg['contact'] if cfg['contact'] else ''})",
               "Accept-Language": "de"}
    with paced("geocoder"):   # shared across all server workers
        try:
            r = httpx.get(cfg["url"] + path, params=params, headers=headers, timeout=8, follow_redirects=True)
            data = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            data = None
        _last[0] = time.monotonic()
    if data is not None:
        with SessionLocal() as db:
            db.merge(GeoCache(key=key, value_json=json.dumps(data), created_at=utcnow()))
            if hash(key) % 50 == 0:   # gelegentlich aufräumen
                db.execute(delete(GeoCache).where(GeoCache.created_at < utcnow() - timedelta(days=CACHE_DAYS)))
            db.commit()
    return data


def _address(item: dict) -> dict:
    a = item.get("address") or {}
    city = a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or a.get("municipality") or ""
    district = a.get("suburb") or a.get("city_district") or a.get("borough") or a.get("quarter") or ""
    # municipality may be a Verbandsgemeinde, not the Ortsgemeinde.
    # Preserve the locality supplied by Nominatim and keep administrative levels separate.
    if not district and (a.get("city") or a.get("town")):
        district = a.get("village") or a.get("hamlet") or ""
    out = {"street": a.get("road") or a.get("pedestrian") or a.get("footway") or a.get("path") or "",
           "house_no": a.get("house_number") or "", "zip": a.get("postcode") or "", "city": city,
           "district": district if district != city else "", "municipality": a.get("municipality") or "", "state": a.get("state") or "",
           "country": a.get("country") or ""}
    try:
        out["lat"], out["lon"] = round(float(item["lat"]), 6), round(float(item["lon"]), 6)
    except (KeyError, TypeError, ValueError):
        pass
    return out


def _label(addr: dict, fallback: str) -> str:
    street = " ".join(x for x in (addr.get("street"), addr.get("house_no")) if x)
    town = " ".join(x for x in (addr.get("zip"), addr.get("city")) if x)
    parts = [p for p in (street, town, addr.get("district") and f"OT {addr['district']}") if p]
    return ", ".join(parts) or fallback


def search(q: str, limit: int = 6) -> list[dict]:
    q = " ".join(q.split())[:200]
    if len(q) < 3:
        return []
    data = _fetch("/search", {"q": q, "limit": max(1, min(limit, 10))}) or []
    out = []
    for item in data if isinstance(data, list) else []:
        addr = _address(item)
        out.append({"label": _label(addr, item.get("display_name", "")), "name": item.get("name") or "",
                    "display": item.get("display_name", ""), "type": item.get("type", ""), **addr,
                    "bbox": item.get("boundingbox")})
    return out


def reverse(lat: float, lon: float) -> dict | None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    data = _fetch("/reverse", {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": 18})
    if not isinstance(data, dict) or "error" in data:
        return None
    addr = _address(data)
    addr["lat"], addr["lon"] = round(lat, 6), round(lon, 6)   # Standort des Geräts, nicht des Gebäudes
    return {"label": _label(addr, data.get("display_name", "")), **addr}


def postcode(plz: str) -> list[dict]:
    """Orte (und Ortsteile) zu einer deutschen Postleitzahl."""
    plz = plz.strip()
    if not ZIP_RE.match(plz):
        return []
    cfg = config()
    params = {"postalcode": plz, "limit": 20}
    if cfg["countries"]:
        params["countrycodes"] = cfg["countries"]
    data = _fetch("/search", params) or []
    seen, out = set(), []
    for item in data if isinstance(data, list) else []:
        addr = _address(item)
        city = addr.get("city") or (item.get("name") if item.get("name") != plz else "")
        if not city:
            continue
        key = (city, addr.get("district", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append({"zip": plz, "city": city, "district": addr.get("district", ""), "lat": addr.get("lat"),
                    "lon": addr.get("lon")})
    return out


def clear_cache() -> int:
    with SessionLocal() as db:
        n = db.execute(delete(GeoCache)).rowcount
        db.commit()
    return n or 0


def cache_count() -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(GeoCache.key)).all())


def public_only():
    return (urlparse(config()["url"]).hostname or "").lower() == "nominatim.openstreetmap.org"
