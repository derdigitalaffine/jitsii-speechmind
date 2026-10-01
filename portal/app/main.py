import asyncio
import json
import logging
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import worker
from .config import settings
from .db import (
    ACTIVE_STATUSES, STATUS_DONE, STATUS_FAILED, STATUS_QUEUED, STATUS_RECORDED, Meeting,
    Recording, SessionLocal, User, get_settings, init_db, set_setting, to_local,
)
from .security import (
    clean_room, csrf_token, csrf_valid, decrypt, encrypt, hash_password, jitsi_token,
    mask_secret, room_slug, verify_password,
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
    "recorded": "Aufgezeichnet",
    "queued": "Wartet",
    "converting": "Audiospur wird extrahiert",
    "uploading": "Wird hochgeladen",
    "processing": "SpeechMind transkribiert",
    "done": "Transkript fertig",
    "failed": "Fehlgeschlagen",
}


def bootstrap_admin() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))) == 0:
            if not settings.admin_email or not settings.admin_password:
                log.warning("Keine Benutzer vorhanden und PORTAL_ADMIN_EMAIL/PASSWORD nicht gesetzt.")
                return
            db.add(User(
                email=settings.admin_email, name="Administrator",
                password_hash=hash_password(settings.admin_password), is_admin=True,
            ))
            db.commit()
            log.info("Admin-Konto %s angelegt", settings.admin_email)


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
templates.env.filters["local"] = lambda dt, fmt="%d.%m.%Y, %H:%M": to_local(dt).strftime(fmt) if dt else ""


# --- Hilfsfunktionen ----------------------------------------------------------

class LoginRequired(Exception):
    def __init__(self, next_url: str):
        self.next_url = next_url


@app.exception_handler(LoginRequired)
async def _login_redirect(_request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)


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
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Nur für Administratoren.")
    return user


async def check_csrf(request: Request) -> None:
    form = await request.form()
    if not csrf_valid(request.session, form.get("csrf")):
        raise HTTPException(400, "Sitzung abgelaufen. Bitte Seite neu laden und erneut versuchen.")


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"kind": kind, "text": message})


def render(request: Request, name: str, user: User | None = None, **ctx) -> HTMLResponse:
    messages = request.session.pop("flash", [])
    return templates.TemplateResponse(request, name, {
        "user": user,
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
def login_form(request: Request, next: str = "/"):
    return render(request, "login.html", next=safe_next(next))


@app.post("/login", dependencies=[Depends(check_csrf)])
def login(request: Request, email: str = Form(...), password: str = Form(...),
          next: str = Form("/"), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.active or not verify_password(user.password_hash, password):
        flash(request, "E-Mail oder Passwort ist falsch.", "error")
        return redirect(f"/login?next={quote(safe_next(next))}")
    request.session.clear()
    request.session["uid"] = user.id
    return redirect(safe_next(next))


@app.post("/logout", dependencies=[Depends(check_csrf)])
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@app.get("/jitsi/auth")
def jitsi_auth(room: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ziel von TOKEN_AUTH_URL: Jitsi schickt nicht angemeldete Nutzer hierher."""
    room = clean_room(room)
    if not room:
        return redirect("/")
    meeting = db.scalar(select(Meeting).where(Meeting.room == room))
    if meeting is None:
        cfg = get_settings(db)
        meeting = Meeting(owner_id=user.id, title=room.replace("-", " ").title(), room=room,
                          transcribe=cfg.get("transcribe_default") == "1")
        db.add(meeting)
        db.commit()
    return redirect(join_url(user, room))


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
    cfg = get_settings(db)
    return render(request, "dashboard.html", user, meetings=meetings, recent=recent,
                  sm_ready=speechmind_ready(db, user),
                  transcribe_default=cfg.get("transcribe_default") == "1")


@app.post("/meetings", dependencies=[Depends(check_csrf)])
def create_meeting(request: Request, title: str = Form(...), transcribe: str = Form(""),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    title = title.strip()[:200] or "Besprechung"
    meeting = Meeting(owner_id=user.id, title=title, room=unique_room(db, room_slug(title)),
                      transcribe=transcribe == "1")
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
                     transcribe: str = Form(""), document_type: str = Form(""),
                     language: str = Form(""), user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    meeting = own_meeting(db, meeting_id, user)
    meeting.title = title.strip()[:200] or meeting.title
    meeting.transcribe = transcribe == "1"
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
                  summary=summary, has_video=has_video,
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
    transcribe_default: str = Form(""), allow_user_keys: str = Form(""),
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
    for key, value in (("transcribe_default", transcribe_default), ("allow_user_keys", allow_user_keys),
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

@app.get("/admin/users")
def admin_users(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.name)).all()
    return render(request, "admin_users.html", user, users=users,
                  new_password=request.session.pop("new_password", None))


@app.post("/admin/users", dependencies=[Depends(check_csrf)])
def admin_users_create(request: Request, name: str = Form(...), email: str = Form(...),
                       is_admin: str = Form(""), user: User = Depends(admin_user),
                       db: Session = Depends(get_db)):
    email = email.strip().lower()
    if "@" not in email:
        flash(request, "Bitte eine gültige E-Mail-Adresse angeben.", "error")
        return redirect("/admin/users")
    if db.scalar(select(User).where(User.email == email)):
        flash(request, f"{email} hat bereits ein Konto.", "error")
        return redirect("/admin/users")
    password = secrets.token_urlsafe(12)
    db.add(User(email=email, name=name.strip()[:200] or email, is_admin=is_admin == "1",
                password_hash=hash_password(password)))
    db.commit()
    request.session["new_password"] = {"email": email, "password": password}
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
    elif action == "reset_password":
        password = secrets.token_urlsafe(12)
        target.password_hash = hash_password(password)
        request.session["new_password"] = {"email": target.email, "password": password}
    elif action == "delete":
        for meeting in target.meetings:
            for rec in meeting.recordings:
                rec.meeting_id = None
            db.delete(meeting)
        db.delete(target)
        flash(request, f"{target.email} gelöscht.")
    db.commit()
    return redirect("/admin/users")


# --- Admin: alle Aufnahmen ----------------------------------------------------

@app.get("/admin/recordings")
def admin_recordings(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    recordings = db.scalars(select(Recording).order_by(Recording.created_at.desc()).limit(200)).all()
    return render(request, "admin_recordings.html", user, recordings=recordings)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    uid = request.session.get("uid")
    with SessionLocal() as db:
        user = db.get(User, uid) if uid else None
        response = render(request, "error.html", user, status=exc.status_code, detail=exc.detail)
    response.status_code = exc.status_code
    return response


__all__ = ["app", "STATUS_RECORDED"]
