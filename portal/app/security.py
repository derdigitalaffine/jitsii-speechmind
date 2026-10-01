import base64
import hashlib
import hmac
import re
import secrets
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# --- Verschlüsselung gespeicherter API-Keys ---------------------------------

def _fernet() -> Fernet:
    digest = hashlib.sha256(("api-key-encryption:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "•" * 8 + value[-4:]


# --- CSRF -------------------------------------------------------------------

def csrf_token(session: dict) -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def csrf_valid(session: dict, token: str | None) -> bool:
    expected = session.get("csrf")
    return bool(expected and token and hmac.compare_digest(expected, token))


# --- Räume & Jitsi-JWT ------------------------------------------------------

_ROOM_RE = re.compile(r"[^a-z0-9-]+")


def room_slug(text: str) -> str:
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    text = text.lower()
    for a, b in replacements.items():
        text = text.replace(a, b)
    slug = _ROOM_RE.sub("-", text).strip("-")
    slug = re.sub("-{2,}", "-", slug)[:60].strip("-")
    return slug or "meeting"


def clean_room(room: str) -> str:
    """Raumname aus Jitsi-URL normalisieren (Jitsi arbeitet intern kleingeschrieben)."""
    room = (room or "").strip().split("?")[0].split("#")[0].strip("/").lower()
    room = room.rsplit("/", 1)[-1]
    return re.sub(r"[^a-z0-9._-]", "", room)[:128]


def jitsi_token(user, room: str) -> str:
    now = int(time.time())
    payload = {
        "aud": settings.jwt_audience,
        "iss": settings.jwt_app_id,
        "sub": "*",
        "room": room,
        "iat": now,
        "nbf": now - 10,
        "exp": now + settings.jwt_ttl_minutes * 60,
        "context": {
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "moderator": True,
            },
            "features": {
                "recording": True,
                "livestreaming": False,
                "transcription": False,
                "outbound-call": False,
            },
        },
    }
    return jwt.encode(payload, settings.jwt_app_secret, algorithm="HS256")


# --- Einladungs- und Zurücksetzen-Links ---------------------------------------

def new_token() -> tuple[str, str]:
    """Liefert (Token für den Link, Hash für die Datenbank)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
