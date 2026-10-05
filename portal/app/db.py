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
    dashboard_json: Mapped[str] = mapped_column(Text, default="")   # Startseite: Reihenfolge/ausgeblendete Kacheln
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
    "laws": ("Rechtstexte", "fa-scale-balanced", "Gesetze, Satzungen und Verordnungen einstellen, gliedern und veröffentlichen"),
    "formblocks": ("Formularbausteine", "fa-cubes", "Datenblöcke (z. B. Antragsteller:in, Hund) in der zentralen Bibliothek anlegen und ändern"),
    "dms_admin": ("Aktenplan verwalten", "fa-sitemap", "Ablagebereiche (DMS) anlegen, Lese-/Schreibrechte und Löschfristen festlegen, abgelaufene Vorgänge löschen"),
    "processes": ("Prozesse", "fa-diagram-project", "Bearbeitungsprozesse für Online-Anträge im Prozesseditor gestalten und veröffentlichen"),
    "app_create": ("Online-Anträge einrichten", "fa-file-signature", "Formulare zu Online-Anträgen machen (Aktenzeichen, Frist, Zuständigkeit) und wieder zurückstellen"),
    "maps_admin": ("Kartenlayer & Geocoding", "fa-layer-group", "Kartenlayer, Kartenstandard und die Adresssuche (Nominatim) einrichten"),
    "maps": ("Karten", "fa-map-location-dot", "Im Kartenbrowser eigene WMS/WFS-Layer hinzufügen, Karten speichern und teilen"),
    "payments": ("Zahlungen", "fa-euro-sign", "Zahlungsübersicht und Export, Zahlungen als bezahlt markieren, erstatten und stornieren"),
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


class UserSession(Base):
    """Angemeldete Sitzung. Das Cookie trägt nur die zufällige Kennung, hier liegt deren Hash."""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    sid_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    last_path: Mapped[str] = mapped_column(String(255), default="")
    method: Mapped[str] = mapped_column(String(16), default="password")   # password | 2fa | invite

    user: Mapped[User] = relationship()


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
    review: Mapped[bool] = mapped_column(Boolean, default=True)    # Übersicht vor dem Absenden
    # Online-Antrag (siehe applications.py): Aktenzeichen, Status, Zuständigkeit, PDF, Antragskatalog
    kind: Mapped[str] = mapped_column(String(12), default="survey")          # survey | application
    app_prefix: Mapped[str] = mapped_column(String(12), default="")          # z. B. GEW → GEW-2026-00042
    app_category: Mapped[str] = mapped_column(String(100), default="")
    app_info: Mapped[str] = mapped_column(Text, default="")                  # Unterlagen, Hinweise
    app_fee: Mapped[str] = mapped_column(String(255), default="")            # Gebühr
    app_duration: Mapped[str] = mapped_column(String(255), default="")       # übliche Bearbeitungsdauer
    app_assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    app_group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    app_mailbox: Mapped[str] = mapped_column(String(255), default="")        # Funktionspostfach
    app_routing_json: Mapped[str] = mapped_column(Text, default="[]")        # Regeln je Antwort
    app_deadline_days: Mapped[int] = mapped_column(Integer, default=14)
    app_catalog: Mapped[bool] = mapped_column(Boolean, default=True)
    app_pdf: Mapped[bool] = mapped_column(Boolean, default=True)
    app_seq_year: Mapped[int] = mapped_column(Integer, default=0)
    app_seq: Mapped[int] = mapped_column(Integer, default=0)
    process_id: Mapped[int | None] = mapped_column(ForeignKey("processes.id", ondelete="SET NULL"), nullable=True)
    dms_area_id: Mapped[int | None] = mapped_column(ForeignKey("dms_areas.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    app_assignee: Mapped[User | None] = relationship(foreign_keys=[app_assignee_id])
    app_group: Mapped[Group | None] = relationship(foreign_keys=[app_group_id])
    process: Mapped["Process | None"] = relationship(foreign_keys=[process_id])
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
    # Nur bei Online-Anträgen
    ref_no: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="")
    status_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    route_email: Mapped[str] = mapped_column(String(255), default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    track_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    process_version_id: Mapped[int | None] = mapped_column(ForeignKey("process_versions.id", ondelete="SET NULL"),
                                                           nullable=True)
    fields_json: Mapped[str] = mapped_column(Text, default="{}")   # interne Felder aus den Arbeitsschritten

    form: Mapped[Form] = relationship(back_populates="responses")
    process_version: Mapped["ProcessVersion | None"] = relationship()
    tasks: Mapped[list["ApplicationTask"]] = relationship(back_populates="response", cascade="all, delete-orphan",
                                                          order_by="ApplicationTask.id", passive_deletes=True)
    requests: Mapped[list["ApplicationRequest"]] = relationship(back_populates="response", cascade="all, delete-orphan",
                                                                order_by="ApplicationRequest.id", passive_deletes=True)
    documents: Mapped[list["ApplicationDocument"]] = relationship(back_populates="response", cascade="all, delete-orphan",
                                                                  order_by="ApplicationDocument.id", passive_deletes=True)

    @property
    def fields(self) -> dict:
        import json as _json
        try:
            data = _json.loads(self.fields_json or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    group: Mapped[Group | None] = relationship(foreign_keys=[group_id])
    events: Mapped[list["ApplicationEvent"]] = relationship(back_populates="response", cascade="all, delete-orphan",
                                                            order_by="ApplicationEvent.at", passive_deletes=True)

    @property
    def answers(self) -> dict:
        import json as _json
        try:
            return _json.loads(self.answers_json or "{}")
        except ValueError:
            return {}


class ApplicationEvent(Base):
    """Verlauf eines Online-Antrags: Eingang, Status, Nachrichten, Notizen, Zuweisungen."""
    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("form_responses.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(12))        # created | status | message | reply | note | assign | due
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    public: Mapped[bool] = mapped_column(Boolean, default=False)   # für Antragsteller:in sichtbar

    response: Mapped[FormResponse] = relationship(back_populates="events")


class Process(Base):
    """Wiederverwendbarer Bearbeitungsprozess für Online-Anträge. Bearbeitet wird ein Entwurf,
    Anträge laufen immer auf einer veröffentlichten Version (siehe workflow.py)."""
    __tablename__ = "processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    draft_json: Mapped[str] = mapped_column(Text, default="{}")      # {steps: [...], end_status: ...}
    draft_changed: Mapped[bool] = mapped_column(Boolean, default=True)
    dms_area_id: Mapped[int | None] = mapped_column(ForeignKey("dms_areas.id", ondelete="SET NULL"), nullable=True)   # Ablage der Vorgänge
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()
    versions: Mapped[list["ProcessVersion"]] = relationship(back_populates="process", cascade="all, delete-orphan",
                                                            order_by="ProcessVersion.version.desc()",
                                                            passive_deletes=True)

    @property
    def current(self) -> "ProcessVersion | None":
        return self.versions[0] if self.versions else None


class ProcessVersion(Base):
    __tablename__ = "process_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("processes.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_by: Mapped[str] = mapped_column(String(255), default="")

    process: Mapped[Process] = relationship(back_populates="versions")


class ApplicationTask(Base):
    """Ein Arbeitsschritt eines Antrags: offen, wartet auf die antragstellende Person, erledigt, übersprungen."""
    __tablename__ = "application_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("form_responses.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(12))           # task | approval | request | auto
    state: Mapped[str] = mapped_column(String(12), default="open", index=True)  # open | waiting | done | skipped | cancelled
    outcome: Mapped[str] = mapped_column(String(12), default="")  # done | approved | rejected
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_by: Mapped[str] = mapped_column(String(255), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")  # abgehakte Prüfpunkte
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    response: Mapped[FormResponse] = relationship(back_populates="tasks")
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    group: Mapped[Group | None] = relationship(foreign_keys=[group_id])

    @property
    def data(self) -> dict:
        import json as _json
        try:
            value = _json.loads(self.data_json or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}


class ApplicationRequest(Base):
    """Nachforderung an die antragstellende Person: zusätzliche Felder/Dateien oder Korrektur von Antragsfeldern."""
    __tablename__ = "application_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("form_responses.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("application_tasks.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    schema_json: Mapped[str] = mapped_column(Text, default="[]")     # zusätzliche Felder (wie im Baukasten)
    reopen_json: Mapped[str] = mapped_column(Text, default="[]")     # IDs der Antragsfragen zur Korrektur
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    state: Mapped[str] = mapped_column(String(12), default="open", index=True)  # open | answered | cancelled
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str] = mapped_column(String(255), default="")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    response: Mapped[FormResponse] = relationship(back_populates="requests")

    def _load(self, raw, default):
        import json as _json
        try:
            value = _json.loads(raw or "")
        except ValueError:
            return default
        return value if isinstance(value, type(default)) else default

    @property
    def items(self) -> list:
        return self._load(self.schema_json, [])

    @property
    def reopen(self) -> list:
        return self._load(self.reopen_json, [])

    @property
    def answers(self) -> dict:
        return self._load(self.answers_json, {})


class RequestTemplate(Base):
    """Vorbereitete Nachforderung (z. B. „Lageplan nachreichen“), im Vorgang mit einem Klick auswählbar."""
    __tablename__ = "request_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    schema_json: Mapped[str] = mapped_column(Text, default="[]")
    due_days: Mapped[int] = mapped_column(Integer, default=14)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApplicationDocument(Base):
    """Im Vorgang erzeugtes Dokument, z. B. ein Bescheid als PDF."""
    __tablename__ = "application_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("form_responses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    file: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    public: Mapped[bool] = mapped_column(Boolean, default=False)   # auf der Statusseite abrufbar
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    response: Mapped[FormResponse] = relationship(back_populates="documents")


class GeoCache(Base):
    """Zwischenspeicher für Antworten des Geocoders (Nominatim), siehe geocode.py."""
    __tablename__ = "geo_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FormBlock(Base):
    """Datenblock (z. B. „Antragsteller:in“, „Hund“): gruppierte Felder, zentral gepflegt und in Formularen
    verknüpft eingesetzt – Änderungen wirken in allen Formularen, die den Block nutzen."""
    __tablename__ = "form_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(40), default="fa-cubes")
    schema_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


_O = lambda *labels: [{"id": f"o{n}", "label": label} for n, label in enumerate(labels)]  # noqa: E731
DEFAULT_BLOCKS = [
    ("Antragsteller:in (Person)", "fa-user", "Name, Geburtsdatum, Anschrift und Kontakt einer Person.", [
        {"id": "anrede", "type": "dropdown", "title": "Anrede", "width": "third", "options": _O("Frau", "Herr", "divers", "keine Angabe")},
        {"id": "vorname", "type": "short", "title": "Vorname", "required": True, "width": "third", "subtype": "text"},
        {"id": "nachname", "type": "short", "title": "Nachname", "required": True, "width": "third", "subtype": "text"},
        {"id": "geburt", "type": "date", "title": "Geburtsdatum", "width": "third"},
        {"id": "telefon", "type": "short", "title": "Telefon", "width": "third", "subtype": "phone"},
        {"id": "email", "type": "short", "title": "E-Mail-Adresse", "required": True, "width": "third", "subtype": "email"},
        {"id": "anschrift", "type": "address", "title": "Anschrift", "required": True, "mode": "full", "search": True,
         "locate": False, "district": False, "coords": True}]),
    ("Firma / Organisation", "fa-building", "Firmenname, Rechtsform, Register, Ansprechperson und Anschrift.", [
        {"id": "firma", "type": "short", "title": "Firmenname", "required": True, "width": "two_thirds", "subtype": "text"},
        {"id": "rechtsform", "type": "dropdown", "title": "Rechtsform", "width": "third",
         "options": _O("Einzelunternehmen", "GbR", "GmbH", "UG (haftungsbeschränkt)", "AG", "e. K.", "KG", "OHG", "e. V.", "Sonstige")},
        {"id": "register", "type": "short", "title": "Registergericht und -nummer", "width": "half", "subtype": "text",
         "placeholder": "z. B. Amtsgericht Kaiserslautern HRB 1234"},
        {"id": "ansprech", "type": "short", "title": "Ansprechperson", "width": "half", "subtype": "text"},
        {"id": "anschrift", "type": "address", "title": "Geschäftsanschrift", "required": True, "mode": "full", "search": True,
         "locate": False, "district": False, "coords": True},
        {"id": "telefon", "type": "short", "title": "Telefon", "width": "half", "subtype": "phone"},
        {"id": "email", "type": "short", "title": "E-Mail-Adresse", "width": "half", "subtype": "email"}]),
    ("Adresse", "fa-house", "Straße, Hausnummer, PLZ und Ort mit Adresssuche.", [
        {"id": "anschrift", "type": "address", "title": "Anschrift", "required": True, "mode": "full", "search": True,
         "locate": True, "district": True, "coords": True}]),
    ("Bankverbindung", "fa-building-columns", "Kontoinhaber:in, IBAN, BIC und Kreditinstitut.", [
        {"id": "inhaber", "type": "short", "title": "Kontoinhaber:in", "required": True, "subtype": "text"},
        {"id": "iban", "type": "short", "title": "IBAN", "required": True, "width": "two_thirds", "subtype": "regex",
         "pattern": "[A-Za-z]{2}[0-9]{2}[A-Za-z0-9 ]{11,32}", "pattern_hint": "Bitte eine gültige IBAN angeben, z. B. DE12 3456 7890 1234 5678 90",
         "placeholder": "DE00 0000 0000 0000 0000 00"},
        {"id": "bic", "type": "short", "title": "BIC (optional)", "width": "third", "subtype": "text"},
        {"id": "bank", "type": "short", "title": "Kreditinstitut", "subtype": "text"}]),
    ("Hund", "fa-dog", "Angaben zum Hund für Hundesteuer und Anmeldung.", [
        {"id": "name", "type": "short", "title": "Name des Hundes", "width": "half", "subtype": "text"},
        {"id": "rasse", "type": "short", "title": "Rasse", "required": True, "width": "half", "subtype": "text",
         "placeholder": "bei Mischlingen die erkennbaren Rassen"},
        {"id": "geschlecht", "type": "radio", "title": "Geschlecht", "required": True, "width": "third", "options": _O("Rüde", "Hündin")},
        {"id": "wurftag", "type": "date", "title": "Wurftag", "required": True, "width": "third"},
        {"id": "seit", "type": "date", "title": "Gehalten seit", "required": True, "width": "third"},
        {"id": "farbe", "type": "short", "title": "Farbe / Kennzeichen", "width": "half", "subtype": "text"},
        {"id": "chip", "type": "short", "title": "Chipnummer (Transponder)", "width": "half", "subtype": "regex",
         "pattern": "[0-9]{15}", "pattern_hint": "Die Chipnummer hat 15 Ziffern."},
        {"id": "herkunft", "type": "dropdown", "title": "Herkunft", "width": "half",
         "options": _O("Züchter:in", "Tierheim / Tierschutz", "Privatperson", "aus eigener Zucht", "Sonstiges")},
        {"id": "nachweis", "type": "file", "title": "Nachweis (z. B. Kaufvertrag, Heimtierausweis)", "width": "half",
         "file_types": ["pdf", "jpg", "jpeg", "png"], "max_files": 3, "max_size_mb": 10}]),
    ("Fahrzeug", "fa-car", "Kennzeichen, Hersteller, Modell und Farbe.", [
        {"id": "kennzeichen", "type": "short", "title": "Amtliches Kennzeichen", "required": True, "width": "third", "subtype": "text",
         "placeholder": "KL-AB 123"},
        {"id": "hersteller", "type": "short", "title": "Hersteller", "width": "third", "subtype": "text"},
        {"id": "modell", "type": "short", "title": "Typ / Modell", "width": "third", "subtype": "text"},
        {"id": "farbe", "type": "short", "title": "Farbe", "width": "third", "subtype": "text"}]),
]


def seed_form_blocks(db) -> None:
    """Startbibliothek der Datenblöcke (nur bei leerer Bibliothek)."""
    import json as _json
    if db.scalar(select(FormBlock.id).limit(1)) is not None:
        return
    for name, icon, description, items in DEFAULT_BLOCKS:
        db.add(FormBlock(name=name, icon=icon, description=description, schema_json=_json.dumps(items, ensure_ascii=False)))


class DmsArea(Base):
    """Ablagebereich im Aktenplan (verschachtelbar). Rechte gelten auch für alle Unterbereiche."""
    __tablename__ = "dms_areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("dms_areas.id", ondelete="RESTRICT"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(40), default="")          # Aktenplan-Nummer, z. B. 1.2.3
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    retention_years: Mapped[int] = mapped_column(Integer, default=0)   # 0 = unbegrenzt / vom übergeordneten Bereich
    position: Mapped[int] = mapped_column(Integer, default=0)
    system_key: Mapped[str] = mapped_column(String(20), default="")   # "unsorted" = „Nicht einsortiert“ (nicht löschbar)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    access: Mapped[list["DmsAccess"]] = relationship(back_populates="area", cascade="all, delete-orphan",
                                                     passive_deletes=True)


class DmsAccess(Base):
    __tablename__ = "dms_access"

    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("dms_areas.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1)             # 1 lesen, 2 lesen und schreiben

    area: Mapped[DmsArea] = relationship(back_populates="access")
    user: Mapped[User | None] = relationship()
    group: Mapped[Group | None] = relationship()


class Person(Base):
    """Bürger:in bzw. Antragsteller:in: verbindet Ablage-Einträge (Anträge, Buchungen, manuell Abgelegtes) mit
    einer Person. Zuordnung automatisch über die E-Mail-Adresse, sonst Name und PLZ (siehe dms.match_person)."""
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="", index=True)
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    street: Mapped[str] = mapped_column(String(255), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DmsRecord(Base):
    """Eintrag in der Ablage: ein Online-Antrag (laufend oder abgeschlossen) oder ein manuell abgelegter Vorgang."""
    __tablename__ = "dms_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("dms_areas.id", ondelete="RESTRICT"), index=True)
    response_id: Mapped[int | None] = mapped_column(ForeignKey("form_responses.id", ondelete="SET NULL"), nullable=True,
                                                    unique=True)
    kind: Mapped[str] = mapped_column(String(12), default="antrag")     # antrag | manuell
    title: Mapped[str] = mapped_column(String(300), default="")
    ref_no: Mapped[str] = mapped_column(String(60), default="", index=True)
    form_title: Mapped[str] = mapped_column(String(255), default="")
    applicant: Mapped[str] = mapped_column(String(255), default="")
    applicant_email: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="")
    street: Mapped[str] = mapped_column(String(255), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    district: Mapped[str] = mapped_column(String(200), default="")
    lat: Mapped[float | None] = mapped_column(nullable=True)
    lon: Mapped[float | None] = mapped_column(nullable=True)
    assignee: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True)
    area_manual: Mapped[bool] = mapped_column(Boolean, default=False)   # von Hand verschoben: nicht mehr automatisch umsortieren
    retention_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")               # Volltext (klein geschrieben)
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    area: Mapped[DmsArea] = relationship()
    person: Mapped[Person | None] = relationship()
    response: Mapped["FormResponse | None"] = relationship()
    files: Mapped[list["DmsFile"]] = relationship(back_populates="record", cascade="all, delete-orphan",
                                                  order_by="DmsFile.id", passive_deletes=True)


class DmsFile(Base):
    __tablename__ = "dms_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("dms_records.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    file: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String(100), default="")
    kind: Mapped[str] = mapped_column(String(16), default="upload")    # upload | abschluss | dokument
    sha256: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    uploaded_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    record: Mapped[DmsRecord] = relationship(back_populates="files")


class DmsSearch(Base):
    """Gespeicherte Suche einer Person."""
    __tablename__ = "dms_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[str] = mapped_column(Text, default="")


class DmsLog(Base):
    """Protokoll für Löschungen und Verschiebungen (Nachweis bei Löschfristen)."""
    __tablename__ = "dms_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_name: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text, default="")


class Payment(Base):
    """Zahlung zu einer Buchung, einem Antrag, einem Formular oder einem Prozessschritt (siehe payments.py).
    Beträge in Cent. Über token erreicht die zahlende Person ihre Zahlseite (/pay/<token>)."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)   # Verwendungszweck, z. B. Z-2026-00012
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="other", index=True)   # resource | application | form | step | other
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)   # Buchung, Antwort …
    purpose: Mapped[str] = mapped_column(String(255), default="")
    items_json: Mapped[str] = mapped_column(Text, default="[]")   # [{label, qty, unit_cents, cents}]
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    deposit_cents: Mapped[int] = mapped_column(Integer, default=0)   # enthaltene Kaution (erstattbar)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    methods: Mapped[str] = mapped_column(String(60), default="paypal,transfer")   # erlaubte Zahlarten
    method: Mapped[str] = mapped_column(String(20), default="")      # tatsächlich: paypal | transfer | cash | free
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    cost_center: Mapped[str] = mapped_column(String(120), default="")   # Kostenstelle / Haushaltsstelle
    payer_name: Mapped[str] = mapped_column(String(255), default="")
    payer_email: Mapped[str] = mapped_column(String(255), default="")
    paypal_order_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    paypal_capture_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    back_url: Mapped[str] = mapped_column(String(500), default="")   # Rücksprung nach der Zahlung (z. B. Statusseite)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overdue_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # Frist abgelaufen (gemeldet)
    log_json: Mapped[str] = mapped_column(Text, default="[]")


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
    shares: Mapped[list["PollShare"]] = relationship(back_populates="poll", cascade="all, delete-orphan",
                                                     order_by="PollShare.id", passive_deletes=True)

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
    shares: Mapped[list["BookingShare"]] = relationship(back_populates="page", cascade="all, delete-orphan",
                                                        order_by="BookingShare.id", passive_deletes=True)


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


class PollShare(Base):
    """Freigabe einer Terminumfrage im Portal (Stufen wie bei Formularen, siehe shares.py)."""
    __tablename__ = "poll_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True,
                                                 index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    poll: Mapped["Poll"] = relationship(back_populates="shares")
    user: Mapped[User | None] = relationship()
    group: Mapped[Group | None] = relationship()


class BookingShare(Base):
    """Freigabe einer Buchungsseite im Portal (Stufen wie bei Formularen, siehe shares.py)."""
    __tablename__ = "booking_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("booking_pages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True,
                                                 index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    page: Mapped["BookingPage"] = relationship(back_populates="shares")
    user: Mapped[User | None] = relationship()
    group: Mapped[Group | None] = relationship()


class MapLayer(Base):
    """Systemweiter Kartenlayer (Admin › Kartenlayer). Siehe maps.py für die Arten."""
    __tablename__ = "map_layers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10), default="xyz")      # xyz | wms | wfs | style | geojson
    role: Mapped[str] = mapped_column(String(10), default="overlay")  # base | overlay
    category: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    layers: Mapped[str] = mapped_column(Text, default="")             # WMS-Layer / WFS-Typname
    styles: Mapped[str] = mapped_column(String(255), default="")
    image_format: Mapped[str] = mapped_column(String(40), default="image/png")
    version: Mapped[str] = mapped_column(String(10), default="")
    transparent: Mapped[bool] = mapped_column(Boolean, default=True)
    tile_size: Mapped[int] = mapped_column(Integer, default=256)
    min_zoom: Mapped[int] = mapped_column(Integer, default=0)
    max_zoom: Mapped[int] = mapped_column(Integer, default=22)
    opacity: Mapped[float] = mapped_column(Float, default=1.0)
    attribution: Mapped[str] = mapped_column(Text, default="")
    legend_url: Mapped[str] = mapped_column(Text, default="")
    feature_info: Mapped[bool] = mapped_column(Boolean, default=False)
    time_values: Mapped[str] = mapped_column(Text, default="")        # WMS-T: Werte (kommagetrennt)
    time_default: Mapped[str] = mapped_column(String(60), default="")
    color: Mapped[str] = mapped_column(String(9), default="#e4572e")   # WFS/GeoJSON
    swap_xy: Mapped[bool] = mapped_column(Boolean, default=False)      # WFS liefert Breite/Länge vertauscht
    extra_hosts: Mapped[str] = mapped_column(Text, default="")         # zusätzliche Hosts für die CSP (direkt)
    proxy: Mapped[bool] = mapped_column(Boolean, default=True)         # über das Portal laden
    cache_hours: Mapped[int] = mapped_column(Integer, default=168)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public: Mapped[bool] = mapped_column(Boolean, default=True)        # im öffentlichen Kartenbrowser
    in_forms: Mapped[bool] = mapped_column(Boolean, default=False)     # als Karte für GPS-Fragen in Formularen
    default_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UserMap(Base):
    """Gespeicherte Karte einer Person: Ausschnitt, Layer, Transparenz, eigene WMS/WFS-Layer."""
    __tablename__ = "user_maps"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    public_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()


# Startausstattung der Kartenlayer (nur wenn noch keiner existiert). Adressen laut Dienstbeschreibung von
# OpenStreetMap bzw. dem BKG (basemap.de, Datenlizenz Deutschland – Namensnennung 2.0).
_BASEMAP_WMTS = ("https://sgx.geodatenzentrum.de/wmts_basemapde/tile/1.0.0/{layer}/default/GLOBAL_WEBMERCATOR/"
                 "{{z}}/{{y}}/{{x}}.png")
_BASEMAP_ATTR = '© <a href="https://basemap.de">basemap.de</a> / BKG, Datenlizenz Deutschland – Namensnennung 2.0'
DEFAULT_MAP_LAYERS = [
    dict(name="basemap.de (farbig)", kind="xyz", role="base", category="Grundkarten",
         url=_BASEMAP_WMTS.format(layer="de_basemapde_web_raster_farbe"), attribution=_BASEMAP_ATTR, max_zoom=19,
         proxy=True, in_forms=True, default_visible=True,
         description="Amtliche Grundkarte Deutschlands (Rasterkacheln) des Bundesamts für Kartographie und Geodäsie."),
    dict(name="basemap.de (grau)", kind="xyz", role="base", category="Grundkarten",
         url=_BASEMAP_WMTS.format(layer="de_basemapde_web_raster_grau"), attribution=_BASEMAP_ATTR, max_zoom=19,
         proxy=True, in_forms=True, description="Graue Variante – gut als Hintergrund für Fachdaten."),
    dict(name="basemap.de Vektor", kind="style", role="base", category="Grundkarten",
         url="https://sgx.geodatenzentrum.de/gdz_basemapde_vektor/styles/bm_web_col.json", attribution=_BASEMAP_ATTR,
         proxy=False, enabled=False, extra_hosts="https://sgx.geodatenzentrum.de",
         description="Vektorkarte von basemap.de (wird direkt beim BKG geladen). Vor dem Einschalten Datenschutzhinweis prüfen."),
    dict(name="OpenStreetMap", kind="xyz", role="base", category="Grundkarten",
         url="https://tile.openstreetmap.org/{z}/{x}/{y}.png", max_zoom=19, proxy=True, cache_hours=168, in_forms=True,
         attribution='© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende',
         description="Freie Weltkarte. Kacheln werden über das Portal geladen und eine Woche zwischengespeichert "
                     "(Nutzungsrichtlinie der OSM Foundation)."),
]


def seed_map_layers(db) -> None:
    if db.scalar(select(MapLayer.id).limit(1)) is not None:
        return
    for pos, spec in enumerate(DEFAULT_MAP_LAYERS):
        db.add(MapLayer(position=pos, **spec))


class LawLevel(Base):
    """Ebene im Rechtsbaum (EU, Bund, Land, Landkreis, Verbandsgemeinde, Ortsgemeinde …), beliebig verschachtelt."""
    __tablename__ = "law_levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("law_levels.id", ondelete="CASCADE"), nullable=True,
                                                  index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="sonstige")   # siehe laws.LEVEL_KINDS
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    parent: Mapped["LawLevel | None"] = relationship(remote_side="LawLevel.id", back_populates="children")
    children: Mapped[list["LawLevel"]] = relationship(back_populates="parent", order_by="(LawLevel.position, LawLevel.name)",
                                                      cascade="all, delete-orphan", passive_deletes=True)
    laws: Mapped[list["LawText"]] = relationship(back_populates="level", order_by="LawText.title")


class LawText(Base):
    """Rechtstext (Gesetz, Verordnung, Satzung …) als Markdown; Gliederung wird beim Speichern zerlegt."""
    __tablename__ = "law_texts"

    id: Mapped[int] = mapped_column(primary_key=True)
    level_id: Mapped[int | None] = mapped_column(ForeignKey("law_levels.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    title: Mapped[str] = mapped_column(String(400))
    short_title: Mapped[str] = mapped_column(String(80), default="")     # Abkürzung, z. B. „HS“ oder „GemO“
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    doc_type: Mapped[str] = mapped_column(String(30), default="satzung")
    body_md: Mapped[str] = mapped_column(Text, default="")
    version_note: Mapped[str] = mapped_column(String(255), default="")   # z. B. „Fassung vom 12.03.2024“
    issued_on: Mapped[str] = mapped_column(String(10), default="")       # Ausfertigung (JJJJ-MM-TT)
    valid_from: Mapped[str] = mapped_column(String(10), default="")      # in Kraft seit
    valid_until: Mapped[str] = mapped_column(String(10), default="")     # außer Kraft ab
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    level: Mapped[LawLevel | None] = relationship(back_populates="laws")
    editor: Mapped[User | None] = relationship(foreign_keys=[updated_by])
    sections: Mapped[list["LawSection"]] = relationship(back_populates="law", cascade="all, delete-orphan",
                                                        order_by="LawSection.position", passive_deletes=True)
    versions: Mapped[list["LawVersion"]] = relationship(back_populates="law", cascade="all, delete-orphan",
                                                        order_by="LawVersion.saved_at.desc()", passive_deletes=True)


class LawSection(Base):
    """Gliederungseinheit eines Rechtstexts (Teil, Abschnitt, § oder Artikel) – abgeleitet aus body_md."""
    __tablename__ = "law_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("law_texts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    parent_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(10))            # intro | group | norm
    number: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    anchor: Mapped[str] = mapped_column(String(120))
    html: Mapped[str] = mapped_column(Text, default="")
    plain: Mapped[str] = mapped_column(Text, default="")

    law: Mapped[LawText] = relationship(back_populates="sections")


class LawVersion(Base):
    """Frühere Fassung eines Rechtstexts (wird bei jeder inhaltlichen Änderung gesichert)."""
    __tablename__ = "law_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("law_texts.id", ondelete="CASCADE"), index=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    saved_by: Mapped[str] = mapped_column(String(255), default="")
    version_note: Mapped[str] = mapped_column(String(255), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")

    law: Mapped[LawText] = relationship(back_populates="versions")


# Ausgangsstruktur des Rechtsbaums (wird nur angelegt, solange noch keine Ebene existiert)
DEFAULT_LAW_LEVELS = (
    "Europäische Union", "eu", [
        ("Bundesrepublik Deutschland", "bund", [
            ("Rheinland-Pfalz", "land", [
                ("Landkreis Kaiserslautern", "landkreis", [
                    ("Verbandsgemeinde Otterbach-Otterberg", "vg", [
                        (f"{'Stadt' if n == 'Otterberg' else 'Ortsgemeinde'} {n}", "og", [])
                        for n in ("Frankelbach", "Hirschhorn/Pfalz", "Katzweiler", "Mehlbach", "Olsbrücken",
                                  "Otterbach", "Otterberg", "Schallodenbach", "Schneckenhausen", "Sulzbachtal",
                                  "Untersulzbach")]),
                ]),
            ]),
        ]),
    ])


def seed_law_levels(db) -> None:
    if db.scalar(select(LawLevel.id).limit(1)) is not None:
        return

    def add(node, parent, pos):
        name, kind, children = node
        level = LawLevel(name=name, kind=kind, parent=parent, position=pos)
        db.add(level)
        for i, child in enumerate(children):
            add(child, level, i)

    add(DEFAULT_LAW_LEVELS, None, 0)


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
    "module_laws": "1",
    # Rechtstexte per <iframe> einbinden (/recht-embed); leere Liste = alle Seiten dürfen einbinden
    "laws_embed": "1",
    "laws_embed_origins": "",
    # Kartenbrowser (Modul) und Kartenlayer
    "module_maps": "1",
    "map_center_lat": "49.4930",      # Startausschnitt: Verbandsgemeinde Otterbach-Otterberg
    "map_center_lon": "7.7680",
    "map_zoom": "11",
    "map_cache_mb": "500",           # Größe des Kachel-Zwischenspeichers
    "maps_embed": "1",
    "maps_embed_origins": "",
    "geocoder_url": "https://nominatim.openstreetmap.org",   # Adress-/Ortssuche (eigener Nominatim-Server möglich)
    "geocoder_countries": "de",
    "geocoder_contact": "",
    # Online-Anträge (Teil des Formularservers) und öffentlicher Antragskatalog
    "module_applications": "1",
    "module_dms": "1",
    # Zahlungen (PayPal Checkout, Überweisung, bar) – siehe payments.py
    "paypal_enabled": "0",
    "paypal_mode": "sandbox",          # sandbox | live
    "paypal_client_id": "",
    "paypal_secret_enc": "",
    "paypal_webhook_id": "",
    "pay_transfer": "1",              # Überweisung anbieten
    "pay_recipient": "",              # Empfänger, IBAN, BIC, Bank für Überweisungen
    "pay_iban": "",
    "pay_bic": "",
    "pay_bank": "",
    "pay_prefix": "Z",                # Verwendungszweck: Z-2026-00001
    "pay_days": "14",                 # Zahlfrist in Tagen
    "apps_embed": "1",
    "apps_embed_origins": "",
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
        "email_code_expires": "DATETIME", "dashboard_json": "TEXT NOT NULL DEFAULT ''",
    },
    "recordings": {"audio_path": "VARCHAR(1024)", "audio_max_db": "FLOAT", "media_deleted_at": "DATETIME",
                   "chat_json": "TEXT", "polls_json": "TEXT"},
    "meetings": {"starts_at": "DATETIME", "duration_minutes": "INTEGER", "description": "TEXT",
                 "ics_uid": "VARCHAR(255)", "ics_sequence": "INTEGER NOT NULL DEFAULT 0",
                 "cancelled_at": "DATETIME", "guest_token": "VARCHAR(64)"},
    "notifications": {"reply_to": "VARCHAR(255)", "attachments_json": "TEXT"},
    "forms": {"kind": "VARCHAR(12) NOT NULL DEFAULT 'survey'", "app_prefix": "VARCHAR(12) NOT NULL DEFAULT ''",
              "app_category": "VARCHAR(100) NOT NULL DEFAULT ''", "app_info": "TEXT NOT NULL DEFAULT ''",
              "app_fee": "VARCHAR(255) NOT NULL DEFAULT ''", "app_duration": "VARCHAR(255) NOT NULL DEFAULT ''",
              "app_assignee_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
              "app_group_id": "INTEGER REFERENCES groups(id) ON DELETE SET NULL",
              "app_mailbox": "VARCHAR(255) NOT NULL DEFAULT ''", "app_routing_json": "TEXT NOT NULL DEFAULT '[]'",
              "app_deadline_days": "INTEGER NOT NULL DEFAULT 14", "app_catalog": "BOOLEAN NOT NULL DEFAULT 1",
              "app_pdf": "BOOLEAN NOT NULL DEFAULT 1", "app_seq_year": "INTEGER NOT NULL DEFAULT 0",
              "app_seq": "INTEGER NOT NULL DEFAULT 0",
              "process_id": "INTEGER REFERENCES processes(id) ON DELETE SET NULL",
              "review": "BOOLEAN NOT NULL DEFAULT 1",
              "dms_area_id": "INTEGER REFERENCES dms_areas(id) ON DELETE SET NULL"},
    "form_responses": {"ref_no": "VARCHAR(40)", "status": "VARCHAR(16) NOT NULL DEFAULT ''", "status_at": "DATETIME",
                       "assignee_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
                       "group_id": "INTEGER REFERENCES groups(id) ON DELETE SET NULL",
                       "route_email": "VARCHAR(255) NOT NULL DEFAULT ''", "due_at": "DATETIME",
                       "overdue_notified_at": "DATETIME", "closed_at": "DATETIME", "track_token": "VARCHAR(64)",
                       "checksum": "VARCHAR(64) NOT NULL DEFAULT ''",
                       "process_version_id": "INTEGER REFERENCES process_versions(id) ON DELETE SET NULL",
                       "fields_json": "TEXT NOT NULL DEFAULT '{}'"},
    "dms_areas": {"system_key": "VARCHAR(20) NOT NULL DEFAULT ''"},
    "dms_records": {"person_id": "INTEGER REFERENCES persons(id) ON DELETE SET NULL",
                    "area_manual": "BOOLEAN NOT NULL DEFAULT 0"},
    "processes": {"dms_area_id": "INTEGER REFERENCES dms_areas(id) ON DELETE SET NULL"},
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
                                    ("ix_recordings_meeting_id", "recordings", "meeting_id"),
                                    ("ix_form_responses_ref_no", "form_responses", "ref_no"),
                                    ("ix_form_responses_assignee_id", "form_responses", "assignee_id"),
                                    ("ix_form_responses_group_id", "form_responses", "group_id")):
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_form_responses_track_token "
                          "ON form_responses (track_token)"))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()
    with SessionLocal() as db:
        for key, value in DEFAULT_SETTINGS.items():
            if db.get(Setting, key) is None:
                db.add(Setting(key=key, value=value))
        seed_law_levels(db)
        seed_map_layers(db)
        seed_form_blocks(db)
        if db.get(Setting, "migrated_app_create") is None:
            # Neues Recht „Online-Anträge einrichten“: wer bisher Formulare bearbeiten durfte, behält die Möglichkeit.
            for u in db.scalars(select(User)):
                if "forms" in u.perms and "app_create" not in u.perms:
                    u.permissions = ",".join([*u.perms, "app_create"])
            db.add(Setting(key="migrated_app_create", value="1"))
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
