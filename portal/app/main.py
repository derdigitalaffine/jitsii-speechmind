import asyncio
import base64
import ipaddress
import json
import re
import logging
import secrets
import shutil
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import access, branding, chat, csp, links, mailtpl, modhosts, notify, planning, proxy, sessions, twofa, worker
from .planning import EMAIL_RE, name_from_email
from .config import settings
from .db import (
    ACTIVE_STATUSES, PERMISSIONS, Group, Invitee, STATUS_DONE, STATUS_FAILED, STATUS_PROCESSING, STATUS_QUEUED, STATUS_RECORDED,
    STATUS_REMOTE, Meeting,
    Notification, Recording, SessionLocal, User, get_settings, init_db, set_setting, to_local, utcnow,
)
from .security import (
    clean_room, csrf_token, csrf_valid, decrypt, encrypt, hash_password, hash_token,
    guest_token, jitsi_token, mask_secret, new_link_token, new_token, room_slug,
    verify_password,
)
from .speechmind import SpeechMindClient, SpeechMindError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("portal")
BASE = Path(__file__).parent

DOCUMENT_TYPES = {
    "summary": "Besprechungsprotokoll (Zusammenfassung mit Aufgaben)",
    "politics": "Sitzungsprotokoll (Gremien, mit Beschlüssen)",
}
LANGUAGES = {"de-DE": "Deutsch", "en-US": "Englisch"}
PIPELINE = [
    ("recorded", "Aufgezeichnet"),
    ("converting", "Audiospur"),
    ("uploading", "Upload"),
    ("processing", "SpeechMind"),
    ("done", "Transkript"),
]
STATUS_LABELS = {
    "new": "MP3 wird erzeugt",
    "recorded": "MP3 bereit",
    "queued": "Wartet",
    "converting": "Audiospur wird extrahiert",
    "uploading": "Wird hochgeladen",
    "processing": "SpeechMind transkribiert",
    "done": "Transkript fertig",
    "remote": "Bei SpeechMind abrufbar",
    "failed": "Fehlgeschlagen",
}


def bootstrap_admin() -> None:
    """Legt beim allerersten Start das Standard-Administratorkonto an."""
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))) == 0:
            password = settings.admin_password or secrets.token_urlsafe(12)
            db.add(User(
                email=settings.admin_email, name="Administrator",
                password_hash=hash_password(password), is_admin=True,
                must_change_password=True,
            ))
            db.commit()
            log.warning("Standard-Admin angelegt: %s", settings.admin_email)
            if not settings.admin_password:
                log.warning("Startpasswort (einmalig, bitte nach der Anmeldung ändern): %s", password)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    bootstrap_admin()
    with SessionLocal() as db:
        proxy.sync(get_settings(db))
        access.sync(db)
        try:
            from . import laws as _laws
            _laws.reparse_all(db)
        except Exception:   # noqa: BLE001 – ein fehlerhafter Text darf den Start nicht verhindern
            db.rollback()
            logging.getLogger("portal").exception("Rechtstexte: Neuzerlegen der Gliederung fehlgeschlagen")
    chat.prepare_dir()
    task = asyncio.create_task(worker.run_forever())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="jsm_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=settings.secure_cookies,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.add_extension(csp.NonceExtension)
templates.env.globals["csp_nonce"] = csp.current_nonce
_HANDLER_HASHES = " ".join(csp.handler_hashes(BASE / "templates"))
templates.env.globals.update(brand=settings.brand_name, product=settings.brand_product)
templates.env.globals["themes"] = branding.THEMES
templates.env.globals["org_logo"] = lambda o: __import__("app.orgs", fromlist=["logo_url"]).logo_url(o)
templates.env.globals["permissions"] = PERMISSIONS
# Rechte, deren Modul anders heißt als das Recht (für die Auswahl in der Benutzerverwaltung)
def _forms_mod():
    from . import forms
    return forms


templates.env.filters["geocenter"] = lambda v: _forms_mod().geo_center(v)
templates.env.filters["geoinput"] = lambda v: _forms_mod().geo_input(v)
templates.env.globals["geo_position"] = lambda v, raw="": _forms_mod().geo_position(v, raw)
templates.env.globals["perm_modules"] = {"processes": "applications", "app_create": "applications", "formblocks": "forms",
                                         "dms_admin": "dms", "seminars_manage": "seminars", "votes": "polls", "resources": "resources",
                                         "krank": "krank", "krank_admin": "krank"}
templates.env.globals.update(planning_when=planning.when, cancel_recipients=planning.cancel_recipients, local_input=planning.local_input,
                             is_upcoming=planning.is_upcoming, rsvp_labels=planning.RSVP_LABELS,
                             rsvp_summary=planning.rsvp_summary)
from .shortlinks import QR_ERRORS as _QR_ERRORS  # noqa: E402
templates.env.globals["qr_errors"] = _QR_ERRORS


def _public_url(key: str, path: str) -> str:
    """Öffentliche Adresse eines Moduls (eigene Domain, falls eingerichtet) – für QR-Codes und Links."""
    from . import links
    return links.base(key) + path


templates.env.globals["public_url"] = _public_url
templates.env.filters["isodate"] = lambda value: datetime.fromisoformat(value) if value else None
templates.env.filters["filesize"] = lambda n: (
    "" if not n else f"{n / 1_000_000:.1f} MB".replace(".", ",") if n >= 1_000_000 else f"{max(n // 1000, 1)} kB")
_LINK_RE = re.compile(r"(https?://[^\s<>\"]+)")


def _richtext(text: str | None) -> Markup:
    """Beschreibungstexte: HTML maskiert, Links anklickbar, **fett**, Zeilenumbrüche erhalten."""
    escaped = str(escape(text or ""))
    escaped = _LINK_RE.sub(lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>', escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    if "[[" in escaped and "laws" in enabled_modules():   # [[HStS § 4]] → Link mit Vorschau auf den Rechtstext
        from . import laws
        escaped = laws.shortcodes(escaped)
    return Markup(escaped.replace("\n", "<br>"))


templates.env.filters["richtext"] = _richtext
templates.env.filters["local"] = lambda dt, fmt="%d.%m.%Y, %H:%M": to_local(dt).strftime(fmt) if dt else ""


# --- Zusatzmodule -------------------------------------------------------------

# Modul: (Einstellung, Rechte-Schlüssel, Pfad-Präfixe)
MODULES = {
    "seminars": ("Seminare & Lehrgänge", "module_seminars", ("/seminare",)),
    "shortlinks": ("Kurzlinks & QR-Codes", "module_shortlinks", ("/shortlinks", "/s/", "/s")),
    "forms": ("Formulare", "module_forms", ("/forms", "/f/")),
    "polls": ("Umfragen & Abstimmungen", "module_polls", ("/polls", "/t/", "/votes", "/v/", "/l/")),
    "bookings": ("Terminbuchung", "module_bookings", ("/bookings", "/b/", "/b")),
    "laws": ("Rechtstexte", "module_laws", ("/laws", "/recht")),
    "maps": ("Kartenbrowser", "module_maps", ("/karte", "/maps")),
    "applications": ("Online-Anträge", "module_applications", ("/antraege", "/a/", "/processes")),
    "circulations": ("Umläufe & Aushänge", "module_circulations", ("/umlaeufe",)),
    "dms": ("Ablage (DMS)", "module_dms", ("/dms",)),
    "resources": ("Ressourcenbuchung", "module_resources", ("/resources", "/r/", "/r", "/r-embed")),
    "krank": ("BlueOtter Krankmelder", "module_krank", ("/krank", "/krankmelder")),
}
_module_cache: dict = {"at": 0.0, "enabled": set(MODULES)}


def enabled_modules() -> set[str]:
    """Eingeschaltete Zusatzmodule (für einige Sekunden zwischengespeichert)."""
    if time.monotonic() - _module_cache["at"] > 5:
        with SessionLocal() as db:
            cfg = get_settings(db)
        enabled = {key for key, (_, setting, _) in MODULES.items() if cfg.get(setting, "1") == "1"}
        if "forms" not in enabled:
            enabled.discard("applications")   # Anträge bauen auf dem Formularserver auf
        _module_cache["enabled"] = enabled
        _module_cache["at"] = time.monotonic()
    return _module_cache["enabled"]


def module_for_path(path: str) -> str | None:
    for key, (_, _, prefixes) in MODULES.items():
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix.rstrip("/") + "/") or path.startswith(prefix + "-"):
                return key
    return None


_MEET_ORIGIN = "{0.scheme}://{0.netloc}".format(urlparse(settings.meet_base_url)) if settings.meet_base_url else ""


def build_csp(frame_ancestors: str = "'none'", hosts: list[str] | tuple = (), nonce: str = "") -> str:
    """Content-Security-Policy für Portalseiten. Alle Bibliotheken liegen lokal, daher nur 'self'.
    Inline-Skripte nur mit der Nonce dieser Antwort (siehe csp.py), Inline-Handler nur mit bekanntem Hash.
    Die Richtlinie verhindert so eingeschleuste Skripte, Datenabfluss zu fremden Servern, <base>/<object>-Tricks
    und Formulare an fremde Ziele.
    hosts: zusätzliche Herkünfte für Bilder und Abrufe (direkt geladene Kartendienste)."""
    form_targets = " ".join(x for x in ("'self'", _MEET_ORIGIN) if x)
    extra = "".join(" " + h for h in hosts if re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?", h))
    scripts = "'self'" + (f" 'nonce-{nonce}'" if nonce else "") + (f" 'unsafe-hashes' {_HANDLER_HASHES}" if _HANDLER_HASHES else "")
    return (f"default-src 'self'; script-src {scripts}; style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data: blob:{extra}; font-src 'self' data:; connect-src 'self'{extra}; "
            "media-src 'self' blob:; frame-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
            f"form-action {form_targets}; frame-ancestors {frame_ancestors}")


# Seiten, die sich in fremde Webseiten einbetten lassen: Pfad-Präfix → (Schalter, erlaubte Herkünfte)
EMBED_PREFIXES = {"/recht-embed": ("laws_embed", "laws_embed_origins"),
                  "/karte-embed": ("maps_embed", "maps_embed_origins"),
                  "/antraege-embed": ("apps_embed", "apps_embed_origins"),
                  "/r-embed": ("resources_embed", "resources_embed_origins"),
                  "/krank-embed": ("krank_embed", "krank_embed_origins")}
EMBED_ORIGIN_RE = re.compile(r"^https?://[a-z0-9.-]+(:\d+)?$|^https?://\*\.[a-z0-9.-]+$", re.I)


def embed_prefix(path: str) -> str | None:
    return next((p for p in EMBED_PREFIXES if path == p or path.startswith(p + "/")), None)


def embed_origins(db, prefix: str) -> list[str]:
    raw = get_settings(db).get(EMBED_PREFIXES[prefix][1], "")
    return [o for o in re.split(r"[\s,;]+", raw) if EMBED_ORIGIN_RE.match(o)]


def embed_enabled(db, prefix: str) -> bool:
    return get_settings(db).get(EMBED_PREFIXES[prefix][0], "1") == "1"


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    # Standort nur für das Portal selbst (GPS-Fragen in Formularen, Kartenbrowser)
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(self), payment=(), usb=(), interest-cohort=()",
}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Schutz-Header für alle Antworten (zusätzlich zu denen des Reverse Proxys)."""
    nonce = csp.new_nonce()
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    prefix = embed_prefix(request.url.path)
    frame_ancestors = "'none'"
    if prefix:
        # Einbettbar (iframe): nur die freigegebenen Webseiten, ohne Liste alle
        with SessionLocal() as db:
            origins = embed_origins(db, prefix)
        frame_ancestors = " ".join(["'self'", *origins]) if origins else "*"
        if "x-frame-options" in response.headers:
            del response.headers["x-frame-options"]
    elif "x-frame-options" not in response.headers:
        response.headers["X-Frame-Options"] = "DENY"
    if "content-security-policy" not in response.headers and \
            response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Content-Security-Policy"] = build_csp(frame_ancestors,
                                                                getattr(request.state, "csp_hosts", ()), nonce)
    logged_in = bool(request.scope.get("session", {}).get("uid")) if "session" in request.scope else False
    if (logged_in or request.url.path.startswith(("/admin", "/profile", "/login", "/invite", "/laws"))) and \
            response.headers.get("content-type", "").startswith(("text/html", "application/json")):
        # Seiten mit persönlichen Daten nicht im Browser-Cache ablegen (gemeinsam genutzte Rechner, Zurück-Taste)
        response.headers.setdefault("Cache-Control", "no-store")
    if request.url.path.startswith("/static/"):
        # Eigene Skripte/Stile nach einem Update sofort neu laden (Browser fragt mit ETag nach, meist 304);
        # Bibliotheken unter vendor/ ändern sich selten und dürfen einen Tag im Cache bleiben.
        response.headers.setdefault("Cache-Control", "public, max-age=86400" if request.url.path.startswith("/static/vendor/")
                                    else "no-cache")
    return response


@app.middleware("http")
async def _module_gate(request: Request, call_next):
    """Abgeschaltete Module sind vollständig unerreichbar (auch öffentliche Links)."""
    key = module_for_path(request.url.path)
    if key and key not in enabled_modules():
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Nicht verfügbar</title>"
                            "<p style='font-family:sans-serif;margin:3rem'>Diese Funktion ist auf diesem Server "
                            "nicht eingeschaltet.</p>", status_code=404)
    return await call_next(request)


_host_cache: dict = {"at": 0.0, "map": {}}


def module_hosts() -> dict[str, str]:
    """Eigene Domains der Module: Domain → Modul (für einige Sekunden zwischengespeichert)."""
    if time.monotonic() - _host_cache["at"] > 5:
        with SessionLocal() as db:
            _host_cache["map"] = modhosts.host_map(get_settings(db))
        _host_cache["at"] = time.monotonic()
    return _host_cache["map"]


@app.middleware("http")
async def _module_host(request: Request, call_next):
    """Aufruf über die eigene Domain eines Moduls: nur dessen öffentliche Seiten und gemeinsame Hilfspfade;
    „/“ führt zur Einstiegsseite, alles andere zur gleichen Adresse unter der Portal-Domain."""
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    key = module_hosts().get(host) if host else None
    if key is None:
        return await call_next(request)
    path = request.url.path
    if key not in enabled_modules():
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Nicht verfügbar</title>"
                            "<p style='font-family:sans-serif;margin:3rem'>Diese Funktion ist auf diesem Server "
                            "nicht eingeschaltet.</p>", status_code=404)
    if path == "/":
        start = modhosts.start_path(key)
        return RedirectResponse(start or settings.portal_base_url + "/", status_code=302)
    if modhosts.allowed(key, path):
        return await call_next(request)
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(settings.portal_base_url + path + query, status_code=302 if request.method == "GET" else 307)


# --- Hilfsfunktionen ----------------------------------------------------------

class LoginRequired(Exception):
    def __init__(self, next_url: str):
        self.next_url = next_url


@app.exception_handler(LoginRequired)
async def _login_redirect(_request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)


class ForcedRedirect(Exception):
    def __init__(self, url: str):
        self.url = url


@app.exception_handler(ForcedRedirect)
async def _forced_redirect(_request: Request, exc: ForcedRedirect):
    return RedirectResponse(exc.url, status_code=303)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None or not user.active:
        request.session.pop("uid", None)
        raise LoginRequired(str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""))
    if not sessions.validate(request, db, user):
        request.session.clear()
        flash(request, "Ihre Sitzung wurde beendet. Bitte melden Sie sich erneut an.", "error")
        raise LoginRequired(str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""))
    if user.must_change_password and request.url.path != "/profile":
        flash(request, "Bitte vergeben Sie zuerst ein eigenes Passwort.", "error")
        raise ForcedRedirect("/profile")
    if request.session.get("mfa_setup") and not request.url.path.startswith("/profile"):
        if twofa.needs_setup(user, get_settings(db)):
            flash(request, "Für Ihr Konto ist die Zwei-Faktor-Anmeldung Pflicht. Bitte richten Sie jetzt die "
                           "Authenticator-App ein.", "error")
            raise ForcedRedirect("/profile/security")
        request.session.pop("mfa_setup", None)
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Nur für Administratoren.")
    return user


def require(perm: str):
    """Abhängigkeit: angemeldet und für den Bereich freigeschaltet (Admins immer)."""
    def dep(user: User = Depends(current_user)) -> User:
        if not user.can(perm):
            raise HTTPException(403, f"Für den Bereich „{PERMISSIONS[perm][0]}“ fehlt die Berechtigung. "
                                     "Bitte wenden Sie sich an die Verwaltung des Portals.")
        return user
    return dep


video_user = require("video")
users_manager = require("users")


def home_for(user: User) -> str:
    """Startseite nach dem Login: das Dashboard (zeigt nur, was die Person nutzen darf)."""
    return "/"


_attempts: "OrderedDict[str, list[float]]" = OrderedDict()
_ATTEMPTS_MAX = 20000


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def client_ip(request: Request) -> str:
    """Adresse der Gegenstelle. Uvicorn setzt sie hinter Caddy aus X-Forwarded-For (Caddy überschreibt den
    Kopf mit der echten Adresse); IPv6-Adressen werden auf ihr /64-Netz gekürzt, weil ein Anschluss meist ein
    ganzes /64 hat."""
    host = request.client.host if request.client else "?"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def rate_limit(request: Request, bucket: str, limit: int = 10, window: int = 600, key: str | None = None) -> None:
    """Einfache Bremse gegen Passwort-Raten und Mail-Fluten (pro IP-Adresse oder eigenem Schlüssel, im Speicher)."""
    key, now = f"{bucket}:{key if key is not None else client_ip(request)}", time.monotonic()
    hits = [t for t in _attempts.get(key, []) if now - t < window]
    if len(hits) >= limit:
        _attempts[key] = hits
        _attempts.move_to_end(key)
        raise HTTPException(429, "Zu viele Versuche. Bitte in einigen Minuten erneut versuchen.")
    hits.append(now)
    _attempts[key] = hits
    _attempts.move_to_end(key)
    # Älteste Einträge verwerfen statt alles zu leeren (sonst ließe sich die Bremse durch viele Schlüssel zurücksetzen)
    while len(_attempts) > _ATTEMPTS_MAX:
        _attempts.popitem(last=False)


_stash: "OrderedDict[tuple[str, str], tuple[float, object]]" = OrderedDict()
STASH_SECONDS = 1800


def stash_put(request: Request, name: str, value) -> None:
    """Geheimnisse (TOTP-Schlüssel, Wiederherstellungscodes, Einladungslinks) für die nächste Seite im Speicher
    des Servers ablegen statt im Sitzungscookie – das ist nur signiert, nicht verschlüsselt."""
    sid = request.session.get("_stash") or secrets.token_urlsafe(16)
    request.session["_stash"] = sid
    _stash[(sid, name)] = (time.monotonic(), value)
    _stash.move_to_end((sid, name))
    while len(_stash) > 5000:
        _stash.popitem(last=False)


def stash_get(request: Request, name: str, pop: bool = False):
    sid = request.session.get("_stash")
    if not sid:
        return None
    item = _stash.pop((sid, name), None) if pop else _stash.get((sid, name))
    if item is None or time.monotonic() - item[0] > STASH_SECONDS:
        _stash.pop((sid, name), None)
        return None
    return item[1]


async def check_csrf(request: Request) -> None:
    form = await request.form()
    if not csrf_valid(request.session, form.get("csrf")):
        raise HTTPException(400, "Sitzung abgelaufen. Bitte Seite neu laden und erneut versuchen.")


def flash(request: Request, message: str, kind: str = "ok") -> None:
    # neu zuweisen statt anhängen: die Sitzung merkt Änderungen nur beim Setzen eines Schlüssels
    request.session["flash"] = [*request.session.get("flash", []), {"kind": kind, "text": message}]


def _shared_nav(user: User | None) -> set[str]:
    """Bereiche, die im Menü erscheinen, weil etwas mit der Person geteilt wurde (ohne eigenes Recht)."""
    kinds = (("polls", "poll"), ("bookings", "booking"), ("votes", "vote"))
    if user is None or user.is_admin or all(user.can(k) for k, _ in kinds):
        return set()
    from . import shares
    with SessionLocal() as db:
        return {kind for kind, perm in kinds if not user.can(kind) and shares.has_any(db, perm, user)}


_badge_cache: dict = {}


def _task_badge(user: User | None) -> int:
    """Anzahl offener Antrags-, Buchungs- und Umlaufaufgaben für die Navigation (30 s zwischengespeichert)."""
    if user is None:
        return 0
    mods = enabled_modules()
    if not mods & {"applications", "resources", "circulations"}:
        return 0
    cache_key = (user.id, frozenset(mods))
    hit = _badge_cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < 30:
        return hit[1]
    n = 0
    with SessionLocal() as db:
        if "applications" in mods:
            from . import workflow
            n += workflow.task_count(db, user)
        if "resources" in mods:
            from . import resources as rs
            n += rs.booking_task_count(db, user)
        if "circulations" in mods:
            from . import circulations
            n += len(circulations.pending_tasks(db, user))
    if len(_badge_cache) > 2000:
        _badge_cache.clear()
    _badge_cache[cache_key] = (time.monotonic(), n)
    return n


def _dms_nav(user: User | None) -> bool:
    """Ablage in der Navigation zeigen: nur mit Zugriff auf mindestens einen Bereich."""
    if user is None or "dms" not in enabled_modules():
        return False
    from .db import DmsAccess, GroupMember
    with SessionLocal() as db:
        groups = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
        return db.scalar(select(DmsAccess.id).where((DmsAccess.user_id == user.id) | DmsAccess.group_id.in_(groups)).limit(1)) is not None


def _res_nav(user: User | None) -> bool:
    """Ressourcen in der Navigation: mit Recht, Freigabe oder Zuständigkeit für eine Ressource."""
    if user is None or "resources" not in enabled_modules():
        return False
    if user.can("resources"):
        return True
    from . import resources
    with SessionLocal() as db:
        return bool(resources.visible(db, user))


def _krank_nav(user: User | None) -> dict:
    """Krankmelder in der Navigation: melden (alle Angemeldeten), bearbeiten (Recht + Zuständigkeit) mit Zähler."""
    if user is None or "krank" not in enabled_modules():
        return {}
    from . import krank
    with SessionLocal() as db:
        staff = krank.uses_module(db, user)
        return {"staff": staff, "manager": krank.manager(user), "badge": krank.open_count(db, user) if staff else 0}


def _update_hint(user: User | None) -> str:
    """Neuere Portal-Version für Admins (sonst leer)."""
    if user is None or not user.is_admin:
        return ""
    from . import updates
    with SessionLocal() as db:
        return updates.available(get_settings(db))


def nav_ctx(request: Request, user: User, navctx: dict | None = None):
    from . import nav
    n = navctx or {"shared_nav": _shared_nav(user), "task_badge": _task_badge(user), "dms_nav": _dms_nav(user),
                   "res_nav": _res_nav(user), "krank_nav": _krank_nav(user)}
    return nav.Ctx(user=user, path=request.url.path, modules=enabled_modules(), shared=n["shared_nav"],
                   task_badge=n["task_badge"], dms_nav=n["dms_nav"], res_nav=n["res_nav"], krank_nav=n["krank_nav"])


def _nav_menu(request: Request, user: User | None, navctx: dict) -> dict:
    """Hauptmenü (Gruppen, Favoriten) für angemeldete Personen – siehe nav.py."""
    if user is None:
        return {}
    from . import nav
    return nav.build(nav_ctx(request, user, navctx))


def _public_nav(user: User | None) -> list[dict]:
    """Einträge der öffentlichen Kopfzeile – nur ohne Anmeldung (angemeldet gibt es das Seitenmenü)."""
    if user is not None:
        return []
    from . import public_nav
    return public_nav.items(enabled_modules())


def _pnav_active(item: dict, path: str) -> bool:
    from . import public_nav
    return public_nav.active(item, path)


def render(request: Request, name: str, user: User | None = None, **ctx) -> HTMLResponse:
    messages = request.session.pop("flash", [])
    ui = branding.load()
    navctx = {"shared_nav": _shared_nav(user), "task_badge": _task_badge(user), "dms_nav": _dms_nav(user),
              "res_nav": _res_nav(user), "krank_nav": _krank_nav(user)}
    return templates.TemplateResponse(request, name, {
        "user": user,
        "ui": ui, "brand": ui["name"], "product": ui["product"],
        "csrf": csrf_token(request.session),
        "messages": messages,
        "status_labels": STATUS_LABELS,
        "pipeline": PIPELINE,
        "active_statuses": ACTIVE_STATUSES,
        "meet_base_url": settings.meet_base_url,
        "modules": enabled_modules(),
        **navctx,
        "update_hint": _update_hint(user),
        "pnav": _public_nav(user),
        "nav_menu": _nav_menu(request, user, navctx),
        "pnav_active": _pnav_active,
        **ctx,
    })


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def safe_next(url: str | None) -> str:
    """Nur Pfade dieses Servers – kein „//host“, kein „/\\host“ (Browser machen daraus „//host“), keine Steuerzeichen."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return "/"
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        return "/"
    return url


def own_meeting(db: Session, meeting_id: int, user: User) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or (meeting.owner_id != user.id and not user.is_admin):
        raise HTTPException(404, "Meeting nicht gefunden.")
    return meeting


def own_recording(db: Session, rec_id: int, user: User) -> Recording:
    rec = db.get(Recording, rec_id)
    if rec is None:
        raise HTTPException(404, "Aufnahme nicht gefunden.")
    if not user.is_admin and (rec.meeting is None or rec.meeting.owner_id != user.id):
        raise HTTPException(404, "Aufnahme nicht gefunden.")
    return rec


def unique_room(db: Session, base: str) -> str:
    """Raumname für einen Portal-Raum. Der Zufallsanhang verhindert, dass jemand ohne Anmeldung
    den Namen vorher besetzt (anonyme Räume kann jede:r unter beliebigem Namen eröffnen)."""
    while True:
        room = f"{base[:52]}-{secrets.token_hex(3)}"
        if db.scalar(select(Meeting).where(Meeting.room == room)) is None:
            return room


def join_url(user: User, room: str, recording: bool = True, moderator: bool = True) -> str:
    return f"{settings.meet_base_url}/{room}?{urlencode({'jwt': jitsi_token(user, room, recording, moderator)})}"


def hosts(user: User, meeting: Meeting | None) -> bool:
    """Moderiert die Person die Konferenz? Freie Räume: wer sie eröffnet; Portal-Räume: Gastgeber:in und Admins."""
    return meeting is None or user.is_admin or meeting.owner_id == user.id


def guest_join_url(name: str, room: str, uid: str, email: str = "") -> str:
    return f"{settings.meet_base_url}/{room}?{urlencode({'jwt': guest_token(name, room, uid, email)})}"


def ensure_guest_token(meeting: Meeting) -> str:
    if not meeting.guest_token:
        meeting.guest_token = new_link_token()
    return meeting.guest_token


def speechmind_ready(db: Session, user: User | None = None) -> bool:
    cfg = get_settings(db)
    if decrypt(cfg.get("sm_api_key_enc")) and cfg.get("sm_project_slug"):
        return True
    return bool(user and cfg.get("allow_user_keys") == "1" and decrypt(user.sm_api_key_enc))


# --- Login --------------------------------------------------------------------

@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/login")
def login_form(request: Request, next: str = "/", db: Session = Depends(get_db)):
    return render(request, "login.html", next=safe_next(next), anonymous=anonymous_allowed(db))


@app.post("/login", dependencies=[Depends(check_csrf)])
def login(request: Request, email: str = Form(...), password: str = Form(...),
          next: str = Form("/"), db: Session = Depends(get_db)):
    rate_limit(request, "login")
    rate_limit(request, "login-account", limit=20, window=1800, key=email.strip().lower()[:255])
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    # Auch für unbekannte Adressen einen Hash prüfen – sonst verrät die Antwortzeit, welche Konten existieren
    valid = verify_password(user.password_hash if user else _DUMMY_HASH, password)
    if user is None or not user.active or not valid:
        flash(request, "E-Mail oder Passwort ist falsch.", "error")
        return redirect(f"/login?next={quote(safe_next(next))}")
    return start_session(request, db, user, safe_next(next))


def start_session(request: Request, db: Session, user: User, target: str) -> RedirectResponse:
    """Nach geprüftem Passwort: anmelden oder zuerst den zweiten Faktor verlangen."""
    cfg = get_settings(db)
    request.session.clear()
    if target == "/":
        target = home_for(user)
    found = twofa.methods(user, cfg)
    if found:
        request.session.update({"mfa_uid": user.id, "mfa_next": target, "mfa_at": time.time(), "mfa_tries": 0})
        if found == ["email"]:
            twofa.send_email_code(db, user)
            db.commit()
            worker.wake()
            request.session["mfa_sent"] = True
        return redirect("/login/2fa")
    sessions.establish(request, db, user)
    if twofa.needs_setup(user, cfg):
        request.session["mfa_setup"] = True
    return redirect(target)


def _pending_mfa(request: Request, db: Session) -> User | None:
    uid = request.session.get("mfa_uid")
    if not uid or time.time() - float(request.session.get("mfa_at", 0)) > 600:
        return None
    user = db.get(User, uid)
    return user if user and user.active else None


@app.get("/login/2fa")
def login_2fa_form(request: Request, db: Session = Depends(get_db)):
    user = _pending_mfa(request, db)
    if user is None:
        flash(request, "Die Anmeldung ist abgelaufen. Bitte erneut anmelden.", "error")
        return redirect("/login")
    found = twofa.methods(user, get_settings(db))
    return render(request, "login_2fa.html", None, methods=found, sent=request.session.get("mfa_sent", False),
                  email_hint=re.sub(r"(?<=.).(?=[^@]*@)", "•", user.email), has_recovery=twofa.recovery_left(user) > 0)


@app.post("/login/2fa/send", dependencies=[Depends(check_csrf)])
def login_2fa_send(request: Request, db: Session = Depends(get_db)):
    rate_limit(request, "mfa-mail", limit=4)
    user = _pending_mfa(request, db)
    if user is None or "email" not in twofa.methods(user, get_settings(db)):
        return redirect("/login")
    twofa.send_email_code(db, user)
    db.commit()
    worker.wake()
    request.session["mfa_sent"] = True
    flash(request, "Ein neuer Code ist unterwegs. Er ist 10 Minuten gültig.")
    return redirect("/login/2fa?m=email")


@app.post("/login/2fa", dependencies=[Depends(check_csrf)])
def login_2fa(request: Request, code: str = Form(""), method: str = Form("totp"), db: Session = Depends(get_db)):
    rate_limit(request, "mfa", limit=20)
    user = _pending_mfa(request, db)
    if user is None:
        flash(request, "Die Anmeldung ist abgelaufen. Bitte erneut anmelden.", "error")
        return redirect("/login")
    # Fehlversuche je Konto auf dem Server zählen – der Zähler im Sitzungscookie ließe sich durch ein
    # früheres Cookie bzw. eine neue Anmeldung zurücksetzen.
    fails_key = f"mfa-fail:{user.id}"
    fails = [t for t in _attempts.get(fails_key, []) if time.monotonic() - t < 900]
    if len(fails) >= twofa.MAX_TRIES * 2:
        request.session.clear()
        flash(request, "Zu viele falsche Codes. Bitte warten Sie 15 Minuten und melden Sie sich dann erneut an.", "error")
        return redirect("/login")
    found = twofa.methods(user, get_settings(db))
    ok = False
    if method == "totp" and "totp" in found:
        step = twofa.check_totp(twofa.user_secret(user), code, user.totp_last_step)
        if step is not None:
            user.totp_last_step, ok = step, True
    elif method == "email" and "email" in found:
        ok = twofa.check_email_code(user, code)
    elif method == "recovery":
        ok = twofa.use_recovery_code(user, code)
    if not ok:
        tries = int(request.session.get("mfa_tries", 0)) + 1
        request.session["mfa_tries"] = tries
        _attempts[fails_key] = fails + [time.monotonic()]
        if tries >= twofa.MAX_TRIES or len(fails) + 1 >= twofa.MAX_TRIES * 2:
            user.email_code_hash = user.email_code_expires = None  # Mail-Code verfällt nach zu vielen Versuchen
        db.commit()
        if tries >= twofa.MAX_TRIES:
            request.session.clear()
            flash(request, "Zu viele falsche Codes. Bitte melden Sie sich erneut an.", "error")
            return redirect("/login")
        flash(request, "Der Code stimmt nicht oder ist abgelaufen.", "error")
        return redirect(f"/login/2fa?m={method}")
    target = request.session.get("mfa_next") or "/"
    db.commit()
    request.session.clear()
    sessions.establish(request, db, user, method="2fa")
    if method == "recovery":
        flash(request, f"Wiederherstellungscode verbraucht – noch {twofa.recovery_left(user)} übrig. "
                       "Richten Sie unter Profil › Sicherheit neue Codes oder ein neues Gerät ein.", "error")
    return redirect(safe_next(target))


# --- Einladung & Passwort zurücksetzen ----------------------------------------

def issue_link(db: Session, target: User, kind: str) -> str:
    """Erzeugt einen Einmal-Link (invite | reset) und speichert nur dessen Hash."""
    token, digest = new_token()
    ttl = settings.invite_ttl_hours if kind == "invite" else settings.reset_ttl_hours
    target.token_hash = digest
    target.token_expires_at = utcnow() + timedelta(hours=ttl)
    return f"{settings.portal_base_url}/invite/{token}"


def send_link(db: Session, target: User, kind: str) -> tuple[str, bool]:
    """Link erzeugen und per Mail einreihen. Gibt (Link, Mail eingereiht?) zurück."""
    link = issue_link(db, target, kind)
    subject, body = notify.account_link_mail(db, target, link, kind)
    queued = notify.enqueue(db, target.email, subject, body, kind)
    return link, queued


def user_by_token(db: Session, token: str) -> User | None:
    user = db.scalar(select(User).where(User.token_hash == hash_token(token)))
    if user is None or not user.active or user.token_expires_at is None or user.token_expires_at < utcnow():
        return None
    return user


@app.get("/invite/{token}")
def invite_form(request: Request, token: str, db: Session = Depends(get_db)):
    target = user_by_token(db, token)
    if target is None:
        return render(request, "invite.html", None, invalid=True, token=token, target=None)
    return render(request, "invite.html", None, invalid=False, token=token, target=target)


@app.post("/invite/{token}", dependencies=[Depends(check_csrf)])
def invite_accept(request: Request, token: str, password: str = Form(...), password2: str = Form(...),
                  db: Session = Depends(get_db)):
    rate_limit(request, "invite")
    target = user_by_token(db, token)
    if target is None:
        return redirect(f"/invite/{token}")
    if len(password) < 10:
        flash(request, "Das Passwort braucht mindestens 10 Zeichen.", "error")
        return redirect(f"/invite/{token}")
    if password != password2:
        flash(request, "Die beiden Passwörter stimmen nicht überein.", "error")
        return redirect(f"/invite/{token}")
    target.password_hash = hash_password(password)
    target.password_set, target.must_change_password = True, False
    target.token_hash = target.token_expires_at = None
    db.commit()
    sessions.end_all(db, target.id)  # neues Passwort: alle bisherigen Anmeldungen beenden
    response = start_session(request, db, target, "/")
    flash(request, "Passwort gespeichert." + ("" if "mfa_uid" in request.session else " Sie sind angemeldet."))
    return response


@app.get("/forgot")
def forgot_form(request: Request):
    return render(request, "forgot.html", None)


@app.post("/forgot", dependencies=[Depends(check_csrf)])
def forgot_send(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    rate_limit(request, "forgot", limit=5)
    target = db.scalar(select(User).where(User.email == email.strip().lower()))
    if target is not None and target.active:
        send_link(db, target, "reset")
        db.commit()
        worker.wake()
    # Gleiche Antwort in jedem Fall, damit sich Konten nicht erraten lassen
    flash(request, "Falls ein Konto zu dieser Adresse existiert, wurde eine E-Mail mit weiteren Schritten verschickt.")
    return redirect("/login")


@app.post("/logout", dependencies=[Depends(check_csrf)])
def logout(request: Request, db: Session = Depends(get_db)):
    sessions.end(request, db)
    request.session.clear()
    return redirect("/login")


def anonymous_allowed(db: Session) -> bool:
    return get_settings(db).get("allow_anonymous") == "1"


def session_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None or not user.active or not sessions.validate(request, db, user):
        return None
    return user


@app.get("/jitsi/auth")
def jitsi_auth(request: Request, room: str = "", db: Session = Depends(get_db)):
    """Ziel von TOKEN_AUTH_URL: Jitsi schickt hierher, wenn ein Raum Anmeldung verlangt
    ("Ich bin der Gastgeber"). Das betrifft Portal-Räume und, falls Räume ohne Anmeldung
    gesperrt sind, alle Räume."""
    room = clean_room(room)
    if not room:
        return redirect("/")
    meeting = db.scalar(select(Meeting).where(Meeting.room == room))
    member = session_user(request, db)
    if meeting is not None and (member is None or not member.can("video")):
        # Geschützter Portal-Raum ohne Anmeldung: erklären, wie man hineinkommt, statt nur Login
        return render(request, "guest.html", None, mode="protected", meeting=meeting,
                      login_url="/login?next=" + quote(f"/jitsi/auth?room={room}"))
    user = current_user(request, db)
    if not user.can("video"):
        raise HTTPException(403, "Für Videokonferenzen fehlt die Berechtigung.")
    # Aufnehmen nur in Portal-Räumen
    return redirect(join_url(user, room, recording=meeting is not None, moderator=hosts(user, meeting)))


def _display_hash(name: str) -> str:
    """Jitsi-URL-Parameter für den Anzeigenamen (#userInfo.displayName="...")."""
    return "#" + urlencode({"userInfo.displayName": json.dumps(name)}) if name else ""


@app.get("/open")
def open_form(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    return render(request, "open.html", user, mode="form", enabled=anonymous_allowed(db),
                  meet_host=settings.meet_base_url)


@app.post("/open", dependencies=[Depends(check_csrf)])
def open_start(request: Request, name: str = Form(""), room: str = Form(""), db: Session = Depends(get_db)):
    """Konferenz ohne Konto eröffnen – ohne Aufnahmefunktion. Führt direkt in Jitsi, ohne Token."""
    if not anonymous_allowed(db):
        raise HTTPException(403, "Konferenzen ohne Anmeldung sind derzeit nicht freigegeben.")
    rate_limit(request, "open", limit=20)
    user = session_user(request, db)
    name = " ".join(name.split())[:60] or (user.name if user else "")
    slug = room_slug(room) if room.strip() else ""
    if slug and db.scalar(select(Meeting).where(Meeting.room == slug)) is not None:
        flash(request, "Dieser Raumname gehört zu einem Portal-Raum. Bitte wählen Sie einen anderen.", "error")
        return redirect("/open")
    slug = slug or f"konferenz-{secrets.token_hex(4)}"
    return redirect(f"{settings.meet_base_url}/{slug}{_display_hash(name)}")


# --- Gastzugang zu Portal-Räumen --------------------------------------------

@app.get("/join/{token}")
def join_personal(request: Request, token: str, db: Session = Depends(get_db)):
    """Persönlicher Einwahllink aus der Einladung: gilt als angemeldet, ohne Aufnahmerecht."""
    inv = db.scalar(select(Invitee).where(Invitee.join_token == token)) if len(token) > 10 else None
    if inv is None:
        return render(request, "guest.html", session_user(request, db), mode="invalid")
    meeting = inv.meeting
    if meeting.cancelled_at:
        return render(request, "guest.html", session_user(request, db), mode="cancelled", meeting=meeting)
    user = session_user(request, db)
    if user is not None and user.email == inv.email and user.can("video"):
        return redirect(join_url(user, meeting.room, moderator=hosts(user, meeting)))
    return redirect(guest_join_url(inv.name or inv.email, meeting.room, f"guest-{inv.id}", inv.email))


def _invitee_by_token(db: Session, token: str) -> Invitee | None:
    return db.scalar(select(Invitee).where(Invitee.join_token == token)) if len(token) > 10 else None


@app.get("/rsvp/{token}")
def rsvp_page(request: Request, token: str, db: Session = Depends(get_db)):
    """Zu-/Absagen im Browser. Nur Anzeige: Link-Scanner von Mailservern rufen Links automatisch
    auf, deshalb wird die Antwort erst mit dem Knopf (POST) gespeichert."""
    inv = _invitee_by_token(db, token)
    return render(request, "rsvp.html", None, inv=inv, meeting=inv.meeting if inv else None, token=token)


@app.post("/rsvp/{token}", dependencies=[Depends(check_csrf)])
def rsvp_answer(request: Request, token: str, status: str = Form(...), comment: str = Form(""),
                db: Session = Depends(get_db)):
    from . import rsvp
    rate_limit(request, "rsvp", limit=30)
    inv = _invitee_by_token(db, token)
    if inv is None or inv.meeting.cancelled_at or status not in ("accepted", "tentative", "declined"):
        return redirect(f"/rsvp/{token}")
    inv.rsvp_status, inv.rsvp_at = status, utcnow()
    inv.rsvp_comment = " ".join(comment.split())[:300] or None
    db.flush()
    rsvp.notify_organizer(db, inv.meeting, inv)
    db.commit()
    worker.wake()
    flash(request, f"Danke, Ihre Antwort „{planning.RSVP_LABELS[status]}“ wurde gespeichert.")
    return redirect(f"/rsvp/{token}")


@app.get("/rsvp/{token}/calendar.ics")
def rsvp_calendar(token: str, db: Session = Depends(get_db)):
    inv = _invitee_by_token(db, token)
    if inv is None or inv.meeting.starts_at is None:
        raise HTTPException(404)
    planning.ensure_uid(inv.meeting)
    db.commit()
    return Response(planning.invitee_calendar(inv.meeting, inv), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{room_slug(inv.meeting.title)}.ics"'})


@app.get("/g/{token}")
def join_guest_form(request: Request, token: str, db: Session = Depends(get_db)):
    meeting = db.scalar(select(Meeting).where(Meeting.guest_token == token)) if len(token) > 10 else None
    user = session_user(request, db)
    if meeting is None:
        return render(request, "guest.html", user, mode="invalid")
    if user is not None and user.can("video"):
        return redirect(join_url(user, meeting.room, moderator=hosts(user, meeting)))
    return render(request, "guest.html", None, mode="form", meeting=meeting, token=token)


@app.post("/g/{token}", dependencies=[Depends(check_csrf)])
def join_guest(request: Request, token: str, name: str = Form(""), db: Session = Depends(get_db)):
    rate_limit(request, "guest", limit=30)
    meeting = db.scalar(select(Meeting).where(Meeting.guest_token == token)) if len(token) > 10 else None
    if meeting is None:
        return redirect(f"/g/{token}")
    name = " ".join(name.split())[:60]
    if not name:
        flash(request, "Bitte geben Sie Ihren Namen an.", "error")
        return redirect(f"/g/{token}")
    return redirect(guest_join_url(name, meeting.room, "guest-" + secrets.token_hex(4)))


# --- Dashboard & Meetings -----------------------------------------------------

@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    """Startseite: Kacheln mit Aufgaben, Anträgen, Terminen, Formularen und Ablage – je nach Rechten. Ohne
    Anmeldung die Startseite für Bürger:innen (abschaltbar unter Verwaltung › Öffentliches Menü)."""
    from . import home
    if not request.session.get("uid") and get_settings(db).get("public_home", "1") == "1":
        from .routes_public import public_home
        return public_home(request, db)
    user = current_user(request, db)
    modules = enabled_modules()
    top, cache = home.overview(db, user, modules)
    return render(request, "home.html", user, tiles=home.tiles(db, user, modules, nav_ctx(request, user), cache),
                  top=top, quick=home.quick_actions(user, modules), now=utcnow())


@app.post("/dashboard/layout", dependencies=[Depends(check_csrf)])
async def dashboard_layout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import home
    data = await request.form()
    order = [k for k in str(data.get("order", "")).split(",") if k in home.TILES]
    hidden = [k for k in str(data.get("hidden", "")).split(",") if k in home.TILES]
    target = db.get(User, user.id)
    target.dashboard_json = json.dumps({"order": order, "hidden": hidden})
    db.commit()
    return JSONResponse({"ok": True})


@app.post("/nav/pin", dependencies=[Depends(check_csrf)])
async def nav_pin(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Menüeintrag als Favorit anheften bzw. lösen (Stern im Menü)."""
    from . import nav
    data = await request.form()
    item = str(data.get("id", ""))
    target = db.get(User, user.id)
    p = nav.prefs(target)
    fav = [i for i in p["fav"] if i != item]
    if data.get("on") == "1" and item in nav.BY_ID:
        if len(fav) >= nav.MAX_FAVORITES:
            return JSONResponse({"ok": False, "fav": fav, "error": f"Höchstens {nav.MAX_FAVORITES} Favoriten."}, status_code=400)
        fav.append(item)
    target.nav_json = nav.dump(fav, p["hidden"], p["closed"])
    db.commit()
    return JSONResponse({"ok": True, "fav": nav.prefs(target)["fav"]})


@app.get("/profile/menu")
def profile_menu(request: Request, user: User = Depends(current_user)):
    from . import nav
    c = nav_ctx(request, user)
    p = nav.prefs(user)
    labels = {it.id: (it.label, it.icon) for it in nav.visible(c)}
    return render(request, "profile_menu.html", user, groups=nav.options(c), max_fav=nav.MAX_FAVORITES,
                  favorites=[{"id": i, "label": labels[i][0], "icon": labels[i][1]} for i in p["fav"] if i in labels])


@app.post("/profile/menu", dependencies=[Depends(check_csrf)])
async def profile_menu_save(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import nav
    data = await request.form()
    if data.get("reset") == "1":
        fav, hidden = [], []
    else:
        checked = set(data.getlist("fav"))
        order = [i for i in data.getlist("fav_order") if i in checked]
        fav = order + [it.id for it in nav.ITEMS if it.id in checked and it.id not in order]
        shown = set(data.getlist("show"))
        hidden = [g for g in nav.GROUPS if g not in shown]
    target = db.get(User, user.id)
    target.nav_json = nav.dump(fav, hidden, None if data.get("reset") == "1" else nav.prefs(target)["closed"])
    db.commit()
    flash(request, "Menü zurückgesetzt." if data.get("reset") == "1" else "Menü gespeichert.")
    return redirect("/profile/menu")


@app.get("/meetings")
def meetings_page(request: Request, user: User = Depends(video_user), db: Session = Depends(get_db)):
    meetings = db.scalars(
        select(Meeting).where(Meeting.owner_id == user.id).order_by(Meeting.created_at.desc())
    ).all()
    recent = db.scalars(
        select(Recording).join(Meeting).where(Meeting.owner_id == user.id)
        .order_by(Recording.created_at.desc()).limit(8)
    ).all()
    upcoming = sorted((mt for mt in meetings if planning.is_upcoming(mt)), key=lambda mt: mt.starts_at)
    return render(request, "meetings.html", user, meetings=meetings, recent=recent, upcoming=upcoming,
                  sm_ready=speechmind_ready(db, user), anonymous=anonymous_allowed(db))


@app.post("/meetings", dependencies=[Depends(check_csrf)])
def create_meeting(request: Request, title: str = Form(...),
                   user: User = Depends(video_user), db: Session = Depends(get_db)):
    title = title.strip()[:200] or "Besprechung"
    meeting = Meeting(owner_id=user.id, title=title, room=unique_room(db, room_slug(title)))
    ensure_guest_token(meeting)
    db.add(meeting)
    db.commit()
    access.sync(db)
    flash(request, f"Meeting „{title}“ angelegt.")
    return redirect(f"/meetings/{meeting.id}")


# --- Besprechungen planen ---------------------------------------------------

def _users_json(db: Session) -> list[dict]:
    """Vorschläge für die Teilnehmer-Eingabe (aktive Portal-Benutzer)."""
    return [{"value": u.email, "name": u.name}
            for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))]


def _plan_values(start: str, duration: str) -> tuple[datetime | None, int, str | None]:
    starts_at = planning.parse_local(start)
    minutes = int(duration) if duration.isdigit() and 5 <= int(duration) <= 1440 else 60
    if starts_at is None:
        return None, minutes, "Bitte Datum und Uhrzeit angeben."
    return starts_at, minutes, None


def _flash_sent(request: Request, count: int, mail_ready: bool, meeting: Meeting, what: str) -> None:
    if not mail_ready:
        flash(request, "E-Mail-Versand ist nicht eingerichtet: Es wurden keine Mails verschickt. Laden Sie den "
              "Termin als ICS-Datei herunter und versenden Sie ihn selbst, oder richten Sie unter "
              "Benachrichtigungen den Mailversand ein.", "error")
    elif count:
        flash(request, f"{what} an {count} Person(en) wird verschickt.")


@app.get("/meetings/plan")
def meeting_plan_form(request: Request, user: User = Depends(video_user), db: Session = Depends(get_db)):
    start = to_local(utcnow() + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    return render(request, "plan.html", user, durations=planning.DURATIONS, users_json=_users_json(db),
                  default_start=start.strftime("%Y-%m-%dT%H:%M"),
                  mail_ready=notify.mail_configured(get_settings(db)))


@app.post("/meetings/plan", dependencies=[Depends(check_csrf)])
def meeting_plan(request: Request, title: str = Form(...), start: str = Form(""), duration: str = Form("60"),
                 description: str = Form(""), invitees: str = Form(""), copy_me: str = Form(""),
                 user: User = Depends(video_user), db: Session = Depends(get_db)):
    title = title.strip()[:200] or "Besprechung"
    starts_at, minutes, error = _plan_values(start, duration)
    emails, bad = planning.parse_emails(invitees)
    if error or bad:
        flash(request, error or ("Ungültige E-Mail-Adresse: " + ", ".join(bad)), "error")
        return redirect("/meetings/plan")
    meeting = Meeting(owner_id=user.id, title=title, room=unique_room(db, room_slug(title)),
                      starts_at=starts_at, duration_minutes=minutes,
                      description=description.strip()[:5000] or None, ics_sequence=0)
    ensure_guest_token(meeting)
    db.add(meeting)
    db.flush()
    planning.ensure_uid(meeting)
    added = planning.add_invitees(db, meeting, emails)
    count, mail_ready = planning.send(db, meeting, added, "invite", user, copy_to_organizer=copy_me == "1")
    db.commit()
    access.sync(db)
    worker.wake()
    flash(request, f"Besprechung „{title}“ geplant.")
    _flash_sent(request, count, mail_ready, meeting, "Die Einladung")
    return redirect(f"/meetings/{meeting.id}")


@app.get("/meetings/{meeting_id}")
def meeting_detail(request: Request, meeting_id: int, user: User = Depends(video_user),
                   db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    if not meeting.guest_token:
        ensure_guest_token(meeting)
        db.commit()
    return render(request, "meeting.html", user, meeting=meeting,
                  durations=planning.DURATIONS, users_json=_users_json(db),
                  mail_ready=notify.mail_configured(get_settings(db)),
                  guest_url=f"{settings.portal_base_url}/g/{ensure_guest_token(meeting)}",
                  document_types=DOCUMENT_TYPES, languages=LANGUAGES,
                  sm_ready=speechmind_ready(db, meeting.owner))


@app.post("/meetings/{meeting_id}/settings", dependencies=[Depends(check_csrf)])
def meeting_settings(request: Request, meeting_id: int, title: str = Form(...),
                     document_type: str = Form(""),
                     language: str = Form(""), user: User = Depends(video_user),
                     db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    meeting.title = title.strip()[:200] or meeting.title
    meeting.document_type = document_type if document_type in DOCUMENT_TYPES else None
    meeting.language = language if language in LANGUAGES else None
    db.commit()
    flash(request, "Einstellungen gespeichert.")
    return redirect(f"/meetings/{meeting.id}")


@app.post("/meetings/{meeting_id}/delete", dependencies=[Depends(check_csrf)])
def meeting_delete(request: Request, meeting_id: int, send_cancel: str = Form(""), message: str = Form(""),
                   user: User = Depends(video_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    recipients = planning.cancel_recipients(meeting)
    count, mail_ready = 0, True
    if recipients and send_cancel == "1":
        meeting.ics_sequence = (meeting.ics_sequence or 0) + 1
        count, mail_ready = planning.send(db, meeting, recipients, "cancel", meeting.owner,
                                          message=message[:2000])
    for rec in meeting.recordings:
        rec.meeting_id = None
    db.delete(meeting)
    db.commit()
    access.sync(db)
    worker.wake()
    flash(request, "Meeting gelöscht. Vorhandene Aufnahmen bleiben für Admins sichtbar.")
    if recipients and send_cancel == "1":
        _flash_sent(request, count, mail_ready, meeting, "Die Absage")
    return redirect("/meetings")


@app.post("/meetings/{meeting_id}/guest-link", dependencies=[Depends(check_csrf)])
def meeting_guest_link_reset(request: Request, meeting_id: int, user: User = Depends(video_user),
                             db: Session = Depends(get_db)):
    """Neuen allgemeinen Gastlink erzeugen; der alte funktioniert danach nicht mehr."""
    meeting = own_meeting(db, meeting_id, user)
    meeting.guest_token = new_link_token()
    db.commit()
    flash(request, "Neuer Gastlink erzeugt. Der bisherige Link funktioniert nicht mehr.")
    return redirect(f"/meetings/{meeting.id}")


@app.get("/meetings/{meeting_id}/join")
def meeting_join(meeting_id: int, user: User = Depends(video_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    return redirect(join_url(user, meeting.room))


@app.post("/meetings/{meeting_id}/schedule", dependencies=[Depends(check_csrf)])
def meeting_schedule(request: Request, meeting_id: int, start: str = Form(""), duration: str = Form("60"),
                     description: str = Form(""), notify_invitees: str = Form(""),
                     user: User = Depends(video_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    starts_at, minutes, error = _plan_values(start, duration)
    if error:
        flash(request, error, "error")
        return redirect(f"/meetings/{meeting.id}")
    first_time = meeting.starts_at is None
    meeting.starts_at, meeting.duration_minutes = starts_at, minutes
    meeting.description = description.strip()[:5000] or None
    meeting.cancelled_at = None
    planning.ensure_uid(meeting)
    if not first_time:
        meeting.ics_sequence = (meeting.ics_sequence or 0) + 1
    count, mail_ready = 0, True
    if meeting.invitees and notify_invitees == "1":
        count, mail_ready = planning.send(db, meeting, list(meeting.invitees),
                                          "invite" if first_time else "update", meeting.owner)
    db.commit()
    worker.wake()
    flash(request, "Termin gespeichert.")
    _flash_sent(request, count, mail_ready, meeting, "Die Änderung")
    return redirect(f"/meetings/{meeting.id}")


@app.post("/meetings/{meeting_id}/invitees", dependencies=[Depends(check_csrf)])
def meeting_add_invitees(request: Request, meeting_id: int, invitees: str = Form(""),
                         user: User = Depends(video_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    emails, bad = planning.parse_emails(invitees)
    if bad or not emails:
        flash(request, ("Ungültige E-Mail-Adresse: " + ", ".join(bad)) if bad else "Bitte E-Mail-Adressen angeben.", "error")
        return redirect(f"/meetings/{meeting.id}")
    added = planning.add_invitees(db, meeting, emails)
    count, mail_ready = (0, True)
    if planning.is_upcoming(meeting):
        count, mail_ready = planning.send(db, meeting, added, "invite", meeting.owner)
    db.commit()
    worker.wake()
    flash(request, f"{len(added)} Person(en) hinzugefügt.")
    _flash_sent(request, count, mail_ready, meeting, "Die Einladung")
    return redirect(f"/meetings/{meeting.id}")


@app.post("/meetings/{meeting_id}/invitees/{invitee_id}/delete", dependencies=[Depends(check_csrf)])
def meeting_remove_invitee(request: Request, meeting_id: int, invitee_id: int,
                           user: User = Depends(video_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    inv = db.get(Invitee, invitee_id)
    if inv is None or inv.meeting_id != meeting.id:
        raise HTTPException(404)
    if planning.is_upcoming(meeting) and inv.invited_at:
        planning.send(db, meeting, [inv], "cancel", meeting.owner)
    db.delete(inv)
    db.commit()
    worker.wake()
    flash(request, f"{inv.email} ausgeladen" + (" (Absage wird verschickt)." if inv.invited_at else "."))
    return redirect(f"/meetings/{meeting.id}")


@app.post("/meetings/{meeting_id}/resend", dependencies=[Depends(check_csrf)])
def meeting_resend(request: Request, meeting_id: int, user: User = Depends(video_user),
                   db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    count, mail_ready = planning.send(db, meeting, list(meeting.invitees), "invite", meeting.owner)
    db.commit()
    worker.wake()
    _flash_sent(request, count, mail_ready, meeting, "Die Einladung")
    return redirect(f"/meetings/{meeting.id}")


@app.post("/meetings/{meeting_id}/cancel", dependencies=[Depends(check_csrf)])
def meeting_cancel(request: Request, meeting_id: int, message: str = Form(""),
                   user: User = Depends(video_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    if meeting.starts_at is None or meeting.cancelled_at:
        return redirect(f"/meetings/{meeting.id}")
    meeting.ics_sequence = (meeting.ics_sequence or 0) + 1
    count, mail_ready = planning.send(db, meeting, list(meeting.invitees), "cancel", meeting.owner,
                                      message=message[:2000])
    meeting.cancelled_at = utcnow()
    db.commit()
    worker.wake()
    flash(request, "Besprechung abgesagt. Der Raum bleibt bestehen.")
    _flash_sent(request, count, mail_ready, meeting, "Die Absage")
    return redirect(f"/meetings/{meeting.id}")


@app.get("/meetings/{meeting_id}/calendar.ics")
def meeting_calendar(meeting_id: int, user: User = Depends(video_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    if meeting.starts_at is None:
        raise HTTPException(404, "Für dieses Meeting ist kein Termin geplant.")
    planning.ensure_uid(meeting)
    db.commit()
    return Response(planning.calendar_file(meeting), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{room_slug(meeting.title)}.ics"'})


# --- Admin: E-Mail-Vorlagen ----------------------------------------------------

@app.get("/admin/templates")
def admin_templates(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    items = []
    for key, t in mailtpl.TEMPLATES.items():
        subject, body = mailtpl.current(cfg, key)
        items.append({"key": key, **t, "cur_subject": subject, "cur_body": body,
                      "custom": bool(cfg.get(f"tpl_{key}_subject") or cfg.get(f"tpl_{key}_body"))})
    sample = {**mailtpl.common_vars(), **mailtpl.SAMPLE}
    return render(request, "admin_templates.html", user, items=items, common_vars=mailtpl.COMMON_VARS,
                  sample=sample, open_key=request.query_params.get("t", ""))


@app.post("/admin/templates/{key}", dependencies=[Depends(check_csrf)])
async def admin_templates_save(request: Request, key: str, subject: str = Form(""), body: str = Form(""),
                               action: str = Form("save"), user: User = Depends(admin_user),
                               db: Session = Depends(get_db)):
    if key not in mailtpl.TEMPLATES:
        raise HTTPException(404)
    t = mailtpl.TEMPLATES[key]
    if action == "reset":
        set_setting(db, f"tpl_{key}_subject", "")
        set_setting(db, f"tpl_{key}_body", "")
        db.commit()
        flash(request, f"Vorlage „{t['label']}“ auf den Standardtext zurückgesetzt.")
        return redirect(f"/admin/templates?t={key}#{key}")
    subject, body = subject.strip()[:300], body.replace("\r\n", "\n").strip()[:20000]
    if not subject or not body:
        flash(request, "Betreff und Text dürfen nicht leer sein.", "error")
        return redirect(f"/admin/templates?t={key}#{key}")
    # Standardtext nicht als eigene Fassung speichern (sonst greifen spätere Verbesserungen nicht)
    set_setting(db, f"tpl_{key}_subject", "" if subject == t["subject"] else subject)
    set_setting(db, f"tpl_{key}_body", "" if body == t["body"] else body)
    db.commit()
    if action == "test":
        cfg = get_settings(db)
        s, b = mailtpl.render(db, key, mailtpl.SAMPLE, cfg)
        try:
            await asyncio.to_thread(notify.deliver, cfg, user.email, "[Test] " + s, b)
        except notify.MailError as exc:
            flash(request, f"Gespeichert, aber die Testmail ging nicht raus: {exc}", "error")
        else:
            flash(request, f"Gespeichert. Testmail mit Beispieldaten an {user.email} verschickt.")
    else:
        flash(request, f"Vorlage „{t['label']}“ gespeichert.")
    return redirect(f"/admin/templates?t={key}#{key}")


# --- Aufnahmen & Transkripte --------------------------------------------------

@app.get("/recordings/{rec_id}")
def recording_detail(request: Request, rec_id: int, user: User = Depends(video_user),
                     db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    transcript = json.loads(rec.transcript_json) if rec.transcript_json else []
    summary = json.loads(rec.summary_json) if rec.summary_json else {}
    has_video = bool(rec.video_path and Path(rec.video_path).exists())
    return render(request, "recording.html", user, rec=rec, transcript=transcript, delete_modes=DELETE_MODES,
                  summary=summary, has_video=has_video, has_audio=rec.audio_size is not None,
                  participants=json.loads(rec.participants or "[]"))


@app.post("/recordings/{rec_id}/transcribe", dependencies=[Depends(check_csrf)])
def recording_transcribe(request: Request, rec_id: int, user: User = Depends(video_user),
                         db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    if rec.status in ACTIVE_STATUSES:
        flash(request, "Die Aufnahme wird bereits verarbeitet.")
    elif rec.status == STATUS_FAILED and rec.sm_protocol_slug:
        # Upload hat geklappt, nur das Abholen ist gescheitert -> erneut abfragen
        rec.status, rec.error = "processing", None
        db.commit()
        worker.wake()
        flash(request, "Das Ergebnis wird erneut bei SpeechMind abgefragt.")
    else:
        rec.status, rec.error = STATUS_QUEUED, None
        rec.sm_protocol_slug = None
        db.commit()
        worker.wake()
        flash(request, "Die Aufnahme wird an SpeechMind übergeben.")
    return redirect(f"/recordings/{rec.id}")


@app.post("/recordings/{rec_id}/reconvert", dependencies=[Depends(check_csrf)])
def recording_reconvert(request: Request, rec_id: int, user: User = Depends(video_user),
                        db: Session = Depends(get_db)):
    """MP3 aus dem Video neu erzeugen und den Ton neu messen."""
    rec = own_recording(db, rec_id, user)
    if rec.status in ACTIVE_STATUSES:
        flash(request, "Die Aufnahme wird gerade verarbeitet.", "error")
    elif not (rec.video_path and Path(rec.video_path).exists()):
        flash(request, "Das Video ist nicht mehr vorhanden, die MP3 kann nicht neu erzeugt werden.", "error")
    else:
        rec.status, rec.error, rec.audio_max_db = "new", None, None
        db.commit()
        worker.wake()
        flash(request, "Die MP3 wird neu erzeugt.")
    return redirect(f"/recordings/{rec.id}")


@app.get("/recordings/{rec_id}/audio.mp3")
def recording_audio(rec_id: int, user: User = Depends(video_user), db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    path = Path(rec.audio_path) if rec.audio_path else None
    if not path or not path.exists():
        raise HTTPException(404, "Die MP3-Datei ist (noch) nicht vorhanden.")
    title = rec.meeting.title if rec.meeting else rec.room
    return FileResponse(path, media_type="audio/mpeg",
                        filename=f"aufnahme-{room_slug(title)}-{to_local(rec.created_at):%Y%m%d-%H%M}.mp3")


@app.get("/recordings/{rec_id}/video")
def recording_video(rec_id: int, user: User = Depends(video_user), db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    path = Path(rec.video_path) if rec.video_path else None
    root = settings.recordings_dir.resolve()
    if not path or not path.exists() or root not in path.resolve().parents:
        raise HTTPException(404, "Die Videodatei ist nicht mehr vorhanden.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/recordings/{rec_id}/chat.txt", response_class=PlainTextResponse)
def recording_chat_txt(rec_id: int, user: User = Depends(video_user), db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    if not rec.chat and not rec.polls:
        raise HTTPException(404, "Zu dieser Aufnahme gibt es kein Chatprotokoll.")
    title = rec.meeting.title if rec.meeting else rec.room
    filename = f"chatprotokoll-{room_slug(title)}-{to_local(rec.created_at):%Y%m%d-%H%M}.txt"
    head = f"Chatprotokoll: {title}, Aufnahme vom {to_local(rec.created_at):%d.%m.%Y %H:%M} Uhr\n\n"
    body = chat.as_text(rec.chat, to_local) if rec.chat else ""
    if rec.polls:
        body += ("\n" if body else "") + "UMFRAGEN\n\n" + chat.polls_as_text(rec.polls, to_local)
    return PlainTextResponse(head + body,
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/recordings/{rec_id}/transcript.txt", response_class=PlainTextResponse)
def recording_transcript_txt(rec_id: int, user: User = Depends(video_user),
                             db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    if rec.status != STATUS_DONE or not rec.transcript_json:
        raise HTTPException(404, "Noch kein Transkript vorhanden.")
    lines = []
    for seg in json.loads(rec.transcript_json):
        stamp = ""
        if seg.get("start") is not None:
            s = int(float(seg["start"]))
            stamp = f"[{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}] "
        lines.append(f"{stamp}{seg['speaker']}: {seg['text']}")
    title = rec.meeting.title if rec.meeting else rec.room
    filename = f"transkript-{room_slug(title)}-{to_local(rec.created_at):%Y%m%d-%H%M}.txt"
    return PlainTextResponse("\n\n".join(lines) + "\n",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


DELETE_MODES = {
    "media": "Nur Video und MP3 löschen, Transkript und Chatprotokoll behalten",
    "keep_link": "Alles hier löschen, Protokoll bei SpeechMind später wieder abrufbar",
    "all": "Alles löschen",
}


def _remove_media(rec: Recording) -> None:
    session_dir = Path(rec.session_dir)
    root = settings.recordings_dir.resolve()
    if session_dir.exists() and root in session_dir.resolve().parents:
        shutil.rmtree(session_dir, ignore_errors=True)
    if rec.audio_path:
        Path(rec.audio_path).unlink(missing_ok=True)
    rec.video_path = rec.audio_path = None
    rec.media_deleted_at = utcnow()


def delete_recording(db: Session, rec: Recording, mode: str) -> str:
    """Löscht je nach Modus Teile einer Aufnahme. Gibt 'removed', 'media', 'remote' oder 'busy' zurück.

    Bleibt nichts Sinnvolles übrig (kein Transkript, kein SpeechMind-Verweis), wird der Eintrag ganz entfernt.
    """
    if rec.status in ACTIVE_STATUSES:
        return "busy"
    _remove_media(rec)
    if mode == "media" and (rec.transcript_json or rec.sm_protocol_slug or rec.chat_json or rec.polls_json):
        if rec.status != STATUS_DONE:
            rec.error = None
        return "media"
    if mode == "keep_link" and rec.sm_protocol_slug:
        rec.transcript_json = rec.summary_json = rec.chat_json = rec.polls_json = None
        rec.status, rec.error = STATUS_REMOTE, None
        return "remote"
    db.delete(rec)
    return "removed"


DELETE_MESSAGES = {
    "removed": "Aufnahme vollständig gelöscht (ein Protokoll in SpeechMind bleibt dort bestehen).",
    "media": "Video und MP3 gelöscht, Transkript und Chatprotokoll bleiben erhalten.",
    "remote": "Aufnahme hier gelöscht. Das Protokoll kann jederzeit wieder von SpeechMind abgerufen werden.",
    "busy": "Die Aufnahme wird gerade verarbeitet und kann erst danach gelöscht werden.",
}


@app.post("/recordings/{rec_id}/delete", dependencies=[Depends(check_csrf)])
def recording_delete(request: Request, rec_id: int, mode: str = Form("all"),
                     user: User = Depends(video_user), db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    back = f"/meetings/{rec.meeting_id}" if rec.meeting_id else "/admin/recordings"
    result = delete_recording(db, rec, mode if mode in DELETE_MODES else "all")
    db.commit()
    flash(request, DELETE_MESSAGES[result], "error" if result == "busy" else "ok")
    return redirect(f"/recordings/{rec_id}" if result in ("media", "remote", "busy") else back)


@app.post("/recordings/bulk-delete", dependencies=[Depends(check_csrf)])
async def recordings_bulk_delete(request: Request, user: User = Depends(video_user),
                                 db: Session = Depends(get_db)):
    form = await request.form()
    mode = form.get("mode") if form.get("mode") in DELETE_MODES else "all"
    ids = {int(i) for i in form.getlist("ids") if str(i).isdigit()}
    counts: dict[str, int] = {}
    for rec_id in ids:
        try:
            rec = own_recording(db, rec_id, user)
        except HTTPException:
            continue
        result = delete_recording(db, rec, mode)
        counts[result] = counts.get(result, 0) + 1
    db.commit()
    if not ids:
        flash(request, "Keine Aufnahmen ausgewählt.", "error")
    else:
        parts = {"removed": "vollständig gelöscht", "media": "Medien gelöscht, Transkript behalten",
                 "remote": "hier gelöscht, bei SpeechMind abrufbar", "busy": "übersprungen (in Verarbeitung)"}
        flash(request, "; ".join(f"{n} {parts[k]}" for k, n in counts.items()) + ".",
              "error" if counts.get("busy") and len(counts) == 1 else "ok")
    return redirect(safe_next(form.get("next")) if form.get("next") else "/admin/recordings")


@app.post("/recordings/{rec_id}/fetch", dependencies=[Depends(check_csrf)])
def recording_fetch(request: Request, rec_id: int, user: User = Depends(video_user),
                    db: Session = Depends(get_db)):
    """Protokoll und Wortlaut erneut bei SpeechMind abholen."""
    rec = own_recording(db, rec_id, user)
    if not rec.sm_protocol_slug:
        flash(request, "Für diese Aufnahme gibt es kein Protokoll bei SpeechMind.", "error")
    elif rec.status in ACTIVE_STATUSES:
        flash(request, "Die Aufnahme wird gerade verarbeitet.")
    else:
        rec.status, rec.error, rec.sm_submitted_at = STATUS_PROCESSING, None, utcnow()
        db.commit()
        worker.wake()
        flash(request, "Das Protokoll wird bei SpeechMind abgerufen. Das dauert meist nur wenige Sekunden.")
    return redirect(f"/recordings/{rec.id}")


# --- Profil -------------------------------------------------------------------

def _profile_page(request, user, db, details=None, profile_error=""):
    from . import profiles
    cfg = get_settings(db)
    return render(request, "profile.html", user,
                  allow_user_keys=cfg.get("allow_user_keys") == "1",
                  own_key_mask=mask_secret(decrypt(user.sm_api_key_enc)),
                  profile_groups=profiles.GROUPS,
                  details=profiles.read(user) if details is None else details,
                  profile_error=profile_error)


@app.get("/profile")
def profile(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _profile_page(request, user, db)


@app.post("/profile/details", dependencies=[Depends(check_csrf)])
async def profile_details(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import profiles
    raw = dict(await request.form())
    try:
        encrypted = profiles.store(raw)
    except ValueError as exc:
        # Only known, voluntary inputs are redisplayed. Never echo credentials or tokens.
        details = {k: str(raw.get(k) or '')[:field[3]] for k, field in profiles.FIELDS.items()}
        details['prefill_enabled'] = raw.get('prefill_enabled') == '1'
        response = _profile_page(request, user, db, details, str(exc))
        response.status_code = 422
        return response
    db.get(User, user.id).profile_data_enc = encrypted
    db.commit()
    flash(request, "Freiwillige Profilangaben gespeichert.")
    return redirect("/profile#details")


@app.post("/profile/details/clear", dependencies=[Depends(check_csrf)])
def profile_details_clear(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.get(User, user.id).profile_data_enc = None
    db.commit()
    flash(request, "Freiwillige Profilangaben gelöscht. Bereits eingereichte Formulare bleiben erhalten.")
    return redirect("/profile#details")


@app.get("/profile/details/export")
def profile_details_export(user: User = Depends(current_user)):
    from .profiles import read
    from fastapi.responses import Response
    return Response(json.dumps(read(user), ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="mein-profil.json"', "Cache-Control": "no-store"})


@app.post("/profile", dependencies=[Depends(check_csrf)])
def profile_save(request: Request, name: str = Form(...), current_password: str = Form(""),
                 new_password: str = Form(""), sm_api_key: str = Form(""),
                 sm_project_slug: str = Form(""), sm_remove_key: str = Form(""), sub_confirm: str = Form(""),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, user.id)
    user.name = name.strip()[:200] or user.name
    user.sub_confirm = sub_confirm == "1"
    if new_password:
        if len(new_password) < 10:
            flash(request, "Das neue Passwort braucht mindestens 10 Zeichen.", "error")
            return redirect("/profile")
        if not verify_password(user.password_hash, current_password):
            flash(request, "Das aktuelle Passwort stimmt nicht.", "error")
            return redirect("/profile")
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        if sessions.end_all(db, user.id, keep_hash=sessions.current_hash(request)):
            flash(request, "Ihre Anmeldungen auf anderen Geräten wurden beendet.")
    elif user.must_change_password:
        flash(request, "Bitte vergeben Sie ein neues Passwort.", "error")
        return redirect("/profile")
    if get_settings(db).get("allow_user_keys") == "1":
        if sm_remove_key == "1":
            user.sm_api_key_enc, user.sm_project_slug = None, None
        else:
            if sm_api_key.strip():
                user.sm_api_key_enc = encrypt(sm_api_key.strip())
            user.sm_project_slug = sm_project_slug.strip() or None
    db.commit()
    flash(request, "Profil gespeichert.")
    return redirect("/profile")


# --- Über dieses Portal -----------------------------------------------------------

@app.get("/about")
def about_page(request: Request, db: Session = Depends(get_db)):
    from . import about, updates
    cfg = get_settings(db)
    return render(request, "about.html", session_user(request, db), publisher=about.PUBLISHER, license=about.LICENSE,
                  components=about.COMPONENTS, services=about.SERVICES, version=updates.current(),
                  latest=cfg.get("update_latest", ""), update_new=updates.available(cfg), cfg=cfg)


@app.post("/about/updates", dependencies=[Depends(check_csrf)])
async def about_updates(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from . import updates
    form = await request.form()
    if form.get("action") == "toggle":
        set_setting(db, "update_check", "1" if form.get("on") == "1" else "0")
        db.commit()
        flash(request, "Update-Hinweis " + ("eingeschaltet." if form.get("on") == "1" else "ausgeschaltet – es wird nicht mehr nachgefragt."))
    else:
        latest = await asyncio.to_thread(updates.check, True)
        flash(request, f"Aktuelle Version: {latest}." if latest else "Prüfung nicht möglich (abgeschaltet oder keine Verbindung).",
              "ok" if latest else "error")
    return redirect("/about#version")


# --- Profil: Sicherheit (Zwei-Faktor-Anmeldung) ---------------------------------

@app.get("/profile/security")
def profile_security(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    setup = None
    if request.query_params.get("setup") == "totp" or (twofa.needs_setup(user, cfg) and not user.totp_enabled):
        secret = stash_get(request, "totp_setup") or twofa.new_secret()
        stash_put(request, "totp_setup", secret)
        uri = twofa.provisioning_uri(secret, user)
        setup = {"secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), "qr": twofa.qr_svg(uri)}
    return render(request, "profile_security.html", user, allowed=twofa.allowed(cfg), required=twofa.required(user, cfg),
                  methods=twofa.methods(user, cfg), setup=setup, recovery_left=twofa.recovery_left(user),
                  new_codes=stash_get(request, "recovery_codes", pop=True), mail_ready=notify.mail_configured(cfg),
                  my_sessions=sessions.rows(request, sessions.for_user(db, user.id)))


def _confirm_password(request: Request, user: User, password: str) -> bool:
    if verify_password(user.password_hash, password):
        return True
    flash(request, "Das Passwort stimmt nicht.", "error")
    return False


@app.post("/profile/security/totp", dependencies=[Depends(check_csrf)])
def profile_totp(request: Request, action: str = Form(...), code: str = Form(""), password: str = Form(""),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, user.id)
    cfg = get_settings(db)
    if action == "enable":
        if user.totp_enabled and not _confirm_password(request, user, password):
            return redirect("/profile/security?setup=totp")  # Gerät ersetzen nur mit Passwort
        secret = stash_get(request, "totp_setup")
        step = twofa.check_totp(secret, code) if secret and twofa.allowed(cfg)["totp"] else None
        if step is None:
            flash(request, "Der Code stimmt nicht. Prüfen Sie die Uhrzeit des Telefons und geben Sie den aktuellen "
                           "Code ein.", "error")
            return redirect("/profile/security?setup=totp")
        twofa.enable_totp(user, secret)
        user.totp_last_step = step
        stash_get(request, "totp_setup", pop=True)
        request.session.pop("mfa_setup", None)
        if not twofa.recovery_left(user):
            stash_put(request, "recovery_codes", twofa.new_recovery_codes(user))
        flash(request, "Authenticator-App eingerichtet. Ab der nächsten Anmeldung wird ein Code abgefragt.")
    elif action == "disable" and _confirm_password(request, user, password):
        if twofa.required(user, cfg) and not (twofa.allowed(cfg)["email"]):
            flash(request, "Die App kann nicht entfernt werden: Zwei-Faktor ist Pflicht und Codes per E-Mail sind "
                           "nicht erlaubt. Richten Sie stattdessen ein neues Gerät ein.", "error")
            return redirect("/profile/security")
        user.totp_enabled, user.totp_secret_enc, user.totp_last_step = False, None, None
        flash(request, "Authenticator-App entfernt.")
    db.commit()
    return redirect("/profile/security")


@app.post("/profile/security/email", dependencies=[Depends(check_csrf)])
def profile_mfa_email(request: Request, enable: str = Form(""), password: str = Form(""),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, user.id)
    if not _confirm_password(request, user, password):
        return redirect("/profile/security")
    if enable == "1" and not twofa.allowed(get_settings(db))["email"]:
        raise HTTPException(403)
    user.mfa_email = enable == "1"
    if user.mfa_email and not twofa.recovery_left(user):
        stash_put(request, "recovery_codes", twofa.new_recovery_codes(user))
    db.commit()
    flash(request, "Code per E-Mail eingeschaltet." if user.mfa_email else "Code per E-Mail ausgeschaltet.")
    return redirect("/profile/security")


@app.post("/profile/security/recovery", dependencies=[Depends(check_csrf)])
def profile_recovery(request: Request, password: str = Form(""), user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    user = db.get(User, user.id)
    if _confirm_password(request, user, password):
        stash_put(request, "recovery_codes", twofa.new_recovery_codes(user))
        db.commit()
        flash(request, "Neue Wiederherstellungscodes erzeugt. Die alten gelten nicht mehr.")
    return redirect("/profile/security#wiederherstellung")


@app.post("/admin/security", dependencies=[Depends(check_csrf)])
def admin_security(request: Request, mfa_email_allowed: str = Form(""), mfa_totp_allowed: str = Form(""),
                   mfa_required: str = Form("off"), user: User = Depends(admin_user), db: Session = Depends(get_db)):
    if mfa_required != "off" and mfa_email_allowed != "1" and mfa_totp_allowed != "1":
        flash(request, "Für eine Pflicht muss mindestens ein Verfahren erlaubt sein.", "error")
        return redirect("/admin/users#sicherheit")
    set_setting(db, "mfa_email_allowed", "1" if mfa_email_allowed == "1" else "0")
    set_setting(db, "mfa_totp_allowed", "1" if mfa_totp_allowed == "1" else "0")
    set_setting(db, "mfa_required", mfa_required if mfa_required in twofa.REQUIRED else "off")
    db.commit()
    flash(request, "Anmelde-Einstellungen gespeichert. Sie gelten ab der nächsten Anmeldung.")
    return redirect("/admin/users#sicherheit")


# --- Admin: SpeechMind --------------------------------------------------------

@app.get("/admin/speechmind")
def admin_speechmind(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    return render(request, "admin_speechmind.html", user, cfg=cfg,
                  key_mask=mask_secret(decrypt(cfg.get("sm_api_key_enc"))),
                  projects=request.session.pop("sm_projects", None),
                  document_types=DOCUMENT_TYPES, languages=LANGUAGES)


@app.post("/admin/speechmind", dependencies=[Depends(check_csrf)])
def admin_speechmind_save(
    request: Request,
    sm_api_url: str = Form(...), sm_api_key: str = Form(""), sm_project_slug: str = Form(""),
    sm_language: str = Form("de-DE"), sm_document_type: str = Form("summary"),
    allow_user_keys: str = Form(""),
    delete_after_upload: str = Form(""), send_participants: str = Form(""),
    user: User = Depends(admin_user), db: Session = Depends(get_db),
):
    if not sm_api_url.startswith("https://"):
        flash(request, "Die API-Adresse muss mit https:// beginnen.", "error")
        return redirect("/admin/speechmind")
    set_setting(db, "sm_api_url", sm_api_url.strip())
    if sm_api_key.strip():
        set_setting(db, "sm_api_key_enc", encrypt(sm_api_key.strip()))
    set_setting(db, "sm_project_slug", sm_project_slug.strip())
    set_setting(db, "sm_language", sm_language if sm_language in LANGUAGES else "de-DE")
    set_setting(db, "sm_document_type", sm_document_type if sm_document_type in DOCUMENT_TYPES else "summary")
    for key, value in (("allow_user_keys", allow_user_keys),
                       ("delete_after_upload", delete_after_upload),
                       ("send_participants", send_participants)):
        set_setting(db, key, "1" if value == "1" else "0")
    db.commit()
    flash(request, "SpeechMind-Einstellungen gespeichert.")
    return redirect("/admin/speechmind")


@app.post("/admin/speechmind/test", dependencies=[Depends(check_csrf)])
async def admin_speechmind_test(request: Request, user: User = Depends(admin_user),
                                db: Session = Depends(get_db)):
    cfg = get_settings(db)
    try:
        projects = await SpeechMindClient(cfg["sm_api_url"], decrypt(cfg.get("sm_api_key_enc"))).list_projects()
    except SpeechMindError as exc:
        flash(request, str(exc), "error")
        return redirect("/admin/speechmind")
    request.session["sm_projects"] = projects
    flash(request, f"Verbindung steht. {len(projects)} Projekt(e) gefunden – bitte eines auswählen.")
    return redirect("/admin/speechmind#projekt")


@app.post("/admin/speechmind/project", dependencies=[Depends(check_csrf)])
async def admin_speechmind_create_project(request: Request, name: str = Form(...),
                                          user: User = Depends(admin_user),
                                          db: Session = Depends(get_db)):
    cfg = get_settings(db)
    try:
        project = await SpeechMindClient(cfg["sm_api_url"], decrypt(cfg.get("sm_api_key_enc"))) \
            .create_project(name.strip()[:120] or "Jitsi")
    except SpeechMindError as exc:
        flash(request, str(exc), "error")
        return redirect("/admin/speechmind")
    if project.get("slug"):
        set_setting(db, "sm_project_slug", project["slug"])
        db.commit()
        flash(request, f"Projekt „{project.get('name')}“ angelegt und ausgewählt.")
    return redirect("/admin/speechmind")


# --- Admin: Benutzer ----------------------------------------------------------

def flash_link_result(request: Request, target: User, link: str, queued: bool) -> None:
    if queued:
        flash(request, f"E-Mail an {target.email} wird versendet.")
    else:
        # Ohne Mailversand muss der Link von Hand weitergegeben werden
        stash_put(request, "invite_links", [{"email": target.email, "link": link}])


def _perm_value(selected: list[str], actor: User | None = None, before: set[str] | None = None) -> str:
    """Rechte als Text. Ohne Admin-Rolle lassen sich nur Rechte vergeben oder entziehen, die man selbst hat;
    alle anderen bleiben, wie sie waren (keine Rechteausweitung über „Benutzer verwalten“)."""
    chosen = set(selected)
    if actor is not None and not actor.is_admin:
        own = actor.perms
        chosen = {p for p in chosen if p in own} | {p for p in (before or set()) if p not in own}
    return ",".join(p for p in PERMISSIONS if p in chosen)


def _can_manage(actor: User, target: User) -> bool:
    """Wer Benutzer verwalten darf, aber kein Admin ist, ändert keine Admin-Konten und keine Konten mit Rechten,
    die er selbst nicht hat (sonst ließe sich z. B. über einen Zurücksetzen-Link ein mächtigeres Konto übernehmen)."""
    return actor.is_admin or (not target.is_admin and (target.id == actor.id or target.perms <= actor.perms))


def _set_groups(db: Session, target: User, group_ids: list[str]) -> None:
    ids = {int(g) for g in group_ids if str(g).isdigit()}
    target.groups = list(db.scalars(select(Group).where(Group.id.in_(ids)))) if ids else []


@app.get("/admin/users")
def admin_users(request: Request, user: User = Depends(users_manager), db: Session = Depends(get_db)):
    users = db.scalars(select(User).options(joinedload(User.groups)).order_by(User.name)).unique().all()
    groups = db.scalars(select(Group).options(joinedload(Group.members)).order_by(Group.name)).unique().all()
    from . import absence
    return render(request, "admin_users.html", user, users=users, groups=groups,
                  away=absence.current_map(db), away_label=absence.label,
                  invite_links=stash_get(request, "invite_links", pop=True),
                  mail_ready=notify.mail_configured(get_settings(db)),
                  invite_ttl=settings.invite_ttl_hours,
                  allow_anonymous=anonymous_allowed(db), cfg=get_settings(db), mfa_required=twofa.REQUIRED)


@app.post("/admin/users", dependencies=[Depends(check_csrf)])
async def admin_users_create(request: Request, emails: str = Form(...), name: str = Form(""),
                             is_admin: str = Form(""), user: User = Depends(users_manager),
                             db: Session = Depends(get_db)):
    """Lädt eine oder mehrere Personen ein (Adressen durch Komma, Semikolon oder Leerzeichen getrennt)."""
    form = await request.form()
    perms = _perm_value(form.getlist("perm"), user)
    group_ids = form.getlist("groups")
    addresses = list(dict.fromkeys(a.lower() for a in re.split(r"[,;\s]+", emails) if a))
    bad = [a for a in addresses if not EMAIL_RE.match(a)]
    if not addresses or bad:
        flash(request, "Ungültige E-Mail-Adresse: " + ", ".join(bad) if bad else "Bitte mindestens eine E-Mail-Adresse angeben.", "error")
        return redirect("/admin/users")
    created, links = [], []
    for email in addresses:
        if db.scalar(select(User).where(User.email == email)):
            flash(request, f"{email} hat bereits ein Konto.", "error")
            continue
        display = name.strip()[:200] if len(addresses) == 1 and name.strip() else name_from_email(email)
        # Bis zur Annahme der Einladung ist das Passwort ein nicht erratbarer Zufallswert
        target = User(email=email, name=display, is_admin=is_admin == "1" and user.is_admin, permissions=perms,
                      password_hash=hash_password(secrets.token_urlsafe(32)), password_set=False)
        db.add(target)
        _set_groups(db, target, group_ids)
        link, queued = send_link(db, target, "invite")
        created.append(email)
        if not queued:
            links.append({"email": email, "link": link})
    db.commit()
    worker.wake()
    if links:
        stash_put(request, "invite_links", links)
    if created:
        flash(request, f"{len(created)} Einladung(en) angelegt: " + ", ".join(created))
    return redirect("/admin/users")


# --- Admin: Benutzer per CSV importieren ----------------------------------------

@app.get("/admin/users/import-template.csv")
def admin_users_import_template(user: User = Depends(users_manager)):
    from . import user_import
    return Response(user_import.template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="benutzer-import-vorlage.csv"'})


@app.post("/admin/users/import", dependencies=[Depends(check_csrf)])
async def admin_users_import_preview(request: Request, file: UploadFile = File(...),
                                     user: User = Depends(users_manager), db: Session = Depends(get_db)):
    """Schritt 1: Datei prüfen und Vorschau zeigen – noch ohne Änderungen."""
    from . import user_import
    data = await file.read(5_000_001)
    if len(data) > 5_000_000:
        flash(request, "Die Datei ist größer als 5 MB.", "error")
        return redirect("/admin/users#import")
    rows, problems = user_import.parse(data, db, user)
    if not rows:
        flash(request, " ".join(problems) or "Keine Zeilen gefunden.", "error")
        return redirect("/admin/users#import")
    token = user_import.stash(rows)
    return render(request, "admin_users_import.html", user, rows=rows, problems=problems, token=token,
                  summary=user_import.summary(rows), filename=file.filename,
                  mail_ready=notify.mail_configured(get_settings(db)), invite_ttl=settings.invite_ttl_hours)


@app.post("/admin/users/import/apply", dependencies=[Depends(check_csrf)])
def admin_users_import_apply(request: Request, token: str = Form(...), invite: str = Form(""),
                             force_change: str = Form(""), user: User = Depends(users_manager),
                             db: Session = Depends(get_db)):
    """Schritt 2: Konten und Gruppen anlegen, auf Wunsch Einladungen an Konten ohne Passwort."""
    from . import user_import
    rows = user_import.unstash(token, remove=True)
    if rows is None:
        flash(request, "Der Import ist abgelaufen. Bitte die Datei erneut hochladen.", "error")
        return redirect("/admin/users#import")
    if not user.is_admin:
        for row in rows:
            row["admin"] = False
    without_password, created, added = user_import.apply(db, rows, force_change == "1")
    links, queued = [], 0
    if invite == "1":
        for target in without_password:
            link, ok = send_link(db, target, "invite")
            queued += ok
            if not ok:
                links.append({"email": target.email, "link": link})
    db.commit()
    worker.wake()
    if links:
        stash_put(request, "invite_links", links[:200])
    parts = [f"{len(created)} Konto/Konten angelegt"]
    if added:
        parts.append(f"{added} Gruppenmitgliedschaft(en) ergänzt")
    if queued:
        parts.append(f"{queued} Einladung(en) per Mail unterwegs")
    if without_password and invite != "1":
        parts.append(f"{len(without_password)} Konto/Konten ohne Passwort – Einladung später über das "
                     "Papierflieger-Symbol senden")
    flash(request, "Import abgeschlossen: " + ", ".join(parts) + ".")
    return redirect("/admin/users")


@app.post("/admin/users/{uid}", dependencies=[Depends(check_csrf)])
async def admin_users_update(request: Request, uid: int, action: str = Form(...),
                             user: User = Depends(users_manager), db: Session = Depends(get_db)):
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404)
    if not _can_manage(user, target):
        flash(request, "Konten von Administrator:innen und Konten mit Rechten, die Sie selbst nicht haben, kann "
                       "nur ein Admin ändern.", "error")
        return redirect("/admin/users")
    if target.id == user.id and action in ("toggle_admin", "toggle_active", "delete"):
        flash(request, "Das eigene Konto lässt sich hier nicht ändern.", "error")
        return redirect("/admin/users")
    if action == "toggle_admin":
        if not user.is_admin:
            raise HTTPException(403)
        target.is_admin = not target.is_admin
    elif action == "edit":
        form = await request.form()
        name = " ".join(str(form.get("name", "")).split())[:200]
        if name:
            target.name = name
        perms = form.getlist("perm")
        if target.id == user.id and not user.is_admin and "users" not in perms:
            perms.append("users")  # sich nicht selbst aussperren
        target.permissions = _perm_value(perms, user, target.perms)
        _set_groups(db, target, form.getlist("groups"))
        flash(request, f"{target.email} gespeichert.")
    elif action == "reset_2fa":
        twofa.reset(target)
        flash(request, f"Zwei-Faktor-Anmeldung von {target.email} zurückgesetzt. Bei Pflicht wird bei der "
                       "nächsten Anmeldung neu eingerichtet bzw. ein Code per E-Mail verwendet.")
    elif action == "toggle_active":
        target.active = not target.active
    elif action in ("invite", "reset_password"):
        kind = "reset" if target.password_set else "invite"
        link, queued = send_link(db, target, kind)
        db.commit()
        worker.wake()
        flash_link_result(request, target, link, queued)
        return redirect("/admin/users")
    elif action == "delete":
        for meeting in target.meetings:
            for rec in meeting.recordings:
                rec.meeting_id = None
            db.delete(meeting)
        _release_owned(db, target)
        db.delete(target)
        flash(request, f"{target.email} gelöscht.")
    db.commit()
    access.sync(db)
    return redirect("/admin/users")


def _release_owned(db: Session, target: User) -> None:
    """Kurzlinks und Formulare einer gelöschten Person bleiben erhalten und gehen an die löschende Verwaltung
    bzw. werden herrenlos (Admins sehen sie weiter)."""
    from .db import BookingPage, Form as FormModel, Poll, ShortLink
    for page in db.scalars(select(BookingPage).where(BookingPage.owner_id == target.id)):
        page.owner_id = None
    for poll in db.scalars(select(Poll).where(Poll.owner_id == target.id)):
        poll.owner_id = None
    for link in db.scalars(select(ShortLink).where(ShortLink.owner_id == target.id)):
        link.owner_id = None
    for form in db.scalars(select(FormModel).where(FormModel.owner_id == target.id)):
        form.owner_id = None


@app.post("/admin/groups", dependencies=[Depends(check_csrf)])
async def admin_groups_create(request: Request, name: str = Form(...), description: str = Form(""),
                              user: User = Depends(users_manager), db: Session = Depends(get_db)):
    form = await request.form()
    name = " ".join(name.split())[:120]
    if not name or db.scalar(select(Group).where(func.lower(Group.name) == name.lower())):
        flash(request, "Bitte einen neuen, noch nicht vergebenen Gruppennamen angeben.", "error")
        return redirect("/admin/users#gruppen")
    group = Group(name=name, description=" ".join(description.split())[:255],
                  lead_id=int(form["lead_id"]) if str(form.get("lead_id", "")).isdigit() else None)
    ids = {int(u) for u in form.getlist("members") if str(u).isdigit()}
    group.members = list(db.scalars(select(User).where(User.id.in_(ids)))) if ids else []
    db.add(group)
    db.commit()
    flash(request, f"Gruppe „{group.name}“ angelegt.")
    return redirect("/admin/users#gruppen")


@app.post("/admin/groups/{gid}", dependencies=[Depends(check_csrf)])
async def admin_groups_update(request: Request, gid: int, action: str = Form("save"),
                              user: User = Depends(users_manager), db: Session = Depends(get_db)):
    group = db.get(Group, gid)
    if group is None:
        raise HTTPException(404)
    if action == "delete":
        db.delete(group)
        db.commit()
        flash(request, f"Gruppe „{group.name}“ gelöscht. Die Mitglieder behalten ihre Konten.")
        return redirect("/admin/users#gruppen")
    form = await request.form()
    name = " ".join(str(form.get("name", "")).split())[:120]
    clash = db.scalar(select(Group).where(func.lower(Group.name) == name.lower(), Group.id != group.id))
    if name and not clash:
        group.name = name
    group.description = " ".join(str(form.get("description", "")).split())[:255]
    group.lead_id = int(form["lead_id"]) if str(form.get("lead_id", "")).isdigit() and db.get(User, int(form["lead_id"])) else None
    ids = {int(u) for u in form.getlist("members") if str(u).isdigit()}
    group.members = list(db.scalars(select(User).where(User.id.in_(ids)))) if ids else []
    db.commit()
    flash(request, f"Gruppe „{group.name}“ gespeichert." + (" Der Name ist schon vergeben." if clash else ""))
    return redirect("/admin/users#gruppen")


# --- Admin: Module -------------------------------------------------------------

@app.get("/admin/modules")
def admin_modules(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from .db import (BookingPage, DmsRecord, Form as FormModel, FormResponse, KrankReport, LawText, Poll,
                     Resource as ResourceModel, ShortLink, UserMap)
    from .db import Circulation, Seminar
    stats = {"seminars": db.scalar(select(func.count(Seminar.id))),"circulations": db.scalar(select(func.count(Circulation.id))), "bookings": db.scalar(select(func.count(BookingPage.id))),
             "dms": db.scalar(select(func.count(DmsRecord.id))),
             "maps": db.scalar(select(func.count(UserMap.id))),
             "applications": db.scalar(select(func.count(FormResponse.id)).where(FormResponse.ref_no.is_not(None))),
             "laws": db.scalar(select(func.count(LawText.id))),
             "shortlinks": db.scalar(select(func.count(ShortLink.id))),
             "forms": db.scalar(select(func.count(FormModel.id))),
             "polls": db.scalar(select(func.count(Poll.id))),
             "krank": db.scalar(select(func.count(KrankReport.id))),
             "resources": db.scalar(select(func.count(ResourceModel.id)))}
    return render(request, "admin_modules.html", user, all_modules=MODULES, stats=stats)


@app.post("/admin/modules", dependencies=[Depends(check_csrf)])
async def admin_modules_save(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    data = await request.form()
    for key, (label, setting, _) in MODULES.items():
        set_setting(db, setting, "1" if data.get(key) == "1" else "0")
    db.commit()
    _module_cache["at"] = 0.0
    flash(request, "Module gespeichert. Abgeschaltete Module sind sofort für alle unerreichbar; ihre Daten "
                   "bleiben erhalten und sind nach dem Wiedereinschalten wieder da.")
    return redirect("/admin/modules")


# --- Admin: Benachrichtigungen ------------------------------------------------

MAIL_FIELDS = ("smtp_host", "smtp_user", "mail_from", "mail_from_name",
               "imap_host", "imap_user", "imap_sent_folder")


@app.get("/admin/notifications")
def admin_notifications(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    log_rows = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(50)).all()
    return render(request, "admin_notifications.html", user, cfg=cfg, log_rows=log_rows,
                  smtp_mask=mask_secret(decrypt(cfg.get("smtp_password_enc"))),
                  imap_mask=mask_secret(decrypt(cfg.get("imap_password_enc"))),
                  mail_ready=notify.mail_configured(cfg))


@app.post("/admin/notifications", dependencies=[Depends(check_csrf)])
def admin_notifications_save(
    request: Request,
    smtp_host: str = Form(""), smtp_port: str = Form("587"), smtp_security: str = Form("starttls"),
    smtp_user: str = Form(""), smtp_password: str = Form(""),
    mail_from: str = Form(""), mail_from_name: str = Form(""),
    imap_host: str = Form(""), imap_port: str = Form("993"), imap_security: str = Form("ssl"),
    imap_user: str = Form(""), imap_password: str = Form(""), imap_sent_folder: str = Form("Sent"),
    imap_save_sent: str = Form(""), imap_rsvp: str = Form(""), imap_rsvp_folder: str = Form("INBOX"),
    imap_rsvp_move: str = Form(""), notify_rsvp: str = Form(""), notify_new_recording: str = Form(""),
    notify_done: str = Form(""), notify_failed: str = Form(""),
    user: User = Depends(admin_user), db: Session = Depends(get_db),
):
    if mail_from.strip() and "@" not in mail_from:
        flash(request, "Die Absenderadresse ist ungültig.", "error")
        return redirect("/admin/notifications")
    values = {
        "smtp_host": smtp_host, "smtp_user": smtp_user, "mail_from": mail_from,
        "mail_from_name": mail_from_name, "imap_host": imap_host, "imap_user": imap_user,
        "imap_sent_folder": imap_sent_folder or "Sent",
        "imap_rsvp_folder": imap_rsvp_folder or "INBOX", "imap_rsvp_move": imap_rsvp_move,
    }
    for key, value in values.items():
        set_setting(db, key, value.strip())
    for key, value, default in (("smtp_port", smtp_port, "587"), ("imap_port", imap_port, "993")):
        set_setting(db, key, value.strip() if value.strip().isdigit() else default)
    set_setting(db, "smtp_security", smtp_security if smtp_security in ("starttls", "ssl", "none") else "starttls")
    set_setting(db, "imap_security", imap_security if imap_security in ("ssl", "starttls", "none") else "ssl")
    if smtp_password:
        set_setting(db, "smtp_password_enc", encrypt(smtp_password))
    if imap_password:
        set_setting(db, "imap_password_enc", encrypt(imap_password))
    if imap_rsvp == "1" and not imap_host.strip():
        flash(request, "Für die Auswertung von Zu-/Absagen wird ein IMAP-Server benötigt.", "error")
        imap_rsvp = ""
    for key, value in (("imap_save_sent", imap_save_sent), ("imap_rsvp", imap_rsvp), ("notify_rsvp", notify_rsvp),
                       ("notify_new_recording", notify_new_recording),
                       ("notify_done", notify_done), ("notify_failed", notify_failed)):
        set_setting(db, key, "1" if value == "1" else "0")
    db.commit()
    flash(request, "Einstellungen gespeichert.")
    return redirect("/admin/notifications")


@app.post("/admin/notifications/test-smtp", dependencies=[Depends(check_csrf)])
async def admin_notifications_test_smtp(request: Request, user: User = Depends(admin_user),
                                        db: Session = Depends(get_db)):
    cfg = get_settings(db)
    try:
        await asyncio.to_thread(notify.test_smtp, cfg, user.email)
    except notify.MailError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, f"Testnachricht an {user.email} verschickt.")
    return redirect("/admin/notifications")


@app.post("/admin/notifications/test-imap", dependencies=[Depends(check_csrf)])
async def admin_notifications_test_imap(request: Request, user: User = Depends(admin_user),
                                        db: Session = Depends(get_db)):
    cfg = get_settings(db)
    try:
        info = await asyncio.to_thread(notify.test_imap, cfg)
    except notify.MailError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, info)
    return redirect("/admin/notifications")


@app.post("/admin/notifications/test-invite", dependencies=[Depends(check_csrf)])
async def admin_notifications_test_invite(request: Request, user: User = Depends(admin_user),
                                          db: Session = Depends(get_db)):
    """Schickt eine echte Testeinladung (Besprechungsanfrage) an die eigene Adresse."""
    import uuid as _uuid
    from . import ics
    cfg = get_settings(db)
    start = (utcnow() + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    org = (branding.load()["name"], cfg.get("mail_from", ""))
    cal = ics.build(method="REQUEST", uid=f"test-{_uuid.uuid4().hex}@portal", sequence=0, start=start, minutes=30,
                    title="Testeinladung Videokonferenz", description="Testeinladung aus dem Portal.",
                    location=settings.portal_base_url, url=settings.portal_base_url, organizer=org,
                    attendees=[(user.name, user.email)])
    subject, body = mailtpl.render(db, "meeting_invite", {
        **mailtpl.SAMPLE, "name": user.name, "titel": "Testeinladung Videokonferenz",
        "link": settings.portal_base_url, "antwort_link": settings.portal_base_url,
        "organisator": org[0], "beschreibung": "Dies ist eine Testeinladung.",
        "datum": planning.when(Meeting(starts_at=start, duration_minutes=30))["datum"],
        "uhrzeit": planning.when(Meeting(starts_at=start, duration_minutes=30))["uhrzeit"]}, cfg)
    try:
        await asyncio.to_thread(notify.deliver, cfg, user.email, "[Test] " + subject, body,
                                [{"filename": "einladung.ics", "content": cal, "calendar_method": "REQUEST"}])
    except notify.MailError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, f"Testeinladung an {user.email} verschickt. In Outlook sollte sie als Besprechungsanfrage "
              "mit „Annehmen/Ablehnen“ erscheinen (ggf. auch im Junk-Ordner nachsehen).")
    return redirect("/admin/notifications")


@app.get("/admin/notifications/rsvp-check")
async def admin_notifications_rsvp_check(request: Request, user: User = Depends(admin_user),
                                         db: Session = Depends(get_db)):
    """Postfach-Diagnose: welche Nachrichten im Antwort-Ordner liegen und ob sie erkannt werden."""
    from . import rsvp
    cfg = get_settings(db)
    rows, error = [], ""
    if not cfg.get("imap_host"):
        error = "Es ist kein IMAP-Server eingetragen."
    else:
        try:
            rows = await asyncio.to_thread(rsvp.inspect_mailbox)
        except notify.MailError as exc:
            error = str(exc)
    return render(request, "admin_rsvp_check.html", user, cfg=cfg, rows=rows, error=error)


@app.post("/admin/notifications/rsvp-poll", dependencies=[Depends(check_csrf)])
async def admin_notifications_rsvp_poll(request: Request, rescan: str = Form(""),
                                        user: User = Depends(admin_user)):
    from . import rsvp
    try:
        result = await asyncio.to_thread(rsvp.poll, True, rescan == "1")
    except notify.MailError as exc:
        flash(request, str(exc), "error")
    else:
        worker.wake()
        flash(request, "Postfach abgerufen: " + result)
    return redirect("/admin/notifications#antworten")


@app.post("/admin/notifications/{nid}/retry", dependencies=[Depends(check_csrf)])
def admin_notifications_retry(request: Request, nid: int, user: User = Depends(admin_user),
                              db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is not None and n.status == "failed":
        n.status, n.attempts, n.next_attempt_at = "pending", 0, utcnow()
        db.commit()
        worker.wake()
        flash(request, "Die Nachricht wird erneut versucht.")
    return redirect("/admin/notifications")


# --- Admin: alle Aufnahmen ----------------------------------------------------

@app.get("/admin/recordings")
def admin_recordings(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    recordings = db.scalars(select(Recording).options(joinedload(Recording.meeting)).order_by(Recording.created_at.desc()).limit(200)).all()
    stats = {
        "total": len(recordings),
        "ready": sum(r.status == STATUS_RECORDED for r in recordings),
        "active": sum(r.status in ACTIVE_STATUSES for r in recordings),
        "done": sum(r.status == STATUS_DONE for r in recordings),
        "failed": sum(r.status == STATUS_FAILED for r in recordings),
    }
    return render(request, "admin_recordings.html", user, recordings=recordings, stats=stats,
                  sm_ready=speechmind_ready(db))


# --- Admin: HTTPS / Zertifikat ------------------------------------------------

@app.get("/admin/domains")
async def admin_domains(request: Request, check: str = "", user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Eigene Domains je Modul (zusätzlich zur Portal-Domain)."""
    cfg = get_settings(db)
    current = modhosts.domains(cfg)
    short = (cfg.get("short_domain") or "").strip().lower()
    names = [*current.values(), *([short] if short else [])]
    dns = await asyncio.gather(*(asyncio.to_thread(proxy.dns_check, d) for d in names))
    certs = await asyncio.gather(*(asyncio.to_thread(proxy.inspect, d) for d in names)) if check else []
    return render(request, "admin_domains.html", user, cfg=cfg, modules_public=modhosts.MODULE_PUBLIC, current=current,
                  short=short, dns=dict(zip(names, dns)), certs=dict(zip(names, certs)), checked=bool(check),
                  hosts=proxy.hosts(), available=proxy.available(), public_ips=settings.public_ips,
                  portal=settings.portal_base_url)


@app.post("/admin/domains", dependencies=[Depends(check_csrf)])
async def admin_domains_save(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    form = await request.form()
    cfg = get_settings(db)
    new = {key: modhosts.clean(str(form.get(key) or "")) for key in modhosts.MODULE_PUBLIC}
    reserved = {**{("Konferenz" if k == "meet" else "Portal"): v for k, v in proxy.hosts().items()},
                "Kurzlinks": (cfg.get("short_domain") or "").strip().lower()}
    errors = modhosts.validate(new, reserved)
    if errors:
        for err in errors:
            flash(request, err, "error")
        return redirect("/admin/domains")
    updated = {**cfg, **{f"domain_{k}": v for k, v in new.items()}}
    if proxy.available():
        try:
            proxy.write(updated)
        except (ValueError, OSError) as exc:
            flash(request, f"Proxy-Konfiguration nicht geschrieben: {exc}", "error")
            return redirect("/admin/domains")
    for key, value in new.items():
        set_setting(db, f"domain_{key}", value)
    db.commit()
    _host_cache["at"] = 0.0
    links.invalidate()
    added = [d for k, d in new.items() if d and d != (cfg.get(f"domain_{k}") or "")]
    flash(request, "Domains gespeichert." + (
        f" Neu: {', '.join(added)}. Jede Domain braucht einen DNS-Eintrag (A/AAAA) auf diesen Server; das Zertifikat "
        "holt der Proxy selbst und erneuert es automatisch." if added else "") +
        ("" if proxy.available() else " Achtung: Der Proxy ist von hier aus nicht steuerbar – Caddyfile bitte selbst ergänzen."))
    return redirect("/admin/domains")


@app.get("/admin/https")
async def admin_https(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    h = proxy.hosts()
    certs = await asyncio.gather(*(asyncio.to_thread(proxy.inspect, host) for host in h.values()))
    dns = await asyncio.gather(*(asyncio.to_thread(proxy.dns_check, host) for host in h.values()))
    return render(request, "admin_https.html", user, cfg=cfg, hosts=h, certs=certs, dns=dns,
                  available=proxy.available(), has_root=proxy.root_cert_path() is not None,
                  default_email=cfg.get("tls_email") or settings.acme_email or user.email,
                  public_ips=settings.public_ips)


@app.post("/admin/https", dependencies=[Depends(check_csrf)])
def admin_https_save(request: Request, tls_mode: str = Form("selfsigned"), tls_email: str = Form(""),
                     tls_staging: str = Form(""), user: User = Depends(admin_user),
                     db: Session = Depends(get_db)):
    mode = "letsencrypt" if tls_mode == "letsencrypt" else "selfsigned"
    email = tls_email.strip().lower()
    if mode == "letsencrypt" and not proxy.valid_email(email):
        flash(request, "Für Let's Encrypt wird eine gültige E-Mail-Adresse benötigt.", "error")
        return redirect("/admin/https")
    if not proxy.available():
        flash(request, "Der Konfigurationsordner des Proxys ist nicht eingebunden (siehe Admin-Handbuch).", "error")
        return redirect("/admin/https")
    new = {"tls_mode": mode, "tls_email": email, "tls_staging": "1" if tls_staging == "1" else "0"}
    try:
        proxy.write({**get_settings(db), **new})
    except (ValueError, OSError) as exc:
        flash(request, f"Die Proxy-Konfiguration konnte nicht geschrieben werden: {exc}", "error")
        return redirect("/admin/https")
    for key, value in new.items():
        set_setting(db, key, value)
    db.commit()
    flash(request, "Gespeichert. Der Proxy übernimmt die Einstellung innerhalb weniger Sekunden"
          + (" und beantragt das Zertifikat bei Let's Encrypt (dauert meist unter einer Minute)." if mode == "letsencrypt"
             else " und stellt wieder selbst signierte Zertifikate aus."))
    return redirect("/admin/https")


@app.get("/admin/https/root.crt")
def admin_https_root(user: User = Depends(admin_user)):
    path = proxy.root_cert_path()
    if path is None:
        raise HTTPException(404, "Es gibt noch kein Root-Zertifikat. Es entsteht beim ersten Start des Proxys.")
    return FileResponse(path, media_type="application/x-x509-ca-cert", filename="proxy-root-ca.crt")


# --- Admin: Zugang ohne Anmeldung --------------------------------------------

@app.post("/admin/access", dependencies=[Depends(check_csrf)])
def admin_access(request: Request, allow_anonymous: str = Form(""), user: User = Depends(admin_user),
                 db: Session = Depends(get_db)):
    set_setting(db, "allow_anonymous", "1" if allow_anonymous == "1" else "0")
    db.commit()
    access.sync(db)
    flash(request, "Konferenzen ohne Anmeldung sind " + ("freigegeben." if allow_anonymous == "1" else "gesperrt."))
    return redirect("/admin/users")


# --- Admin: Design & Branding -------------------------------------------------

DESIGN_TEXT_FIELDS = ("ui_brand_name", "ui_product", "ui_login_text", "ui_footer_text",
                      "ui_imprint_url", "ui_privacy_url")


@app.get("/branding/{kind}")
def branding_file(kind: str):
    if kind == "jitsi.json":
        return branding_jitsi()
    path = branding.file_path(kind) if kind in ("logo", "favicon", "favicon_auto") else None
    if path is None:
        raise HTTPException(404)
    media = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp",
             "svg": "image/svg+xml", "ico": "image/x-icon"}.get(path.suffix.lstrip("."), "application/octet-stream")
    return FileResponse(path, media_type=media, headers={
        "Cache-Control": "public, max-age=86400",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        "X-Content-Type-Options": "nosniff",
    })


def _drop_brand_file(db: Session, key: str) -> None:
    name = get_settings(db).get(key) or ""
    if name and "/" not in name:
        (branding.BRAND_DIR / name).unlink(missing_ok=True)
    set_setting(db, key, "")


@app.get("/admin/design")
def admin_design(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    return render(request, "admin_design.html", user, cfg=cfg, navbars=branding.NAVBARS,
                  photos=branding.photo_sizes(cfg), thumb_ratios=branding.THUMB_RATIOS,
                  radii=branding.RADII, default_primary=branding.DEFAULT_PRIMARY,
                  logo_url=branding._file(cfg, "ui_logo")[1], favicon_url=branding._file(cfg, "ui_favicon")[1],
                  favicon_auto_url=branding._file(cfg, "ui_favicon_auto")[1] if cfg.get("ui_logo") else "")


@app.get("/admin/design/mail-vorschau")
def admin_design_mail_preview(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Vorschau einer Mail im aktuellen Erscheinungsbild (Logo als Daten-URL statt cid:)."""
    cfg = get_settings(db)
    frame = notify.mail_frame(cfg) or None
    sample = ("Guten Tag Erika Muster,\n\nIhre Buchung RB-2026-00042 ist bestätigt:\n\nGrillhütte am Weiher\n"
              "Samstag, 12.09.2026, ganztägig\n\nIhre Buchung ansehen: " + settings.portal_base_url + "/r/b/beispiel"
              "\n\nMit freundlichen Grüßen\nIhre Verwaltung")
    page = notify.text_to_html(sample, frame)
    if frame and frame.get("logo"):
        data, sub = frame["logo"]
        page = page.replace(f"cid:{frame['cid']}", f"data:image/{sub};base64," + base64.b64encode(data).decode("ascii"))
    return HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'"})


@app.post("/admin/design", dependencies=[Depends(check_csrf)])
async def admin_design_save(
    request: Request,
    ui_custom: str = Form(""), ui_primary: str = Form(""), ui_navbar: str = Form("dark"),
    ui_theme: str = Form("auto"), ui_radius: str = Form("0.375rem"), ui_logo_height: str = Form("32"),
    ui_show_name: str = Form(""), ui_jitsi: str = Form(""), remove_logo: str = Form(""),
    remove_favicon: str = Form(""),
    ui_brand_name: str = Form(""), ui_product: str = Form(""), ui_login_text: str = Form(""),
    ui_footer_text: str = Form(""), ui_imprint_url: str = Form(""), ui_privacy_url: str = Form(""),
    ui_gallery_h: str = Form(""), ui_gallery_h_mobile: str = Form(""), ui_thumb_ratio: str = Form(""),
    ui_photo_fit: str = Form(""), ui_mail_frame: str = Form("1"),
    logo: UploadFile | None = File(None), favicon: UploadFile | None = File(None),
    user: User = Depends(admin_user), db: Session = Depends(get_db),
):
    values = dict(ui_brand_name=ui_brand_name, ui_product=ui_product, ui_login_text=ui_login_text,
                  ui_footer_text=ui_footer_text, ui_imprint_url=ui_imprint_url, ui_privacy_url=ui_privacy_url)
    for key in DESIGN_TEXT_FIELDS:
        set_setting(db, key, values[key].strip()[:500])
    set_setting(db, "ui_custom", "1" if ui_custom == "1" else "0")
    if branding.HEX.match(ui_primary.strip()):
        set_setting(db, "ui_primary", ui_primary.strip().lower())
    set_setting(db, "ui_navbar", ui_navbar if ui_navbar in branding.NAVBARS else "dark")
    set_setting(db, "ui_theme", ui_theme if ui_theme in branding.THEMES else "auto")
    set_setting(db, "ui_radius", ui_radius if ui_radius in branding.RADII else "0.375rem")
    set_setting(db, "ui_logo_height", ui_logo_height if ui_logo_height.isdigit() else "32")
    set_setting(db, "ui_show_name", "1" if ui_show_name == "1" else "0")
    set_setting(db, "ui_jitsi", "1" if ui_jitsi == "1" else "0")
    photos = branding.photo_sizes({"ui_gallery_h": ui_gallery_h, "ui_gallery_h_mobile": ui_gallery_h_mobile,
                                   "ui_thumb_ratio": ui_thumb_ratio, "ui_photo_fit": ui_photo_fit})
    set_setting(db, "ui_gallery_h", str(photos["gallery"]))
    set_setting(db, "ui_gallery_h_mobile", str(photos["gallery_mobile"]))
    set_setting(db, "ui_thumb_ratio", photos["ratio"])
    set_setting(db, "ui_photo_fit", photos["fit"])
    set_setting(db, "ui_mail_frame", "0" if ui_mail_frame == "0" else "1")

    errors, notes = [], []
    for key, upload, remove, allowed in (("ui_logo", logo, remove_logo, branding.LOGO_TYPES),
                                         ("ui_favicon", favicon, remove_favicon, branding.FAVICON_TYPES)):
        label = "Logo" if key == "ui_logo" else "Favicon"
        if remove == "1":
            _drop_brand_file(db, key)
            if key == "ui_logo":
                _drop_brand_file(db, "ui_favicon_auto")
        if upload is None or not upload.filename:
            continue
        data = await upload.read(branding.MAX_UPLOAD + 1)
        try:
            ext = branding.check_upload(data, upload.filename, allowed, branding.MAX_UPLOAD)
            if key == "ui_logo":
                stored, ext, shrunk = await asyncio.to_thread(branding.shrink_logo, data, ext)
                if shrunk:
                    notes.append(f"Das Logo wurde für die Anzeige verkleinert ({len(data) // 1024} kB → "
                                 f"{len(stored) // 1024} kB).")
                icon, icon_ext = await asyncio.to_thread(branding.make_favicon, stored, ext)
            else:
                stored, ext = await asyncio.to_thread(branding.make_favicon, data, ext, 256)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
            continue
        _drop_brand_file(db, key)
        branding.BRAND_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{key.removeprefix('ui_')}-{secrets.token_hex(4)}.{ext}"
        (branding.BRAND_DIR / name).write_bytes(stored)
        set_setting(db, key, name)
        if key == "ui_logo":
            # Favicon aus dem Logo: gilt, solange kein eigenes Favicon hochgeladen ist
            _drop_brand_file(db, "ui_favicon_auto")
            auto = f"favicon_auto-{secrets.token_hex(4)}.{icon_ext}"
            (branding.BRAND_DIR / auto).write_bytes(icon)
            set_setting(db, "ui_favicon_auto", auto)
    db.commit()
    branding.invalidate()
    for err in errors:
        flash(request, err, "error")
    cfg = get_settings(db)
    if cfg.get("ui_custom") != "1" and (cfg.get("ui_primary") != branding.DEFAULT_PRIMARY or cfg.get("ui_logo")
                                        or cfg.get("ui_navbar") != "dark" or cfg.get("ui_theme") != "auto"):
        flash(request, "Gespeichert, aber das eigene Design ist ausgeschaltet: Farben und Logo sind deshalb "
              "noch nicht sichtbar. Schalten Sie oben „Eigenes Design“ ein und speichern Sie erneut.", "error")
    else:
        flash(request, "Design gespeichert und angewendet.")
    for note in notes:
        flash(request, note)
    return redirect("/admin/design")


@app.get("/branding/jitsi.json")
def branding_jitsi():
    """Dynamisches Branding für Jitsi Meet (config.dynamicBrandingUrl).

    Wird über die Konferenz-Domain ausgeliefert (Caddy leitet /branding/* ans Portal weiter),
    damit der Browser und Jibri es ohne CORS und Zertifikatsfragen laden können.
    """
    ui = branding.load()
    data: dict = {}
    with SessionLocal() as db:
        enabled = get_settings(db).get("ui_jitsi") == "1"
    if ui["custom"] and enabled:
        data = {
            "backgroundColor": branding.shade(ui["primary"], .72),
            "premeetingBackground": f"linear-gradient(135deg, {branding.shade(ui['primary'], .55)}, {ui['primary']})",
            "logoClickUrl": settings.portal_base_url,
        }
        if ui["logo"]:
            data["logoImageUrl"] = settings.meet_base_url + ui["logo"]
    return JSONResponse(data, headers={"Cache-Control": "no-cache"})


@app.post("/admin/design/reset", dependencies=[Depends(check_csrf)])
def admin_design_reset(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from .db import DEFAULT_SETTINGS
    for key in ("ui_logo", "ui_favicon", "ui_favicon_auto"):
        _drop_brand_file(db, key)
    for key, value in DEFAULT_SETTINGS.items():
        if key.startswith("ui_"):
            set_setting(db, key, value)
    db.commit()
    branding.invalidate()
    flash(request, "Das Design wurde auf die Standardwerte zurückgesetzt.")
    return redirect("/admin/design")


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    uid = request.session.get("uid")
    with SessionLocal() as db:
        user = db.get(User, uid) if uid else None
        response = render(request, "error.html", user, status=exc.status_code, detail=exc.detail)
    response.status_code = exc.status_code
    return response


__all__ = ["app", "STATUS_RECORDED"]


# Weitere Bereiche (registrieren ihre Routen an derselben App)
from . import routes_shortlinks  # noqa: E402,F401
from . import routes_blocks  # noqa: E402,F401  (vor routes_forms: /forms/blocks vor /forms/{id})
from . import routes_applications  # noqa: E402,F401  (vor routes_forms: /forms/applications vor /forms/{id})
from . import routes_form_mail  # noqa: E402,F401
from . import routes_forms  # noqa: E402,F401
from . import routes_workflow  # noqa: E402,F401
from . import routes_geo  # noqa: E402,F401
from . import routes_dms  # noqa: E402,F401
from . import routes_polls  # noqa: E402,F401
from . import routes_bookings  # noqa: E402,F401
from . import routes_btypes  # noqa: E402,F401
from . import routes_live  # noqa: E402,F401
from . import routes_public  # noqa: E402,F401
from . import routes_absences  # noqa: E402,F401
from . import routes_sessions  # noqa: E402,F401
from . import routes_circulations  # noqa: E402,F401
from . import routes_laws  # noqa: E402,F401
from . import routes_maps  # noqa: E402,F401
from . import routes_payments  # noqa: E402,F401
from . import routes_votes  # noqa: E402,F401
from . import routes_resources  # noqa: E402,F401
from . import routes_resources_public  # noqa: E402,F401
from . import routes_caretakers  # noqa: E402,F401
from . import routes_qr  # noqa: E402,F401
from . import routes_trash  # noqa: E402,F401
from . import routes_krank  # noqa: E402,F401
from . import routes_orgs  # noqa: E402,F401

from . import routes_locations  # noqa: E402,F401

from . import routes_expenses  # noqa: E402,F401


@app.post("/nav/expand", dependencies=[Depends(check_csrf)])
async def nav_expand(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import nav
    data = await request.form()
    target = db.get(User, user.id)
    p = nav.prefs(target)
    target.nav_json = nav.dump(p["fav"], p["hidden"], data.getlist("closed"))
    db.commit()
    return JSONResponse({"ok": True})

from . import routes_seminars  # noqa: E402,F401

from . import routes_seminar_learning  # noqa: E402,F401

from . import routes_seminar_series  # noqa: E402,F401
