"""Update-Hinweis für Admins.

Einmal täglich (abschaltbar unter „Über dieses Portal“) liest das Portal die Versionsnummer der aktuellen Fassung
aus dem öffentlichen Repository (nur die Datei VERSION, ohne Daten dieses Servers außer der üblichen
IP-Adresse). Ist sie neuer als die installierte, sehen Admins einen Hinweis. Aktualisiert wird weiterhin
bewusst von Hand (git pull und docker compose up -d --build, siehe Admin-Handbuch).
"""

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from .db import SessionLocal, get_settings, set_setting, utcnow

log = logging.getLogger("portal.updates")

VERSION_FILE = Path(__file__).with_name("VERSION")
CHECK_URL = os.environ.get("UPDATE_CHECK_URL",
                           "https://raw.githubusercontent.com/derdigitalaffine/jitsii-speechmind/main/portal/app/VERSION").strip()
INTERVAL = timedelta(hours=24)
_VERSION_RE = re.compile(r"^\d+(\.\d+){1,3}$")


def current() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split(".")) if _VERSION_RE.match(version or "") else (0,)


def available(cfg: dict[str, str]) -> str:
    """Neuere Version als die installierte (oder "")."""
    latest = cfg.get("update_latest") or ""
    return latest if cfg.get("update_check") == "1" and parse(latest) > parse(current()) else ""


def check(force: bool = False) -> str | None:
    """Fragt die aktuelle Versionsnummer ab (höchstens einmal täglich). Gibt sie zurück oder None."""
    with SessionLocal() as db:
        cfg = get_settings(db)
        if cfg.get("update_check") != "1" or not CHECK_URL:
            return None
        last = cfg.get("update_checked_at") or ""
        try:
            if not force and last and utcnow() - datetime.fromisoformat(last) < INTERVAL:
                return cfg.get("update_latest") or None
        except ValueError:
            pass
        set_setting(db, "update_checked_at", utcnow().isoformat(timespec="seconds"))
        db.commit()
        try:
            r = httpx.get(CHECK_URL, timeout=10, follow_redirects=True, headers={"User-Agent": "Verwaltungsportal-Updatecheck"})
            r.raise_for_status()
            latest = r.text.strip()[:30]
        except httpx.HTTPError as exc:
            log.info("Update-Prüfung nicht möglich: %s", exc)
            return None
        if not _VERSION_RE.match(latest):
            return None
        set_setting(db, "update_latest", latest)
        db.commit()
        return latest
