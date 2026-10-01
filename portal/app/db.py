import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, select,
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
    transcribe: Mapped[bool] = mapped_column(Boolean, default=True)
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[User] = relationship(back_populates="meetings")
    recordings: Mapped[list["Recording"]] = relationship(
        back_populates="meeting", order_by="Recording.created_at.desc()"
    )


# Status-Abfolge einer Aufnahme
STATUS_RECORDED = "recorded"        # liegt vor, Transkription nicht aktiv
STATUS_QUEUED = "queued"            # wartet auf Verarbeitung
STATUS_CONVERTING = "converting"    # Audiospur wird extrahiert
STATUS_UPLOADING = "uploading"      # Upload zu SpeechMind
STATUS_PROCESSING = "processing"    # SpeechMind transkribiert
STATUS_DONE = "done"
STATUS_FAILED = "failed"

ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_CONVERTING, STATUS_UPLOADING, STATUS_PROCESSING}


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    room: Mapped[str] = mapped_column(String(128), index=True)
    session_dir: Mapped[str] = mapped_column(String(512), unique=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
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


DEFAULT_SETTINGS = {
    "sm_api_url": "https://api-v2.speechmind.com/external/v2/graphql",
    "sm_api_key_enc": "",
    "sm_project_slug": "",
    "sm_language": "de-DE",
    "sm_document_type": "summary",
    "transcribe_default": "1",
    "allow_user_keys": "0",
    "delete_after_upload": "0",
    "send_participants": "0",
}


def init_db() -> None:
    Base.metadata.create_all(engine)
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
