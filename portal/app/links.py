"""Öffentliche Adressen je Modul.

Jedes Modul ist immer unter der Portal-Domain erreichbar (z. B. https://portal.example.de/krank). Ist unter
Verwaltung › Domains zusätzlich eine eigene Domain eingetragen (z. B. krank.example.de), bauen Mails, QR-Codes
und Links für Außenstehende ihre Adressen mit dieser Domain. Interne Verwaltungslinks bleiben auf der
Portal-Domain (dort gilt die Anmeldung). Kurzlinks behalten ihre eigene Einstellung (short_domain).
"""

import time
from urllib.parse import urlparse

from .config import settings
from .db import SessionLocal, get_settings

_cache: dict = {"at": 0.0, "cfg": {}}


def _cfg() -> dict[str, str]:
    if time.monotonic() - _cache["at"] > 5:
        with SessionLocal() as db:
            _cache["cfg"] = get_settings(db)
        _cache["at"] = time.monotonic()
    return _cache["cfg"]


def invalidate() -> None:
    _cache["at"] = 0.0


def domain_of(cfg: dict[str, str], key: str) -> str:
    return (cfg.get(f"domain_{key}") or "").strip().lower()


def _base(domain: str) -> str:
    if not domain:
        return settings.portal_base_url
    scheme = urlparse(settings.portal_base_url).scheme or "https"
    return f"{scheme}://{domain}"


def base(key: str) -> str:
    """Basisadresse für öffentliche Links eines Moduls (ohne abschließenden Schrägstrich)."""
    return _base(domain_of(_cfg(), key))


def module_base(db, key: str, cfg: dict[str, str] | None = None) -> str:
    return _base(domain_of(cfg if cfg is not None else get_settings(db), key))


def module_url(db, key: str, path: str, cfg: dict[str, str] | None = None) -> str:
    return module_base(db, key, cfg) + path
