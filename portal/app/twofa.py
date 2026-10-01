"""Zwei-Faktor-Anmeldung: Einmalcode per E-Mail, Authenticator-App (TOTP, RFC 6238) und Wiederherstellungscodes.

Der Admin legt fest, welche Verfahren erlaubt sind und für wen 2FA Pflicht ist (niemand, Admins, alle).
Ist 2FA Pflicht und hat jemand keine App eingerichtet, wird automatisch der Code per E-Mail verwendet;
ist auch der nicht erlaubt, muss die App direkt nach der Anmeldung eingerichtet werden.
"""

import base64
import hashlib
import hmac
import io
import json
import secrets
import struct
import time
from datetime import timedelta
from urllib.parse import quote

import segno

from . import branding, mailtpl, notify
from .db import User, get_settings, utcnow
from .security import decrypt, encrypt, hash_token

PERIOD = 30
DIGITS = 6
EMAIL_CODE_MINUTES = 10
MAX_TRIES = 5
RECOVERY_COUNT = 10
REQUIRED = {"off": "Freiwillig", "admins": "Pflicht für Administrator:innen", "all": "Pflicht für alle"}


# --- Richtlinie ------------------------------------------------------------------

def allowed(cfg: dict) -> dict[str, bool]:
    return {"email": cfg.get("mfa_email_allowed", "1") == "1", "totp": cfg.get("mfa_totp_allowed", "1") == "1"}


def required(user: User, cfg: dict) -> bool:
    mode = cfg.get("mfa_required", "off")
    return mode == "all" or (mode == "admins" and user.is_admin)


def methods(user: User, cfg: dict) -> list[str]:
    """Verfahren, mit denen sich die Person beim Anmelden ausweisen muss (leer = kein zweiter Faktor)."""
    ok = allowed(cfg)
    found = []
    if ok["totp"] and user.totp_enabled:
        found.append("totp")
    if ok["email"] and (user.mfa_email or (required(user, cfg) and not found)):
        found.append("email")
    return found


def needs_setup(user: User, cfg: dict) -> bool:
    """Pflicht, aber kein nutzbares Verfahren: App muss eingerichtet werden."""
    return required(user, cfg) and not methods(user, cfg)


# --- TOTP --------------------------------------------------------------------------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def totp_now(secret: str, at: float | None = None) -> str:
    return _code(secret, int((at or time.time()) // PERIOD))


def check_totp(secret: str, code: str, last_step: int | None = None, at: float | None = None) -> int | None:
    """Prüft einen Code (±1 Zeitschritt). Gibt den Zeitschritt zurück oder None. Schon benutzte Codes zählen nicht."""
    code = "".join(c for c in code or "" if c.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    now = int((at or time.time()) // PERIOD)
    for step in (now - 1, now, now + 1):
        if (last_step is None or step > last_step) and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, user: User) -> str:
    issuer = branding.load()["name"]
    label = quote(f"{issuer}:{user.email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}"


def qr_svg(uri: str) -> str:
    buf = io.BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2, xmldecl=False, svgns=True,
                                   dark="#000000", light="#ffffff")
    return buf.getvalue().decode("utf-8")


def enable_totp(user: User, secret: str) -> None:
    user.totp_secret_enc = encrypt(secret)
    user.totp_enabled = True


def user_secret(user: User) -> str:
    return decrypt(user.totp_secret_enc) or ""


# --- Code per E-Mail ----------------------------------------------------------------

def send_email_code(db, user: User) -> bool:
    code = "".join(secrets.choice("0123456789") for _ in range(DIGITS))
    user.email_code_hash = hash_token(f"{user.id}:{code}")
    user.email_code_expires = utcnow() + timedelta(minutes=EMAIL_CODE_MINUTES)
    cfg = get_settings(db)
    subject, body = mailtpl.render(db, "login_code", {"name": user.name, "code": code,
                                                      "minuten": EMAIL_CODE_MINUTES}, cfg)
    return notify.enqueue(db, user.email, subject, body, "login_code", cfg)


def check_email_code(user: User, code: str) -> bool:
    code = "".join(c for c in code or "" if c.isdigit())
    if not user.email_code_hash or not user.email_code_expires or user.email_code_expires < utcnow():
        return False
    if hmac.compare_digest(user.email_code_hash, hash_token(f"{user.id}:{code}")):
        user.email_code_hash = user.email_code_expires = None  # nur einmal gültig
        return True
    return False


# --- Wiederherstellungscodes --------------------------------------------------------

def new_recovery_codes(user: User) -> list[str]:
    codes = ["-".join(secrets.token_hex(2) for _ in range(3)) for _ in range(RECOVERY_COUNT)]
    user.recovery_json = json.dumps([hash_token(c) for c in codes])
    return codes


def recovery_left(user: User) -> int:
    try:
        return len(json.loads(user.recovery_json or "[]"))
    except ValueError:
        return 0


def use_recovery_code(user: User, code: str) -> bool:
    code = (code or "").strip().lower().replace(" ", "")
    try:
        hashes = json.loads(user.recovery_json or "[]")
    except ValueError:
        return False
    digest = hash_token(code)
    if digest in hashes:
        hashes.remove(digest)
        user.recovery_json = json.dumps(hashes)
        return True
    return False


def reset(user: User) -> None:
    """Alle Verfahren zurücksetzen (z. B. bei verlorenem Telefon, durch die Verwaltung)."""
    user.totp_enabled, user.totp_secret_enc, user.totp_last_step = False, None, None
    user.mfa_email, user.recovery_json = False, None
    user.email_code_hash = user.email_code_expires = None
