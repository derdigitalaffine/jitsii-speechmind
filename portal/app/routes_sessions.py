"""Technik: angemeldete Benutzer, Sitzungen und Session-Cookies (Admin) sowie eigene Sitzungen (Profil)."""

import base64
import json

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, TimestampSigner
from sqlalchemy.orm import Session

from . import sessions
from .config import settings
from .db import User, UserSession, to_local
from .main import admin_user, app, check_csrf, current_user, flash, get_db, redirect, render

# Bekannte Cookies des Portals (Name bzw. Präfix → Zweck)
KNOWN_COOKIES = {
    sessions.COOKIE_NAME: "Anmeldung und Sitzung des Portals (signiert, nicht verschlüsselt)",
    "jsm_poll_": "Terminumfrage: eigene Stimme später ändern (je Umfrage, 180 Tage)",
}
SECRET_KEYS = {"sid", "csrf", "totp_setup", "recovery_codes"}


def _mask(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 8 else text[:4] + "…" + f" ({len(text)} Zeichen)"


def _cookie_purpose(name: str) -> str:
    for key, label in KNOWN_COOKIES.items():
        if name == key or (key.endswith("_") and name.startswith(key)):
            return label
    return "fremdes oder unbekanntes Cookie (z. B. einer anderen Anwendung auf derselben Domain)"


def _decode_session_cookie(raw: str | None) -> dict:
    """Inhalt des eigenen Session-Cookies lesbar machen (Geheimnisse gekürzt)."""
    if not raw:
        return {"present": False}
    info = {"present": True, "size": len(raw), "entries": [], "signed_at": None, "valid": False}
    try:
        payload, signed_at = TimestampSigner(str(settings.secret_key)).unsign(raw.encode(), return_timestamp=True)
        data = json.loads(base64.b64decode(payload))
        info["valid"], info["signed_at"] = True, to_local(signed_at.replace(tzinfo=None))
    except (BadSignature, ValueError):
        return info
    for key in sorted(data):
        value = data[key]
        shown = _mask(value) if key in SECRET_KEYS else (
            value if isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=False))
        info["entries"].append({"key": key, "value": str(shown)[:200], "secret": key in SECRET_KEYS})
    return info


def _rows(db: Session, request: Request, items: list[UserSession]) -> list[dict]:
    return sessions.rows(request, items)


@app.get("/admin/sessions")
def admin_sessions(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = _rows(db, request, sessions.active(db))
    users = {}
    for r in rows:
        entry = users.setdefault(r["s"].user_id, {"user": r["s"].user, "count": 0, "online": False,
                                                  "last": r["s"].last_seen_at})
        entry["count"] += 1
        entry["online"] = entry["online"] or r["online"]
        entry["last"] = max(entry["last"], r["s"].last_seen_at)
    cookies = [{"name": name, "size": len(value), "value": _mask(value), "purpose": _cookie_purpose(name)}
               for name, value in sorted(request.cookies.items())]
    config = {"name": sessions.COOKIE_NAME, "max_age": sessions.MAX_AGE // 3600, "secure": settings.secure_cookies,
              "samesite": "Lax", "httponly": True, "path": "/"}
    return render(request, "admin_sessions.html", user, rows=rows, users=sorted(users.values(), key=lambda e: e["last"],
                  reverse=True), cookies=cookies, config=config,
                  own=_decode_session_cookie(request.cookies.get(sessions.COOKIE_NAME)),
                  online_minutes=sessions.ONLINE_MINUTES)


@app.post("/admin/sessions/{session_id}/end", dependencies=[Depends(check_csrf)])
def admin_session_end(request: Request, session_id: int, user: User = Depends(admin_user),
                      db: Session = Depends(get_db)):
    row = db.get(UserSession, session_id)
    if row is None:
        raise HTTPException(404, "Sitzung nicht gefunden (vielleicht schon abgemeldet).")
    own = row.sid_hash == sessions.current_hash(request)
    name = row.user.name
    db.delete(row)
    db.commit()
    if own:
        request.session.clear()
        return redirect("/login")
    flash(request, f"Sitzung von {name} beendet. Beim nächsten Klick muss sich die Person neu anmelden.")
    return redirect("/admin/sessions")


@app.post("/admin/sessions/user/{user_id}/end", dependencies=[Depends(check_csrf)])
def admin_sessions_end_user(request: Request, user_id: int, user: User = Depends(admin_user),
                            db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Benutzer nicht gefunden.")
    keep = sessions.current_hash(request) if target.id == user.id else None
    count = sessions.end_all(db, target.id, keep_hash=keep)
    flash(request, f"{count} Sitzung(en) von {target.name} beendet." + (" Ihre aktuelle Sitzung bleibt bestehen."
                                                                         if keep else ""))
    return redirect("/admin/sessions")


@app.post("/admin/sessions/purge", dependencies=[Depends(check_csrf)])
def admin_sessions_end_others(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Alle Sitzungen außer der eigenen beenden (z. B. nach einem Sicherheitsvorfall)."""
    mine = sessions.current_hash(request)
    count = db.query(UserSession).filter(UserSession.sid_hash != mine).delete()
    db.commit()
    flash(request, f"{count} Sitzung(en) beendet. Alle anderen müssen sich neu anmelden.")
    return redirect("/admin/sessions")


# --- Eigene Sitzungen (Profil › Sicherheit) -----------------------------------

@app.post("/profile/sessions/{session_id}/end", dependencies=[Depends(check_csrf)])
def profile_session_end(request: Request, session_id: int, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    row = db.get(UserSession, session_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Sitzung nicht gefunden.")
    own = row.sid_hash == sessions.current_hash(request)
    db.delete(row)
    db.commit()
    if own:
        request.session.clear()
        return redirect("/login")
    flash(request, "Die Anmeldung auf dem anderen Gerät wurde beendet.")
    return redirect("/profile/security#sitzungen")


@app.post("/profile/sessions/others/end", dependencies=[Depends(check_csrf)])
def profile_sessions_end_others(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    count = sessions.end_all(db, user.id, keep_hash=sessions.current_hash(request))
    flash(request, f"{count} andere Anmeldung(en) beendet." if count else "Es gab keine anderen Anmeldungen.")
    return redirect("/profile/security#sitzungen")

