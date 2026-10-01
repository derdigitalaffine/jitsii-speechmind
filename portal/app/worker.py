"""Hintergrundprozesse des Portals.

1. Watcher: findet abgeschlossene Jibri-Aufzeichnungen (Markierung .finalized)
   und legt sie in der Datenbank an.
2. Pipeline: extrahiert die Audiospur (ffmpeg), lädt sie zu SpeechMind hoch,
   startet das Protokoll und holt das fertige Transkript ab.
"""

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from .config import settings
from .db import (
    ACTIVE_STATUSES, SILENCE_DB, STATUS_CONVERTING, STATUS_NEW, STATUS_DONE, STATUS_FAILED, STATUS_PROCESSING,
    STATUS_QUEUED, STATUS_RECORDED, STATUS_UPLOADING, Meeting, Recording, SessionLocal,
    get_settings, to_local, utcnow,
)
from . import chat, notify
from .security import decrypt
from .speechmind import SpeechMindClient, SpeechMindError

log = logging.getLogger("portal.worker")

AUDIO_DIR = settings.data_dir / "audio"
_FILENAME_TS = re.compile(r"_\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")
_last_poll: dict[int, float] = {}
_wakeup = asyncio.Event()
_loop: asyncio.AbstractEventLoop | None = None


def wake() -> None:
    """Pipeline sofort anstoßen (z. B. nach Klick auf 'Transkribieren'). Thread-sicher."""
    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(_wakeup.set)


# --- Zugangsdaten ------------------------------------------------------------

def resolve_credentials(db, meeting: Meeting | None) -> tuple[str, str, str]:
    """Liefert (api_url, api_key, project_slug) für eine Aufnahme."""
    cfg = get_settings(db)
    api_key = decrypt(cfg.get("sm_api_key_enc"))
    project = cfg.get("sm_project_slug", "")
    if meeting and cfg.get("allow_user_keys") == "1":
        owner = meeting.owner
        own_key = decrypt(owner.sm_api_key_enc)
        if own_key:
            api_key = own_key
            project = owner.sm_project_slug or project
    return cfg["sm_api_url"], api_key, project


# --- Watcher -----------------------------------------------------------------

def _room_from_metadata(session_dir: Path, video: Path | None) -> tuple[str, list]:
    room, participants = "", []
    meta_file = session_dir / "metadata.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            url = meta.get("meeting_url") or meta.get("meetingUrl") or ""
            room = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
            participants = meta.get("participants") or []
        except (ValueError, OSError) as exc:
            log.warning("metadata.json in %s nicht lesbar: %s", session_dir, exc)
    if not room and video:
        room = _FILENAME_TS.sub("", video.stem)
    return room.lower(), participants


def _participant_names(participants: list) -> list[str]:
    names = []
    for p in participants:
        if not isinstance(p, dict):
            continue
        user = p.get("user") if isinstance(p.get("user"), dict) else {}
        name = p.get("name") or p.get("displayName") or user.get("name") or ""
        name = str(name).strip()
        if name and "jibri" not in name.lower() and "recorder" not in name.lower() and name not in names:
            names.append(name)
    return names


def scan_recordings() -> int:
    root = settings.recordings_dir
    if not root.exists():
        return 0
    found = 0
    with SessionLocal() as db:
        known = set(db.scalars(select(Recording.session_dir)).all())
        for session_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if str(session_dir) in known or not (session_dir / ".finalized").exists():
                continue
            videos = sorted(session_dir.glob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
            video = videos[0] if videos else None
            room, participants = _room_from_metadata(session_dir, video)
            meeting = db.scalar(select(Meeting).where(Meeting.room == room)) if room else None
            if meeting is None:
                # Aufnahmen gibt es nur in Portal-Räumen (Prosody lässt sie anderswo nicht zu);
                # taucht trotzdem eine auf, wird sie nicht aufbewahrt
                log.warning("Aufnahme außerhalb eines Portal-Raums (%s) verworfen: %s", room, session_dir.name)
                shutil.rmtree(session_dir, ignore_errors=True)
                continue

            # Die Transkription wird nie automatisch gestartet: erst die MP3 erzeugen,
            # dann entscheidet ein Mensch in der GUI.
            status = STATUS_NEW
            error = None
            if not video:
                status, error = STATUS_FAILED, "Keine MP4-Datei im Aufnahmeordner gefunden."

            db.add(Recording(
                meeting_id=meeting.id if meeting else None,
                room=room or session_dir.name,
                session_dir=str(session_dir),
                video_path=str(video) if video else None,
                participants=json.dumps(_participant_names(participants), ensure_ascii=False),
                status=status,
                error=error,
            ))
            found += 1
            log.info("Neue Aufnahme: %s (Raum %s, Status %s)", session_dir.name, room, status)
        db.commit()
    if found:
        wake()
    return found


# --- Pipeline ----------------------------------------------------------------

async def _run(*cmd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace")


NO_SOUND_CAUSE = ("Entweder hat in der Konferenz niemand hörbar gesprochen (Mikrofon stumm?), oder Jibri erfasst "
                  "den Ton nicht. Diagnose auf dem Server: ./scripts/diagnose-recording.sh "
                  "(siehe Admin-Handbuch, Abschnitt „Aufnahme ohne Ton“).")
NO_SOUND_HINT = "Die Aufnahme enthält keinen hörbaren Ton. " + NO_SOUND_CAUSE
_VOLUME = re.compile(r"max_volume:\s*(-?[\d.]+|-inf)\s*dB")


async def measure_max_db(audio: Path) -> float | None:
    """Lauteste Stelle in dB (volumedetect). Gibt -91 zurück, wenn keine Lautstärke ermittelbar ist."""
    code, out = await _run("ffmpeg", "-nostdin", "-i", str(audio), "-af", "volumedetect",
                           "-vn", "-sn", "-dn", "-f", "null", "-")
    if code != 0:
        return None
    match = _VOLUME.search(out)
    if not match:
        return -91.0
    return -91.0 if match.group(1) == "-inf" else float(match.group(1))


async def extract_audio(video: Path, target: Path) -> tuple[int | None, float | None]:
    """Erzeugt die MP3 und liefert (Dauer in Sekunden, lauteste Stelle in dB)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    code, out = await _run(
        "ffmpeg", "-nostdin", "-y", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", str(target),
    )
    if code != 0:
        if "does not contain any stream" in out or "Output file #0 does not contain" in out:
            raise RuntimeError("Das Video enthält keine Tonspur. " + NO_SOUND_CAUSE)
        raise RuntimeError("ffmpeg konnte die Audiospur nicht extrahieren: " + out[-400:])
    if not target.exists() or target.stat().st_size < 1024:
        raise RuntimeError("Die erzeugte MP3 ist leer. " + NO_SOUND_HINT)
    code, out = await _run(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(target),
    )
    try:
        duration = int(float(out.strip()))
    except ValueError:
        duration = None
    return duration, await measure_max_db(target)


def _set(rec_id: int, notify_event: str | None = None, **fields) -> None:
    with SessionLocal() as db:
        rec = db.get(Recording, rec_id)
        if rec is None:
            return
        for k, v in fields.items():
            setattr(rec, k, v)
        if notify_event:
            notify.notify_recording(db, rec, notify_event)
        db.commit()


async def convert_recording(rec_id: int) -> None:
    """Neue Aufnahme: MP3 erzeugen und zum Download bereitstellen."""
    with SessionLocal() as db:
        rec = db.get(Recording, rec_id)
        if rec is None or rec.status != STATUS_NEW:
            return
        video = Path(rec.video_path) if rec.video_path else None
        room = rec.room
    try:
        if not video or not video.exists():
            raise RuntimeError("Die Videodatei der Aufnahme existiert nicht mehr.")
        audio = AUDIO_DIR / f"recording-{rec_id}.mp3"
        duration, max_db = await extract_audio(video, audio)
        messages = chat.for_video(room, video, duration)
        if messages:
            _set(rec_id, chat_json=json.dumps(messages, ensure_ascii=False))
            log.info("Chatprotokoll mit %d Nachricht(en) an Aufnahme %s gehängt", len(messages), rec_id)
        polls = chat.polls_for_video(room, video, duration)
        if polls:
            _set(rec_id, polls_json=json.dumps(polls, ensure_ascii=False))
            log.info("%d Umfrage(n) an Aufnahme %s gehängt", len(polls), rec_id)
        silent = max_db is not None and max_db < SILENCE_DB
        if silent:
            log.warning("Aufnahme %s ist stumm (lauteste Stelle %.1f dB)", rec_id, max_db)
        _set(rec_id, "silent" if silent else "new_recording", status=STATUS_RECORDED,
             error=NO_SOUND_HINT if silent else None,
             audio_path=str(audio), duration_seconds=duration, audio_max_db=max_db)
        log.info("MP3 für Aufnahme %s erzeugt", rec_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("MP3-Erzeugung für Aufnahme %s fehlgeschlagen", rec_id)
        _set(rec_id, "failed", status=STATUS_FAILED, error=str(exc))


def _speaker_list(names: list[str]) -> list[dict]:
    speakers = []
    for name in names:
        parts = name.split()
        given = " ".join(parts[:-1]) if len(parts) > 1 else name
        family = parts[-1] if len(parts) > 1 else ""
        speakers.append({
            "gender": "", "givenName": given, "familyName": family,
            "party": "", "preTitle": "", "postTitle": "", "systemId": "",
        })
    return speakers


async def submit_recording(rec_id: int) -> None:
    with SessionLocal() as db:
        rec = db.get(Recording, rec_id)
        if rec is None or rec.status not in (STATUS_QUEUED, STATUS_CONVERTING, STATUS_UPLOADING):
            return
        meeting = rec.meeting
        cfg = get_settings(db)
        api_url, api_key, project = resolve_credentials(db, meeting)
        video = Path(rec.video_path) if rec.video_path else None
        audio_path = rec.audio_path
        title = meeting.title if meeting else rec.room
        language = (meeting.language if meeting and meeting.language else cfg["sm_language"])
        doc_type = (meeting.document_type if meeting and meeting.document_type else cfg["sm_document_type"])
        names = json.loads(rec.participants or "[]") if cfg.get("send_participants") == "1" else []
        rec.attempts += 1
        created = to_local(rec.created_at)
        db.commit()

    try:
        if not api_key:
            raise SpeechMindError("Keine SpeechMind-Anbindung eingerichtet. Ein Admin muss im Bereich "
                                  "„SpeechMind“ einen API-Key hinterlegen.")
        if not project:
            raise SpeechMindError("Kein SpeechMind-Projekt ausgewählt. Ein Admin wählt es im Bereich „SpeechMind“ aus.")
        have_audio = bool(audio_path and Path(audio_path).exists())
        if not have_audio and (not video or not video.exists()):
            raise RuntimeError("Weder MP3 noch Videodatei der Aufnahme sind noch vorhanden.")

        audio = Path(audio_path) if audio_path else None
        if audio and audio.exists():
            duration = None
        else:
            _set(rec_id, status=STATUS_CONVERTING, error=None)
            audio = AUDIO_DIR / f"recording-{rec_id}.mp3"
            duration, max_db = await extract_audio(video, audio)
            _set(rec_id, audio_path=str(audio), audio_max_db=max_db)

        _set(rec_id, status=STATUS_UPLOADING, **({"duration_seconds": duration} if duration else {}))
        unique = f"jitsi-{rec_id}-{uuid.uuid4().hex[:12]}.mp3"
        client = SpeechMindClient(api_url, api_key)
        await client.upload_file(unique, audio)
        stamp = created.strftime("%d.%m.%Y %H:%M")
        slug = await client.init_protocol(
            name=f"{title} – {stamp}",
            date=created.strftime("%Y-%m-%d"),
            language=language,
            document_type=doc_type,
            project_slug=project,
            unique_obj_name=unique,
            speakers=_speaker_list(names),
        )
        _set(rec_id, status=STATUS_PROCESSING, sm_unique_obj_name=unique,
             sm_protocol_slug=slug, sm_submitted_at=utcnow())
        log.info("Aufnahme %s an SpeechMind übergeben (Protokoll %s)", rec_id, slug)
    except Exception as exc:  # noqa: BLE001 – Fehler landet sichtbar in der GUI
        log.exception("Aufnahme %s fehlgeschlagen", rec_id)
        _set(rec_id, "failed", status=STATUS_FAILED, error=str(exc))


async def poll_recording(rec_id: int) -> None:
    with SessionLocal() as db:
        rec = db.get(Recording, rec_id)
        if rec is None or rec.status != STATUS_PROCESSING or not rec.sm_protocol_slug:
            return
        api_url, api_key, _ = resolve_credentials(db, rec.meeting)
        slug = rec.sm_protocol_slug
        submitted = rec.sm_submitted_at or rec.updated_at
        delete_local = get_settings(db).get("delete_after_upload") == "1"
        session_dir = Path(rec.session_dir)

    try:
        client = SpeechMindClient(api_url, api_key)
        results = await client.get_results(slug)
        if not results.get("creationDone"):
            if utcnow() - submitted > timedelta(hours=settings.poll_timeout_hours):
                _set(rec_id, "failed", status=STATUS_FAILED,
                     error=f"SpeechMind hat nach {settings.poll_timeout_hours} Stunden kein Ergebnis geliefert.")
            return
        transcript = await client.get_transcript(slug)
        summary = {
            "agenda": results.get("agendaItemList") or [],
            "tasks": results.get("taskItemList") or [],
        }
        fields = dict(
            status=STATUS_DONE, error=None,
            transcript_json=json.dumps(transcript, ensure_ascii=False),
            summary_json=json.dumps(summary, ensure_ascii=False),
        )
        if delete_local and session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
            fields["video_path"] = None
        _set(rec_id, "done", **fields)
        log.info("Transkript für Aufnahme %s abgeholt (%d Segmente)", rec_id, len(transcript))
    except SpeechMindError as exc:
        # Vorübergehende Fehler beim Pollen nicht sofort als Abbruch werten
        log.warning("Abfrage für Aufnahme %s fehlgeschlagen: %s", rec_id, exc)
        _set(rec_id, error=f"Letzte Abfrage fehlgeschlagen: {exc}")


async def pipeline_tick() -> None:
    with SessionLocal() as db:
        new = db.scalars(select(Recording.id).where(Recording.status == STATUS_NEW).order_by(Recording.id)).all()
        queued = db.scalars(
            select(Recording.id).where(Recording.status == STATUS_QUEUED).order_by(Recording.id)
        ).all()
        processing = db.scalars(
            select(Recording.id).where(Recording.status == STATUS_PROCESSING)
        ).all()

    for rec_id in new:
        await convert_recording(rec_id)

    for rec_id in queued:
        await submit_recording(rec_id)

    now = time.monotonic()
    for rec_id in processing:
        if now - _last_poll.get(rec_id, 0) >= settings.poll_interval_seconds:
            _last_poll[rec_id] = now
            await poll_recording(rec_id)


def reset_interrupted() -> None:
    """Nach einem Neustart abgebrochene Schritte erneut einreihen."""
    with SessionLocal() as db:
        for rec in db.scalars(select(Recording).where(
                Recording.status.in_([STATUS_CONVERTING, STATUS_UPLOADING]))):
            rec.status = STATUS_QUEUED
        db.commit()


RSVP_INTERVAL_SECONDS = 120
_last_rsvp = [0.0]
_last_chat_prune = [0.0]


def _poll_rsvp() -> None:
    from . import rsvp
    with SessionLocal() as db:
        enabled = get_settings(db).get("imap_rsvp") == "1"
    if enabled:
        rsvp.poll_safely()


async def run_forever() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    reset_interrupted()
    log.info("Worker gestartet – überwache %s", settings.recordings_dir)
    while True:
        try:
            await asyncio.to_thread(scan_recordings)
            await pipeline_tick()
            await asyncio.to_thread(notify.process_queue)
            if time.monotonic() - _last_rsvp[0] >= RSVP_INTERVAL_SECONDS:
                _last_rsvp[0] = time.monotonic()
                await asyncio.to_thread(_poll_rsvp)
            await asyncio.to_thread(notify.process_queue)  # Hinweise zu neuen Antworten gleich verschicken
            if time.monotonic() - _last_chat_prune[0] >= 3600:
                _last_chat_prune[0] = time.monotonic()
                await asyncio.to_thread(chat.prune)
        except Exception:  # noqa: BLE001
            log.exception("Fehler im Worker-Durchlauf")
        _wakeup.clear()
        try:
            await asyncio.wait_for(_wakeup.wait(), timeout=settings.watch_interval_seconds)
        except asyncio.TimeoutError:
            pass


__all__ = ["run_forever", "wake", "resolve_credentials", "ACTIVE_STATUSES", "STATUS_RECORDED"]
