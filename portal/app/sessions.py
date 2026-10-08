"""Serverseitige Erfassung angemeldeter Sitzungen.

Die Sitzung selbst steckt weiterhin im signierten Cookie „jsm_session“ (Starlette). Zusätzlich trägt das
Cookie eine zufällige Kennung („sid“); in der Datenbank liegt nur deren SHA-256-Hash mit Zeitpunkten,
Adresse und Browser. So lassen sich angemeldete Personen anzeigen und Sitzungen gezielt beenden: Fehlt der
Datensatz, gilt das Cookie nicht mehr.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select

from .db import User, UserSession, utcnow

COOKIE_NAME = "jsm_session"
MAX_AGE = 60 * 60 * 12           # wie SessionMiddleware(max_age=…): Ablauf nach 12 Stunden ohne Aufruf
TOUCH_EVERY = 60                 # „zuletzt aktiv“ höchstens einmal pro Minute schreiben
ONLINE_MINUTES = 5               # gilt als „gerade aktiv“


def _hash(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


def client_ip(request) -> str:
    # Hinter Caddy setzt Uvicorn (--proxy-headers) die echte Adresse; den Kopf selbst nicht auswerten (fälschbar)
    return request.client.host if request.client else "?"


def establish(request, db, user: User, method: str = "password", oidc_flow=None) -> None:
    """Nach erfolgreicher Anmeldung: Kennung erzeugen, im Cookie ablegen, Datensatz anlegen."""
    sid = secrets.token_urlsafe(24)
    row=UserSession(sid_hash=_hash(sid), user_id=user.id, ip=client_ip(request)[:64],
                       user_agent=request.headers.get("user-agent", "")[:400], method=method,
                       last_path=request.url.path[:255])
    if oidc_flow is not None:
        from . import oidc
        oidc.bind_session(db,row,oidc_flow,user)
    db.add(row)
    db.commit()
    request.session["uid"] = user.id
    request.session["sid"] = sid
    import time
    request.session["auth_at"] = time.time()
    request.session["auth_method"] = row.method


def validate(request, db, user: User) -> bool:
    """Prüft die Kennung im Cookie und aktualisiert „zuletzt aktiv“. Ältere Cookies ohne Kennung werden
    einmalig nachgetragen, damit nach einem Update niemand abgemeldet wird."""
    sid = request.session.get("sid")
    if not sid:
        establish(request, db, user, method="bestehend")
        return True
    row = db.scalar(select(UserSession).where(UserSession.sid_hash == _hash(sid)))
    if row is None or row.user_id != user.id:
        return False
    now = utcnow()
    from . import oidc
    cfg=oidc.config(db) if row.oidc_identity_id else None
    if not oidc.session_valid(db,row,cfg):
        db.delete(row);db.commit();return False
    if cfg:request.session["oidc_central"] = bool(cfg["central_logout"] and cfg.get("metadata",{}).get("end_session_endpoint"))
    if (now - row.last_seen_at).total_seconds() > MAX_AGE:
        db.delete(row)
        db.commit()
        return False
    if (now - row.last_seen_at).total_seconds() > TOUCH_EVERY:
        row.last_seen_at = now
        row.ip = client_ip(request)[:64]
        row.last_path = request.url.path[:255]
        db.commit()
    return True


def current_hash(request) -> str | None:
    sid = request.session.get("sid")
    return _hash(sid) if sid else None


def end(request, db) -> None:
    """Abmelden: Datensatz der eigenen Sitzung entfernen."""
    sid = request.session.get("sid")
    if sid:
        db.execute(delete(UserSession).where(UserSession.sid_hash == _hash(sid)))
        db.commit()


def purge(db) -> int:
    """Abgelaufene Sitzungen löschen."""
    cutoff = utcnow() - timedelta(seconds=MAX_AGE)
    result = db.execute(delete(UserSession).where(UserSession.last_seen_at < cutoff))
    from . import oidc
    oidc.purge(db)
    db.commit()
    return result.rowcount or 0


def active(db) -> list[UserSession]:
    purge(db)
    return list(db.scalars(select(UserSession).order_by(UserSession.last_seen_at.desc())))


def for_user(db, user_id: int) -> list[UserSession]:
    purge(db)
    return list(db.scalars(select(UserSession).where(UserSession.user_id == user_id)
                           .order_by(UserSession.last_seen_at.desc())))


def end_all(db, user_id: int, keep_hash: str | None = None) -> int:
    q = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_hash:
        q = q.where(UserSession.sid_hash != keep_hash)
    result = db.execute(q)
    db.commit()
    return result.rowcount or 0


def describe_agent(ua: str) -> str:
    """Grobe, verständliche Browser-/Systemangabe aus dem User-Agent."""
    ua = ua or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in ua), "")
    system = next((name for key, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"),
                                          ("iPad", "iPad"), ("Mac OS X", "macOS"), ("Linux", "Linux")) if key in ua), "")
    if not browser and not system:
        return ua[:60] or "unbekannt"
    return " auf ".join(p for p in (browser or "Browser", system) if p)


def is_online(row: UserSession) -> bool:
    return (utcnow() - row.last_seen_at).total_seconds() < ONLINE_MINUTES * 60


def rows(request, items: list[UserSession]) -> list[dict]:
    """Für die Anzeige: Sitzung, gerade aktiv?, Browser, eigene Sitzung?"""
    mine = current_hash(request)
    return [{"s": s, "online": is_online(s), "agent": describe_agent(s.user_agent), "current": s.sid_hash == mine}
            for s in items]
