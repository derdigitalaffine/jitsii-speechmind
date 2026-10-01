import os
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, event, inspect, select, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


try:
    LOCAL_TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")
except ZoneInfoNotFoundError:
    LOCAL_TZ = ZoneInfo("Europe/Berlin")


def to_local(dt: datetime | None) -> datetime | None:
    """Gespeichert wird UTC (naiv), angezeigt in der Zeitzone aus TZ."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


engine = create_engine(
    f"sqlite:///{settings.data_dir / 'portal.db'}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    # Web-Anfragen und Worker-Thread schreiben gleichzeitig: WAL + Wartezeit statt "database is locked"
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optional eigener SpeechMind-Zugang (überschreibt die globale Anbindung)
    sm_api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    sm_project_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # False, solange eine Einladung noch nicht angenommen wurde
    password_set: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # Einladungs- bzw. Zurücksetzen-Link (nur der Hash wird gespeichert)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    meetings: Mapped[list["Meeting"]] = relationship(back_populates="owner")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    room: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # Ungenutzt seit der Umstellung auf manuelle Transkription (Spalte bleibt aus Kompatibilität)
    transcribe: Mapped[bool] = mapped_column(Boolean, default=False)
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[User] = relationship(back_populates="meetings")
    recordings: Mapped[list["Recording"]] = relationship(
        back_populates="meeting", order_by="Recording.created_at.desc()"
    )


# Status-Abfolge einer Aufnahme
STATUS_NEW = "new"                  # Aufnahme gefunden, MP3 wird erzeugt
STATUS_RECORDED = "recorded"        # MP3 liegt vor, wartet auf manuellen Start der Transkription
STATUS_QUEUED = "queued"            # wartet auf Verarbeitung
STATUS_CONVERTING = "converting"    # Audiospur wird extrahiert
STATUS_UPLOADING = "uploading"      # Upload zu SpeechMind
STATUS_PROCESSING = "processing"    # SpeechMind transkribiert
STATUS_DONE = "done"
STATUS_FAILED = "failed"

ACTIVE_STATUSES = {STATUS_NEW, STATUS_QUEUED, STATUS_CONVERTING, STATUS_UPLOADING, STATUS_PROCESSING}


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    room: Mapped[str] = mapped_column(String(128), index=True)
    session_dir: Mapped[str] = mapped_column(String(512), unique=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    participants: Mapped[str] = mapped_column(Text, default="[]")
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=STATUS_RECORDED)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    sm_unique_obj_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sm_protocol_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sm_submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    transcript_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    meeting: Mapped[Meeting | None] = relationship(back_populates="recordings")

    @property
    def audio_size(self) -> int | None:
        """Größe der MP3 in Bytes, None wenn (noch) keine Datei vorhanden ist."""
        if not self.audio_path:
            return None
        try:
            return Path(self.audio_path).stat().st_size
        except OSError:
            return None


class Notification(Base):
    """Warteschlange der Benachrichtigungs-Engine (E-Mail)."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    to_addr: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


DEFAULT_SETTINGS = {
    "sm_api_url": "https://api-v2.speechmind.com/external/v2/graphql",
    "sm_api_key_enc": "",
    "sm_project_slug": "",
    "sm_language": "de-DE",
    "sm_document_type": "summary",
    "allow_user_keys": "0",
    "delete_after_upload": "0",
    "send_participants": "0",
    # Benachrichtigungen (E-Mail)
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_security": "starttls",  # starttls | ssl | none
    "smtp_user": "",
    "smtp_password_enc": "",
    "mail_from": "",
    "mail_from_name": "",
    "imap_host": "",
    "imap_port": "993",
    "imap_security": "ssl",       # ssl | starttls | none
    "imap_user": "",
    "imap_password_enc": "",
    "imap_sent_folder": "Sent",
    "imap_save_sent": "0",
    "notify_new_recording": "1",
    "notify_done": "1",
    "notify_failed": "1",
    # Zugang
    "allow_anonymous": "1",
    # Design & Branding (siehe branding.py)
    "ui_custom": "0",
    "ui_brand_name": "",
    "ui_product": "",
    "ui_primary": "#1f5fa8",
    "ui_navbar": "dark",
    "ui_theme": "auto",
    "ui_radius": "0.375rem",
    "ui_logo": "",
    "ui_logo_height": "32",
    "ui_show_name": "1",
    "ui_favicon": "",
    "ui_login_text": "",
    "ui_footer_text": "",
    "ui_imprint_url": "",
    "ui_privacy_url": "",
}

# Spalten, die in späteren Versionen dazukamen (SQLite: ALTER TABLE ADD COLUMN)
_NEW_COLUMNS = {
    "users": {
        "password_set": "BOOLEAN NOT NULL DEFAULT 1",
        "must_change_password": "BOOLEAN NOT NULL DEFAULT 0",
        "token_hash": "VARCHAR(64)",
        "token_expires_at": "DATETIME",
    },
    "recordings": {"audio_path": "VARCHAR(1024)"},
}


def _migrate() -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        for name, table, column in (("ix_recordings_status", "recordings", "status"),
                                    ("ix_recordings_meeting_id", "recordings", "meeting_id")):
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()
    with SessionLocal() as db:
        for key, value in DEFAULT_SETTINGS.items():
            if db.get(Setting, key) is None:
                db.add(Setting(key=key, value=value))
        db.commit()


def get_settings(db) -> dict[str, str]:
    rows = db.scalars(select(Setting)).all()
    values = dict(DEFAULT_SETTINGS)
    values.update({r.key: r.value for r in rows})
    return values


def set_setting(db, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
