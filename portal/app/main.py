import asyncio
import json
import re
import logging
import secrets
import shutil
import time
from datetime import timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import branding, notify, worker
from .config import settings
from .db import (
    ACTIVE_STATUSES, STATUS_DONE, STATUS_FAILED, STATUS_QUEUED, STATUS_RECORDED, Meeting,
    Notification, Recording, SessionLocal, User, get_settings, init_db, set_setting, to_local, utcnow,
)
from .security import (
    clean_room, csrf_token, csrf_valid, decrypt, encrypt, hash_password, hash_token,
    is_open_room, jitsi_token, mask_secret, new_open_room, new_token, open_room_token, room_slug,
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
templates.env.globals.update(brand=settings.brand_name, product=settings.brand_product)
templates.env.globals["themes"] = branding.THEMES
templates.env.filters["filesize"] = lambda n: (
    "" if not n else f"{n / 1_000_000:.1f} MB".replace(".", ",") if n >= 1_000_000 else f"{max(n // 1000, 1)} kB")
templates.env.filters["local"] = lambda dt, fmt="%d.%m.%Y, %H:%M": to_local(dt).strftime(fmt) if dt else ""


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
    if user.must_change_password and request.url.path != "/profile":
        flash(request, "Bitte vergeben Sie zuerst ein eigenes Passwort.", "error")
        raise ForcedRedirect("/profile")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Nur für Administratoren.")
    return user


_attempts: dict[str, list[float]] = {}


def rate_limit(request: Request, bucket: str, limit: int = 10, window: int = 600) -> None:
    """Einfache Bremse gegen Passwort-Raten und Mail-Fluten (pro Adresse, im Speicher)."""
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    key, now = f"{bucket}:{ip}", time.monotonic()
    hits = [t for t in _attempts.get(key, []) if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(429, "Zu viele Versuche. Bitte in einigen Minuten erneut versuchen.")
    hits.append(now)
    _attempts[key] = hits
    if len(_attempts) > 5000:
        _attempts.clear()


async def check_csrf(request: Request) -> None:
    form = await request.form()
    if not csrf_valid(request.session, form.get("csrf")):
        raise HTTPException(400, "Sitzung abgelaufen. Bitte Seite neu laden und erneut versuchen.")


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"kind": kind, "text": message})


def render(request: Request, name: str, user: User | None = None, **ctx) -> HTMLResponse:
    messages = request.session.pop("flash", [])
    ui = branding.load()
    return templates.TemplateResponse(request, name, {
        "user": user,
        "ui": ui, "brand": ui["name"], "product": ui["product"],
        "csrf": csrf_token(request.session),
        "messages": messages,
        "status_labels": STATUS_LABELS,
        "pipeline": PIPELINE,
        "active_statuses": ACTIVE_STATUSES,
        "meet_base_url": settings.meet_base_url,
        **ctx,
    })


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/"


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
    if is_open_room(base):
        base = "m-" + base  # Präfix offener Räume ist reserviert
    room = base
    while db.scalar(select(Meeting).where(Meeting.room == room)) is not None:
        room = f"{base}-{secrets.token_hex(2)}"
    return room


def join_url(user: User, room: str) -> str:
    return f"{settings.meet_base_url}/{room}?{urlencode({'jwt': jitsi_token(user, room)})}"


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
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.active or not verify_password(user.password_hash, password):
        flash(request, "E-Mail oder Passwort ist falsch.", "error")
        return redirect(f"/login?next={quote(safe_next(next))}")
    request.session.clear()
    request.session["uid"] = user.id
    target = safe_next(next)
    if user.is_admin and target == "/":
        target = "/admin/recordings"
    return redirect(target)


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
    subject, body = (notify.invite_text if kind == "invite" else notify.reset_text)(target, link)
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
    request.session.clear()
    request.session["uid"] = target.id
    flash(request, "Passwort gespeichert. Sie sind angemeldet.")
    return redirect("/")


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
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


def anonymous_allowed(db: Session) -> bool:
    return get_settings(db).get("allow_anonymous") == "1"


def open_join_url(name: str, room: str) -> str:
    return f"{settings.meet_base_url}/{room}?{urlencode({'jwt': open_room_token(name, room)})}"


def session_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    return user if user and user.active else None


@app.get("/jitsi/auth")
def jitsi_auth(request: Request, room: str = "", db: Session = Depends(get_db)):
    """Ziel von TOKEN_AUTH_URL: Jitsi schickt Moderatoren ohne Token hierher."""
    room = clean_room(room)
    if not room:
        return redirect("/")
    if is_open_room(room):
        # Offene Konferenz: nur die Person, die sie eröffnet hat, wird Moderator:in
        user = session_user(request, db)
        if anonymous_allowed(db) and room in request.session.get("open_rooms", []):
            return redirect(open_join_url(user.name if user else request.session.get("open_name", "Gastgeber:in"), room))
        return render(request, "open.html", user, mode="foreign", enabled=anonymous_allowed(db))
    user = current_user(request, db)
    meeting = db.scalar(select(Meeting).where(Meeting.room == room))
    if meeting is None:
        meeting = Meeting(owner_id=user.id, title=room.replace("-", " ").title(), room=room)
        db.add(meeting)
        db.commit()
    return redirect(join_url(user, room))


@app.get("/open")
def open_form(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    return render(request, "open.html", user, mode="form", enabled=anonymous_allowed(db))


@app.post("/open", dependencies=[Depends(check_csrf)])
def open_start(request: Request, name: str = Form(""), db: Session = Depends(get_db)):
    """Konferenz ohne Konto starten – ohne Aufnahmefunktion."""
    if not anonymous_allowed(db):
        raise HTTPException(403, "Konferenzen ohne Anmeldung sind derzeit nicht freigegeben.")
    rate_limit(request, "open", limit=10)
    user = session_user(request, db)
    name = " ".join(name.split())[:60] or (user.name if user else "")
    if not name:
        flash(request, "Bitte geben Sie Ihren Namen an.", "error")
        return redirect("/open")
    room = new_open_room()
    rooms = (request.session.get("open_rooms", []) + [room])[-20:]
    request.session["open_rooms"], request.session["open_name"] = rooms, name
    return redirect(open_join_url(name, room))


# --- Dashboard & Meetings -----------------------------------------------------

@app.get("/")
def dashboard(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    meetings = db.scalars(
        select(Meeting).where(Meeting.owner_id == user.id).order_by(Meeting.created_at.desc())
    ).all()
    recent = db.scalars(
        select(Recording).join(Meeting).where(Meeting.owner_id == user.id)
        .order_by(Recording.created_at.desc()).limit(8)
    ).all()
    return render(request, "dashboard.html", user, meetings=meetings, recent=recent,
                  sm_ready=speechmind_ready(db, user), anonymous=anonymous_allowed(db))


@app.post("/meetings", dependencies=[Depends(check_csrf)])
def create_meeting(request: Request, title: str = Form(...),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    title = title.strip()[:200] or "Besprechung"
    meeting = Meeting(owner_id=user.id, title=title, room=unique_room(db, room_slug(title)))
    db.add(meeting)
    db.commit()
    flash(request, f"Meeting „{title}“ angelegt.")
    return redirect(f"/meetings/{meeting.id}")


@app.get("/meetings/{meeting_id}")
def meeting_detail(request: Request, meeting_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    return render(request, "meeting.html", user, meeting=meeting,
                  guest_url=f"{settings.meet_base_url}/{meeting.room}",
                  document_types=DOCUMENT_TYPES, languages=LANGUAGES,
                  sm_ready=speechmind_ready(db, meeting.owner))


@app.post("/meetings/{meeting_id}/settings", dependencies=[Depends(check_csrf)])
def meeting_settings(request: Request, meeting_id: int, title: str = Form(...),
                     document_type: str = Form(""),
                     language: str = Form(""), user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    meeting.title = title.strip()[:200] or meeting.title
    meeting.document_type = document_type if document_type in DOCUMENT_TYPES else None
    meeting.language = language if language in LANGUAGES else None
    db.commit()
    flash(request, "Einstellungen gespeichert.")
    return redirect(f"/meetings/{meeting.id}")


@app.post("/meetings/{meeting_id}/delete", dependencies=[Depends(check_csrf)])
def meeting_delete(request: Request, meeting_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    for rec in meeting.recordings:
        rec.meeting_id = None
    db.delete(meeting)
    db.commit()
    flash(request, "Meeting gelöscht. Vorhandene Aufnahmen bleiben für Admins sichtbar.")
    return redirect("/")


@app.get("/meetings/{meeting_id}/join")
def meeting_join(meeting_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    return redirect(join_url(user, meeting.room))


# --- Aufnahmen & Transkripte --------------------------------------------------

@app.get("/recordings/{rec_id}")
def recording_detail(request: Request, rec_id: int, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    transcript = json.loads(rec.transcript_json) if rec.transcript_json else []
    summary = json.loads(rec.summary_json) if rec.summary_json else {}
    has_video = bool(rec.video_path and Path(rec.video_path).exists())
    return render(request, "recording.html", user, rec=rec, transcript=transcript,
                  summary=summary, has_video=has_video, has_audio=rec.audio_size is not None,
                  participants=json.loads(rec.participants or "[]"))


@app.post("/recordings/{rec_id}/transcribe", dependencies=[Depends(check_csrf)])
def recording_transcribe(request: Request, rec_id: int, user: User = Depends(current_user),
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


@app.get("/recordings/{rec_id}/audio.mp3")
def recording_audio(rec_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    path = Path(rec.audio_path) if rec.audio_path else None
    if not path or not path.exists():
        raise HTTPException(404, "Die MP3-Datei ist (noch) nicht vorhanden.")
    title = rec.meeting.title if rec.meeting else rec.room
    return FileResponse(path, media_type="audio/mpeg",
                        filename=f"aufnahme-{room_slug(title)}-{to_local(rec.created_at):%Y%m%d-%H%M}.mp3")


@app.get("/recordings/{rec_id}/video")
def recording_video(rec_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    path = Path(rec.video_path) if rec.video_path else None
    root = settings.recordings_dir.resolve()
    if not path or not path.exists() or root not in path.resolve().parents:
        raise HTTPException(404, "Die Videodatei ist nicht mehr vorhanden.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/recordings/{rec_id}/transcript.txt", response_class=PlainTextResponse)
def recording_transcript_txt(rec_id: int, user: User = Depends(current_user),
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


@app.post("/recordings/{rec_id}/delete", dependencies=[Depends(check_csrf)])
def recording_delete(request: Request, rec_id: int, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    rec = own_recording(db, rec_id, user)
    if rec.status in ACTIVE_STATUSES:
        flash(request, "Die Aufnahme wird gerade verarbeitet und kann erst danach gelöscht werden.", "error")
        return redirect(f"/recordings/{rec.id}")
    session_dir = Path(rec.session_dir)
    root = settings.recordings_dir.resolve()
    if session_dir.exists() and root in session_dir.resolve().parents:
        shutil.rmtree(session_dir, ignore_errors=True)
    if rec.audio_path:
        Path(rec.audio_path).unlink(missing_ok=True)
    target = f"/meetings/{rec.meeting_id}" if rec.meeting_id else "/admin/recordings"
    db.delete(rec)
    db.commit()
    flash(request, "Aufnahme und Transkript gelöscht (bei SpeechMind bleibt das Protokoll bestehen).")
    return redirect(target)


# --- Profil -------------------------------------------------------------------

@app.get("/profile")
def profile(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    return render(request, "profile.html", user,
                  allow_user_keys=cfg.get("allow_user_keys") == "1",
                  own_key_mask=mask_secret(decrypt(user.sm_api_key_enc)))


@app.post("/profile", dependencies=[Depends(check_csrf)])
def profile_save(request: Request, name: str = Form(...), current_password: str = Form(""),
                 new_password: str = Form(""), sm_api_key: str = Form(""),
                 sm_project_slug: str = Form(""), sm_remove_key: str = Form(""),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, user.id)
    user.name = name.strip()[:200] or user.name
    if new_password:
        if len(new_password) < 10:
            flash(request, "Das neue Passwort braucht mindestens 10 Zeichen.", "error")
            return redirect("/profile")
        if not verify_password(user.password_hash, current_password):
            flash(request, "Das aktuelle Passwort stimmt nicht.", "error")
            return redirect("/profile")
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
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
        request.session["invite_links"] = [{"email": target.email, "link": link}]


@app.get("/admin/users")
def admin_users(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.name)).all()
    return render(request, "admin_users.html", user, users=users,
                  invite_links=request.session.pop("invite_links", None),
                  mail_ready=notify.mail_configured(get_settings(db)),
                  invite_ttl=settings.invite_ttl_hours,
                  allow_anonymous=anonymous_allowed(db))


EMAIL_RE = re.compile(r"^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$")


def name_from_email(email: str) -> str:
    return " ".join(p.capitalize() for p in re.split(r"[._\-+]+", email.split("@")[0]) if p) or email


@app.post("/admin/users", dependencies=[Depends(check_csrf)])
def admin_users_create(request: Request, emails: str = Form(...), name: str = Form(""),
                       is_admin: str = Form(""), user: User = Depends(admin_user),
                       db: Session = Depends(get_db)):
    """Lädt eine oder mehrere Personen ein (Adressen durch Komma, Semikolon oder Leerzeichen getrennt)."""
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
        target = User(email=email, name=display, is_admin=is_admin == "1",
                      password_hash=hash_password(secrets.token_urlsafe(32)), password_set=False)
        db.add(target)
        link, queued = send_link(db, target, "invite")
        created.append(email)
        if not queued:
            links.append({"email": email, "link": link})
    db.commit()
    worker.wake()
    if links:
        request.session["invite_links"] = links
    if created:
        flash(request, f"{len(created)} Einladung(en) angelegt: " + ", ".join(created))
    return redirect("/admin/users")


@app.post("/admin/users/{uid}", dependencies=[Depends(check_csrf)])
def admin_users_update(request: Request, uid: int, action: str = Form(...),
                       user: User = Depends(admin_user), db: Session = Depends(get_db)):
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404)
    if target.id == user.id and action in ("toggle_admin", "toggle_active", "delete"):
        flash(request, "Das eigene Konto lässt sich hier nicht ändern.", "error")
        return redirect("/admin/users")
    if action == "toggle_admin":
        target.is_admin = not target.is_admin
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
        db.delete(target)
        flash(request, f"{target.email} gelöscht.")
    db.commit()
    return redirect("/admin/users")


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
    imap_save_sent: str = Form(""), notify_new_recording: str = Form(""),
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
    for key, value in (("imap_save_sent", imap_save_sent), ("notify_new_recording", notify_new_recording),
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


# --- Admin: Zugang ohne Anmeldung --------------------------------------------

@app.post("/admin/access", dependencies=[Depends(check_csrf)])
def admin_access(request: Request, allow_anonymous: str = Form(""), user: User = Depends(admin_user),
                 db: Session = Depends(get_db)):
    set_setting(db, "allow_anonymous", "1" if allow_anonymous == "1" else "0")
    db.commit()
    flash(request, "Konferenzen ohne Anmeldung sind " + ("freigegeben." if allow_anonymous == "1" else "gesperrt."))
    return redirect("/admin/users")


# --- Admin: Design & Branding -------------------------------------------------

DESIGN_TEXT_FIELDS = ("ui_brand_name", "ui_product", "ui_login_text", "ui_footer_text",
                      "ui_imprint_url", "ui_privacy_url")


@app.get("/branding/{kind}")
def branding_file(kind: str):
    path = branding.file_path(kind) if kind in ("logo", "favicon") else None
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
                  radii=branding.RADII, default_primary=branding.DEFAULT_PRIMARY,
                  logo_url=branding._file(cfg, "ui_logo")[1], favicon_url=branding._file(cfg, "ui_favicon")[1])


@app.post("/admin/design", dependencies=[Depends(check_csrf)])
async def admin_design_save(
    request: Request,
    ui_custom: str = Form(""), ui_primary: str = Form(""), ui_navbar: str = Form("dark"),
    ui_theme: str = Form("auto"), ui_radius: str = Form("0.375rem"), ui_logo_height: str = Form("32"),
    ui_show_name: str = Form(""), remove_logo: str = Form(""), remove_favicon: str = Form(""),
    ui_brand_name: str = Form(""), ui_product: str = Form(""), ui_login_text: str = Form(""),
    ui_footer_text: str = Form(""), ui_imprint_url: str = Form(""), ui_privacy_url: str = Form(""),
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

    errors = []
    for key, upload, remove, allowed, limit in (
        ("ui_logo", logo, remove_logo, branding.LOGO_TYPES, 1_000_000),
        ("ui_favicon", favicon, remove_favicon, branding.FAVICON_TYPES, 256_000),
    ):
        if remove == "1":
            _drop_brand_file(db, key)
        if upload is not None and upload.filename:
            data = await upload.read(limit + 1)
            try:
                ext = branding.check_upload(data, upload.filename, allowed, limit)
            except ValueError as exc:
                errors.append(f"{'Logo' if key == 'ui_logo' else 'Favicon'}: {exc}")
                continue
            _drop_brand_file(db, key)
            branding.BRAND_DIR.mkdir(parents=True, exist_ok=True)
            name = f"{key.removeprefix('ui_')}-{secrets.token_hex(4)}.{ext}"
            (branding.BRAND_DIR / name).write_bytes(data)
            set_setting(db, key, name)
    db.commit()
    branding.invalidate()
    for err in errors:
        flash(request, err, "error")
    flash(request, "Design gespeichert.")
    return redirect("/admin/design")


@app.post("/admin/design/reset", dependencies=[Depends(check_csrf)])
def admin_design_reset(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from .db import DEFAULT_SETTINGS
    for key in ("ui_logo", "ui_favicon"):
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
    uid = request.session.get("uid")
    with SessionLocal() as db:
        user = db.get(User, uid) if uid else None
        response = render(request, "error.html", user, status=exc.status_code, detail=exc.detail)
    response.status_code = exc.status_code
    return response


__all__ = ["app", "STATUS_RECORDED"]
