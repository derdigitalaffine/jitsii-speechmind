import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, inspect, select, text,
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
    # Freigeschaltete Bereiche, kommagetrennt (siehe PERMISSIONS). Admins dürfen immer alles.
    permissions: Mapped[str] = mapped_column(String(255), default="video")
    # Zwei-Faktor-Anmeldung (siehe twofa.py)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mfa_email: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_code_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    meetings: Mapped[list["Meeting"]] = relationship(back_populates="owner")
    groups: Mapped[list["Group"]] = relationship(secondary="group_members", back_populates="members",
                                                 order_by="Group.name")

    @property
    def perms(self) -> set[str]:
        return {p for p in (self.permissions or "").split(",") if p in PERMISSIONS}

    def can(self, perm: str) -> bool:
        return bool(self.is_admin or perm in self.perms)


# Bereiche, die einzeln pro Benutzer freigeschaltet werden
PERMISSIONS = {
    "video": ("Videokonferenzen", "fa-video", "Meetings anlegen, planen, moderieren und aufnehmen"),
    "shortlinks": ("Kurzlinks", "fa-link", "Kurzlinks anlegen und auswerten"),
    "forms": ("Formulare", "fa-clipboard-list", "Formulare erstellen, verteilen und auswerten"),
    "polls": ("Terminumfragen", "fa-calendar-check", "Terminumfragen (wie Doodle) erstellen und auswerten"),
    "bookings": ("Terminbuchung", "fa-calendar-plus", "Buchungsseiten mit freien Zeitfenstern anbieten (z. B. Vorstellungsgespräche)"),
    "users": ("Benutzerverwaltung", "fa-users-gear", "Benutzer und Gruppen anlegen, bearbeiten und löschen"),
}


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Group(Base):
    """Benutzergruppe, z. B. zum gemeinsamen Einladen zu Formularen."""
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    members: Mapped[list[User]] = relationship(secondary="group_members", back_populates="groups",
                                               order_by="User.name")


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
    # Geplante Besprechung (Kalendereinladung); starts_at in UTC
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ics_uid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ics_sequence: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Allgemeiner Gastlink (/g/<token>): Gäste geben ihren Namen ein und kommen ohne Konto hinein
    guest_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    owner: Mapped[User] = relationship(back_populates="meetings")
    recordings: Mapped[list["Recording"]] = relationship(
        back_populates="meeting", order_by="Recording.created_at.desc()"
    )
    invitees: Mapped[list["Invitee"]] = relationship(
        back_populates="meeting", order_by="Invitee.email", cascade="all, delete-orphan"
    )

    @property
    def ends_at(self) -> datetime | None:
        if self.starts_at is None:
            return None
        return self.starts_at + timedelta(minutes=self.duration_minutes or 60)


class Invitee(Base):
    """Eingeladene Person einer geplanten Besprechung (Portal-Benutzer oder externer Gast)."""
    __tablename__ = "invitees"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), default="")
    invited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Persönlicher Einwahllink (/join/<token>) aus der Einladung
    join_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Antwort auf die Einladung (aus dem IMAP-Postfach): accepted | declined | tentative | delegated | counter
    rsvp_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rsvp_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rsvp_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="invitees")


# Status-Abfolge einer Aufnahme
STATUS_NEW = "new"                  # Aufnahme gefunden, MP3 wird erzeugt
STATUS_RECORDED = "recorded"        # MP3 liegt vor, wartet auf manuellen Start der Transkription
STATUS_QUEUED = "queued"            # wartet auf Verarbeitung
STATUS_CONVERTING = "converting"    # Audiospur wird extrahiert
STATUS_UPLOADING = "uploading"      # Upload zu SpeechMind
STATUS_PROCESSING = "processing"    # SpeechMind transkribiert
STATUS_DONE = "done"
STATUS_REMOTE = "remote"            # lokal gelöscht, Protokoll bei SpeechMind wieder abrufbar
STATUS_FAILED = "failed"

SILENCE_DB = -50.0  # lauteste Stelle darunter = kein hörbarer Ton

ACTIVE_STATUSES = {STATUS_NEW, STATUS_QUEUED, STATUS_CONVERTING, STATUS_UPLOADING, STATUS_PROCESSING}


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    room: Mapped[str] = mapped_column(String(128), index=True)
    session_dir: Mapped[str] = mapped_column(String(512), unique=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Lauteste Stelle der MP3 in dB (0 = Vollaussteuerung, -91 = digitale Stille); None = nicht gemessen
    audio_max_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Zeitpunkt, zu dem Video und MP3 gelöscht wurden (Transkript bzw. SpeechMind-Verweis bleiben)
    media_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Chatprotokoll aus der Konferenz während der Aufnahme: JSON-Liste [{time, name, text}]
    chat_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Umfragen aus der Konferenz während der Aufnahme: JSON-Liste (siehe chat.collect_polls)
    polls_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def polls(self) -> list[dict]:
        import json as _json
        try:
            return _json.loads(self.polls_json) if self.polls_json else []
        except ValueError:
            return []

    @property
    def chat(self) -> list[dict]:
        import json as _json
        try:
            return _json.loads(self.chat_json) if self.chat_json else []
        except ValueError:
            return []
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
    def audio_silent(self) -> bool:
        """True, wenn die MP3 gemessen wurde und praktisch keinen Ton enthält."""
        return self.audio_max_db is not None and self.audio_max_db < SILENCE_DB

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
    reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # JSON-Liste von Anhängen: {"filename", "content", "calendar_method"?}
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ShortLink(Base):
    """Kurzlink (wie Shlink): /s/<code> bzw. Kurz-Domain leitet auf target_url weiter."""
    __tablename__ = "short_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # immer klein geschrieben
    target_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(255), default="")
    tags: Mapped[str] = mapped_column(String(500), default="")  # kommagetrennt
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    max_visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forward_query: Mapped[bool] = mapped_column(Boolean, default=True)
    redirect_code: Mapped[int] = mapped_column(Integer, default=302)
    visit_count: Mapped[int] = mapped_column(Integer, default=0)   # ohne erkannte Bots
    bot_count: Mapped[int] = mapped_column(Integer, default=0)
    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()
    visits: Mapped[list["ShortVisit"]] = relationship(back_populates="link", cascade="all, delete-orphan",
                                                      passive_deletes=True)

    @property
    def tag_list(self) -> list[str]:
        return [t for t in (self.tags or "").split(",") if t]


class ShortVisit(Base):
    """Ein Aufruf eines Kurzlinks. Datensparsam: keine IP-Adresse, User-Agent nur ausgewertet."""
    __tablename__ = "short_visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("short_links.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    referer_host: Mapped[str] = mapped_column(String(255), default="")
    browser: Mapped[str] = mapped_column(String(40), default="")
    os: Mapped[str] = mapped_column(String(40), default="")
    device: Mapped[str] = mapped_column(String(20), default="")
    bot: Mapped[bool] = mapped_column(Boolean, default=False)

    link: Mapped[ShortLink] = relationship(back_populates="visits")


class Form(Base):
    """Formular aus dem Baukasten. Aufbau als JSON-Liste von Elementen (siehe forms.py)."""
    __tablename__ = "forms"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    schema_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Öffentlicher Link /f/<token>; None = ausgeschaltet
    public_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    multiple: Mapped[bool] = mapped_column(Boolean, default=False)
    submit_message: Mapped[str] = mapped_column(Text, default="")
    confirm_mail: Mapped[bool] = mapped_column(Boolean, default=False)
    # Benachrichtigung bei neuen Antworten
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_to: Mapped[str] = mapped_column(Text, default="")        # weitere Adressen
    notify_answers: Mapped[bool] = mapped_column(Boolean, default=True)  # Antworten im Mailtext
    notify_json: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_csv: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_scope: Mapped[str] = mapped_column(String(10), default="single")  # single | all
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()
    invites: Mapped[list["FormInvite"]] = relationship(back_populates="form", cascade="all, delete-orphan",
                                                       order_by="FormInvite.email", passive_deletes=True)
    responses: Mapped[list["FormResponse"]] = relationship(back_populates="form", cascade="all, delete-orphan",
                                                           order_by="FormResponse.id", passive_deletes=True)
    shares: Mapped[list["FormShare"]] = relationship(back_populates="form", cascade="all, delete-orphan",
                                                     passive_deletes=True)


class FormShare(Base):
    """Freigabe eines Formulars im Portal für eine Person oder Gruppe.

    level: 1 = Ergebnisse einsehen, 2 = zusätzlich Teilnehmende einladen,
           3 = zusätzlich Formular bearbeiten und löschen
    """
    __tablename__ = "form_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True,
                                                 index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    form: Mapped["Form"] = relationship(back_populates="shares")
    user: Mapped[User | None] = relationship()
    group: Mapped[Group | None] = relationship()


class FormInvite(Base):
    """Persönliche Einladung zu einem Formular (Benutzer, Gruppenmitglied oder Gast per Mail)."""
    __tablename__ = "form_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    via: Mapped[str] = mapped_column(String(160), default="")  # z. B. Gruppenname
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    form: Mapped[Form] = relationship(back_populates="invites")


class FormResponse(Base):
    __tablename__ = "form_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(20), default="public")  # public | invite | user
    answers_json: Mapped[str] = mapped_column(Text, default="{}")

    form: Mapped[Form] = relationship(back_populates="responses")

    @property
    def answers(self) -> dict:
        import json as _json
        try:
            return _json.loads(self.answers_json or "{}")
        except ValueError:
            return {}


class Poll(Base):
    """Terminumfrage (wie Doodle): Teilnehmende stimmen je Terminvorschlag mit Ja, Wenn nötig oder Nein."""
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    public_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    allow_maybe: Mapped[bool] = mapped_column(Boolean, default=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)       # Teilnehmende sehen nur ihre eigenen Antworten
    single_choice: Mapped[bool] = mapped_column(Boolean, default=False)  # nur ein Termin wählbar
    max_per_option: Mapped[int | None] = mapped_column(Integer, nullable=True)  # z. B. Sprechstunden
    require_email: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_votes: Mapped[bool] = mapped_column(Boolean, default=True)
    final_option_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()
    options: Mapped[list["PollOption"]] = relationship(back_populates="poll", cascade="all, delete-orphan",
                                                       order_by="PollOption.starts_at", passive_deletes=True)
    participants: Mapped[list["PollParticipant"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan", order_by="PollParticipant.id", passive_deletes=True)

    @property
    def final_option(self) -> "PollOption | None":
        return next((o for o in self.options if o.id == self.final_option_id), None)


class PollOption(Base):
    """Terminvorschlag: Tag (ganztägig) oder Beginn mit optionalem Ende, in UTC."""
    __tablename__ = "poll_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(120), default="")

    poll: Mapped[Poll] = relationship(back_populates="options")


class PollParticipant(Base):
    """Eine Person mit ihren Antworten. Über edit_token (persönlicher Link) änderbar."""
    __tablename__ = "poll_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    edit_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")  # {option_id: "yes" | "maybe" | "no"}
    comment: Mapped[str] = mapped_column(Text, default="")
    invited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    poll: Mapped[Poll] = relationship(back_populates="participants")

    @property
    def answers(self) -> dict[str, str]:
        import json as _json
        try:
            data = _json.loads(self.answers_json or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}


class BookingPage(Base):
    """Terminbuchung: In festgelegten Zeitbereichen buchen Gäste selbst freie Zeitfenster (Slots)."""
    __tablename__ = "booking_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30)
    pause_minutes: Mapped[int] = mapped_column(Integer, default=0)       # Puffer nach jedem Termin
    capacity: Mapped[int] = mapped_column(Integer, default=1)            # Personen je Zeitfenster
    min_notice_hours: Mapped[int] = mapped_column(Integer, default=12)   # frühestens so viele Stunden vorher buchbar
    cancel_hours: Mapped[int] = mapped_column(Integer, default=24)       # bis so viele Stunden vorher selbst absagbar
    max_per_person: Mapped[int] = mapped_column(Integer, default=1)      # aktive Buchungen je E-Mail-Adresse
    invite_only: Mapped[bool] = mapped_column(Boolean, default=False)    # nur mit persönlichem Einladungslink
    ask_phone: Mapped[bool] = mapped_column(Boolean, default=False)
    online: Mapped[bool] = mapped_column(Boolean, default=False)         # je Buchung eine Videokonferenz
    notify_owner: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_hours: Mapped[int] = mapped_column(Integer, default=24)     # 0 = keine Erinnerung
    confirm_text: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Geheimer Link zum Abonnieren der Buchungen im eigenen Kalender (None = aus)
    feed_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()
    windows: Mapped[list["BookingWindow"]] = relationship(back_populates="page", cascade="all, delete-orphan",
                                                          order_by="BookingWindow.starts_at", passive_deletes=True)
    bookings: Mapped[list["Booking"]] = relationship(back_populates="page", cascade="all, delete-orphan",
                                                     order_by="Booking.starts_at", passive_deletes=True)
    invites: Mapped[list["BookingInvite"]] = relationship(back_populates="page", cascade="all, delete-orphan",
                                                          order_by="BookingInvite.email", passive_deletes=True)


class BookingWindow(Base):
    """Zeitbereich, in dem gebucht werden kann (UTC). Wird in Zeitfenster der Slot-Dauer geteilt."""
    __tablename__ = "booking_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("booking_pages.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)

    page: Mapped[BookingPage] = relationship(back_populates="windows")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("booking_pages.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(60), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    invite_id: Mapped[int | None] = mapped_column(ForeignKey("booking_invites.id", ondelete="SET NULL"),
                                                  nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)   # Verwalten / Absagen
    status: Mapped[str] = mapped_column(String(16), default="booked")         # booked | cancelled
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[str] = mapped_column(String(16), default="")          # guest | owner
    cancel_reason: Mapped[str] = mapped_column(Text, default="")
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    page: Mapped[BookingPage] = relationship(back_populates="bookings")


class BookingInvite(Base):
    """Persönliche Einladung zum Buchen (z. B. Bewerber:innen), mit vorausgefülltem Namen."""
    __tablename__ = "booking_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("booking_pages.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="")
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    page: Mapped[BookingPage] = relationship(back_populates="invites")


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
    # Zu-/Absagen auf Besprechungseinladungen per IMAP auswerten
    "imap_rsvp": "0",
    "imap_rsvp_folder": "INBOX",
    "imap_rsvp_move": "",
    "notify_rsvp": "1",
    "notify_new_recording": "1",
    "notify_done": "1",
    "notify_failed": "1",
    "ui_jitsi": "1",              # Design auch in der Konferenzoberfläche (Jitsi) anwenden
    # HTTPS / Reverse Proxy
    "tls_mode": "selfsigned",     # selfsigned | letsencrypt
    "tls_email": "",
    "tls_staging": "0",
    # Zugang
    "allow_anonymous": "1",
    # Zwei-Faktor-Anmeldung
    "mfa_email_allowed": "1",
    "mfa_totp_allowed": "1",
    "mfa_required": "off",        # off | admins | all
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
    # Zusatzmodule (komplett abschaltbar unter Verwaltung › Module)
    "module_shortlinks": "1",
    "module_forms": "1",
    "module_polls": "1",
    "module_bookings": "1",
    # Kurzlinks
    "short_domain": "",           # optional eigene Kurz-Domain, z. B. kurz.example.de
    "short_fallback_url": "",     # Ziel für unbekannte Kurzlinks und die Startseite der Kurz-Domain
    "short_code_length": "6",
}

# Spalten, die in späteren Versionen dazukamen (SQLite: ALTER TABLE ADD COLUMN)
_NEW_COLUMNS = {
    "users": {
        "password_set": "BOOLEAN NOT NULL DEFAULT 1",
        "must_change_password": "BOOLEAN NOT NULL DEFAULT 0",
        "token_hash": "VARCHAR(64)",
        "token_expires_at": "DATETIME",
        "permissions": "VARCHAR(255) NOT NULL DEFAULT 'video'",
        "totp_secret_enc": "TEXT", "totp_enabled": "BOOLEAN NOT NULL DEFAULT 0", "totp_last_step": "INTEGER",
        "mfa_email": "BOOLEAN NOT NULL DEFAULT 0", "recovery_json": "TEXT", "email_code_hash": "VARCHAR(64)",
        "email_code_expires": "DATETIME",
    },
    "recordings": {"audio_path": "VARCHAR(1024)", "audio_max_db": "FLOAT", "media_deleted_at": "DATETIME",
                   "chat_json": "TEXT", "polls_json": "TEXT"},
    "meetings": {"starts_at": "DATETIME", "duration_minutes": "INTEGER", "description": "TEXT",
                 "ics_uid": "VARCHAR(255)", "ics_sequence": "INTEGER NOT NULL DEFAULT 0",
                 "cancelled_at": "DATETIME", "guest_token": "VARCHAR(64)"},
    "notifications": {"reply_to": "VARCHAR(255)", "attachments_json": "TEXT"},
    "invitees": {"rsvp_status": "VARCHAR(16)", "rsvp_at": "DATETIME", "rsvp_comment": "TEXT",
                 "join_token": "VARCHAR(64)"},
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
