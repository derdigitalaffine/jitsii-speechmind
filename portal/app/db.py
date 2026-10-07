import os
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    Boolean, Date, DateTime, Float, UniqueConstraint, ForeignKey, Integer, String, Text, create_engine, event, inspect, select, text,
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
    profile_data_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    nav_json: Mapped[str] = mapped_column(Text, default="")         # Menü: Favoriten, ausgeblendete Gruppen (nav.py)
    permissions: Mapped[str] = mapped_column(String(255), default="video")
    # Zwei-Faktor-Anmeldung (siehe twofa.py)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mfa_email: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_code_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Krankmelder: eigene Meldungen unter „Meine Krankmeldungen“ führen (freiwillig, siehe krank.py)
    krank_history: Mapped[bool] = mapped_column(Boolean, default=False)
    sub_confirm: Mapped[bool] = mapped_column(Boolean, default=False)   # Vertretungen für mich erst nach Zustimmung

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
    "circulations_create": ("Umläufe erstellen", "fa-folder-open", "Aushänge und Sammelmappen als Entwurf erstellen"),
    "circulations_publish": ("Umläufe veröffentlichen", "fa-bullhorn", "Eigene Umläufe veröffentlichen und redaktionell freigegebene Entwürfe übernehmen"),
    "circulations_manage": ("Umläufe verwalten", "fa-list-check", "Fremde Umläufe, Nachweise, Ausnahmen und Verteiler verwalten"),
    "locations_manage": ("Zentrale Orte pflegen", "fa-location-dot", "Dienststätten und Einrichtungen als Start-/Zielpunkte pflegen und importieren"),
    "internal_forms": ("Interne Formulare ausfüllen", "fa-user-lock", "Beschäftigte dürfen geschützte interne Formulare und Anträge einreichen"),
    "video": ("Videokonferenzen", "fa-video", "Meetings anlegen, planen, moderieren und aufnehmen"),
    "shortlinks": ("Kurzlinks", "fa-link", "Kurzlinks anlegen und auswerten"),
    "forms": ("Formulare", "fa-clipboard-list", "Formulare erstellen, verteilen und auswerten"),
    "polls": ("Terminumfragen", "fa-calendar-check", "Terminumfragen (wie Doodle) erstellen und auswerten"),
    "votes": ("Abstimmungen", "fa-check-to-slot", "Abstimmungen und Wahlen anlegen (offen, geheim, anonym), Wahlberechtigte einladen, Codes drucken, auswerten"),
    "bookings": ("Terminbuchung", "fa-calendar-plus", "Buchungsseiten mit freien Zeitfenstern anbieten (z. B. Vorstellungsgespräche)"),
    "laws": ("Rechtstexte", "fa-scale-balanced", "Gesetze, Satzungen und Verordnungen einstellen, gliedern und veröffentlichen"),
    "formblocks": ("Formularbausteine", "fa-cubes", "Datenblöcke (z. B. Antragsteller:in, Hund) in der zentralen Bibliothek anlegen und ändern"),
    "dms_admin": ("Aktenplan verwalten", "fa-sitemap", "Ablagebereiche (DMS) anlegen, Lese-/Schreibrechte und Löschfristen festlegen, abgelaufene Vorgänge löschen"),
    "processes": ("Prozesse", "fa-diagram-project", "Bearbeitungsprozesse für Online-Anträge im Prozesseditor gestalten und veröffentlichen"),
    "app_create": ("Online-Anträge einrichten", "fa-file-signature", "Formulare zu Online-Anträgen machen (Aktenzeichen, Frist, Zuständigkeit) und wieder zurückstellen"),
    "maps_admin": ("Kartenlayer & Geocoding", "fa-layer-group", "Kartenlayer, Kartenstandard und die Adresssuche (Nominatim) einrichten"),
    "maps": ("Karten", "fa-map-location-dot", "Im Kartenbrowser eigene WMS/WFS-Layer hinzufügen, Karten speichern und teilen"),
    "payments": ("Zahlungen", "fa-euro-sign", "Zahlungsübersicht und Export, Zahlungen als bezahlt markieren, erstatten und stornieren"),
    "resources": ("Ressourcen", "fa-building", "Bürgerhäuser, Räume, Grillplätze, Geräte anlegen, Buchungen bearbeiten, Belegungskalender teilen"),
    "krank": ("Krankmeldungen", "fa-notes-medical", "Krankmeldungen der Arbeitgeber bearbeiten, für die man (oder die eigene Gruppe) zuständig ist"),
    "krank_admin": ("Krankmelder verwalten", "fa-user-nurse", "Alle Krankmeldungen sehen; Arbeitgeber, Empfänger, Zuständige, Zugang, Texte, Löschfrist und Import verwalten"),
    "orgs": ("Körperschaften (Stammdaten)", "fa-landmark-flag", "Gebietskörperschaften, Zweckverbände und ihre Einrichtungen (Abteilungen, Kitas …) mit Wappen und Kontakt pflegen – genutzt von Ressourcen, Krankmelder, Rechtstexten und Anträgen"),
    "absences": ("Vertretungen verwalten", "fa-user-clock", "Abwesenheiten (z. B. Krankheit) mit Vertretung für andere eintragen – ohne Angabe eines Grundes"),
    "users": ("Benutzerverwaltung", "fa-users-gear", "Benutzer und Gruppen anlegen, bearbeiten und löschen"),
}



class Circulation(Base):
    """Editable draft; published versions and their acknowledgements remain separate."""
    __tablename__ = "circulations"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    draft_json: Mapped[str] = mapped_column(Text, default="{}")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CirculationBundle(Base):
    """Reusable document collection; imports are independent copies, not live publications."""
    __tablename__ = "circulation_bundles"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    draft_json: Mapped[str] = mapped_column(Text, default="{}")
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CirculationVersion(Base):
    __tablename__ = "circulation_versions"
    __table_args__ = (UniqueConstraint("circulation_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    circulation_id: Mapped[int] = mapped_column(ForeignKey("circulations.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
    published_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CirculationRecipient(Base):
    __tablename__ = "circulation_recipients"
    __table_args__ = (UniqueConstraint("version_id", "user_id"), UniqueConstraint("version_id", "email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("circulation_versions.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision: Mapped[str] = mapped_column(String(24), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class CirculationReceipt(Base):
    __tablename__ = "circulation_receipts"
    __table_args__ = (UniqueConstraint("recipient_id", "item_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("circulation_recipients.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(80))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    method: Mapped[str] = mapped_column(String(24), default="self")
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="")


class CirculationEvent(Base):
    __tablename__ = "circulation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    circulation_id: Mapped[int] = mapped_column(ForeignKey("circulations.id"), index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("circulation_versions.id"), nullable=True)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("circulation_recipients.id"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CirculationDistributor(Base):
    __tablename__ = "circulation_distributors"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    audience_json: Mapped[str] = mapped_column(Text, default="{}")

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
    # Gruppenleitung: darf Abwesenheiten und Vertretungen für die Mitglieder eintragen
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    members: Mapped[list[User]] = relationship(secondary="group_members", back_populates="groups",
                                               order_by="User.name")
    lead: Mapped[User | None] = relationship(foreign_keys=[lead_id])


class Absence(Base):
    """Abwesenheit mit Vertretung (absence.py). Sichtbar ist nur „abwesend bis …, Vertretung: …“ – kein Grund."""
    __tablename__ = "absences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    substitute_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                      index=True)
    starts_on: Mapped[str] = mapped_column(String(10))          # JJJJ-MM-TT (einschließlich)
    ends_on: Mapped[str] = mapped_column(String(10))            # JJJJ-MM-TT (einschließlich)
    status: Mapped[str] = mapped_column(String(10), default="confirmed")   # pending | confirmed | declined
    note: Mapped[str] = mapped_column(Text, default="")         # Notiz für die Vertretung (z. B. Übergabe)
    auto_reply: Mapped[str] = mapped_column(Text, default="")   # Abwesenheitsnotiz in Mails an Bürger:innen
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    substitute: Mapped[User | None] = relationship(foreign_keys=[substitute_id])
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])


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
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    org: Mapped["Organization | None"] = relationship(foreign_keys=[org_id])
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    schema_json: Mapped[str] = mapped_column(Text, default="[]")
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
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
    notify_pdf: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_files: Mapped[bool] = mapped_column(Boolean, default=False)
    pdf_uploads: Mapped[bool] = mapped_column(Boolean, default=True)
    confirm_csv: Mapped[bool] = mapped_column(Boolean, default=False)
    confirm_json: Mapped[bool] = mapped_column(Boolean, default=False)
    confirm_pdf: Mapped[bool] = mapped_column(Boolean, default=True)
    confirm_files: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_scope: Mapped[str] = mapped_column(String(10), default="single")  # single | all
    review: Mapped[bool] = mapped_column(Boolean, default=True)    # Übersicht vor dem Absenden
    # Online-Antrag (siehe applications.py): Aktenzeichen, Status, Zuständigkeit, PDF, Antragskatalog
    kind: Mapped[str] = mapped_column(String(12), default="survey")          # survey | application
    app_prefix: Mapped[str] = mapped_column(String(12), default="")          # z. B. GEW → GEW-2026-00042
    app_category: Mapped[str] = mapped_column(String(100), default="")
    app_icon: Mapped[str] = mapped_column(String(48), default="")      # Symbol im Antragskatalog (leer = Kategorie/Vorschlag)
    app_color: Mapped[str] = mapped_column(String(7), default="")      # Farbe des Symbols (leer = Kategorie)
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
    fee_json: Mapped[str] = mapped_column(Text, default="{}")        # Gebühr beim Absenden (siehe fees.py)
    legal_json: Mapped[str] = mapped_column(Text, default="[]")      # Rechtsgrundlagen: [{"law_id", "anchor"}]
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


class FormMailDownload(Base):
    __tablename__ = "form_mail_downloads"

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("form_responses.id", ondelete="CASCADE"), index=True)
    applicant: Mapped[bool] = mapped_column(Boolean, default=False)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload_enc: Mapped[str] = mapped_column(Text)


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
    prefill_json: Mapped[str] = mapped_column(Text, default="{}")
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


class ExpenseRuleSet(Base):
    __tablename__ = "expense_rule_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(200))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    rates_json: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PortalLocation(Base):
    __tablename__ = "portal_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), default="")
    street: Mapped[str] = mapped_column(String(255), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    public: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LocationFavorite(Base):
    __tablename__ = "location_favorites"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("portal_locations.id", ondelete="CASCADE"), primary_key=True)


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
    kind: Mapped[str] = mapped_column(String(12), default="antrag")     # antrag | manuell | buchung
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
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("resource_bookings.id", ondelete="SET NULL"), nullable=True,
                                                   index=True)
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
    kind: Mapped[str] = mapped_column(String(16), default="upload")    # upload | abschluss | dokument | nachreichung
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
    active_refund: Mapped[str] = mapped_column(String(36), default="")
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


class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    ref: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    cents: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    snapshot_json: Mapped[str] = mapped_column(Text)


class PaymentRefund(Base):
    """Durable refund intent; request_id remains stable across retries."""
    __tablename__ = "payment_refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    provider_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    cents: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), default="created")
    note: Mapped[str] = mapped_column(String(300), default="")
    actor: Mapped[str] = mapped_column(String(255), default="")
    fire_event: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default="")


class Vote(Base):
    """Abstimmung/Wahl (siehe votes.py): mehrere Fragen, offen, geheim oder anonym, Zugang per Einladung,
    öffentlichem Link mit E-Mail-Bestätigung und/oder ausgedruckten Codes."""
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    secrecy: Mapped[str] = mapped_column(String(12), default="secret")       # open | secret | anonymous
    access: Mapped[str] = mapped_column(String(40), default="invite")        # invite,public,codes
    results: Mapped[str] = mapped_column(String(12), default="after_end")    # live | after_vote | after_end | owner
    status: Mapped[str] = mapped_column(String(10), default="draft")         # draft | open | closed
    allow_change: Mapped[bool] = mapped_column(Boolean, default=False)       # Stimme bis zum Ende änderbar (nur offen)
    chart: Mapped[str] = mapped_column(String(8), default="bar")             # Live-Ansicht: bar (liegend) | column (stehend)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="")              # eingefrorenes Ergebnis beim Beenden
    result_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()
    questions: Mapped[list["VoteQuestion"]] = relationship(back_populates="vote", cascade="all, delete-orphan",
                                                           order_by="VoteQuestion.position", passive_deletes=True)
    voters: Mapped[list["VoteVoter"]] = relationship(back_populates="vote", cascade="all, delete-orphan",
                                                     order_by="VoteVoter.id", passive_deletes=True)
    shares: Mapped[list["VoteShare"]] = relationship(back_populates="vote", cascade="all, delete-orphan",
                                                     passive_deletes=True)


class VoteQuestion(Base):
    __tablename__ = "vote_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    vote_id: Mapped[int] = mapped_column(ForeignKey("votes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(10), default="single")          # single | multi | rank | points
    options_json: Mapped[str] = mapped_column(Text, default="[]")           # [{"id": "a1", "label", "info"}]
    min_choices: Mapped[int] = mapped_column(Integer, default=0)
    max_choices: Mapped[int] = mapped_column(Integer, default=1)              # Mehrfach: höchstens; Rangfolge: Plätze
    points_total: Mapped[int] = mapped_column(Integer, default=10)
    abstain: Mapped[bool] = mapped_column(Boolean, default=True)              # „Enthaltung“ anbieten

    vote: Mapped[Vote] = relationship(back_populates="questions")


class VoteVoter(Base):
    """Wählerverzeichnis: wer abstimmen darf und ob schon abgestimmt wurde (bei geheimen Abstimmungen getrennt
    von der Stimme gespeichert)."""
    __tablename__ = "vote_voters"

    id: Mapped[int] = mapped_column(primary_key=True)
    vote_id: Mapped[int] = mapped_column(ForeignKey("votes.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(10), default="invite")        # invite | public | code
    name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # persönlicher Link /v/p/<token>
    code: Mapped[str] = mapped_column(String(12), default="", index=True)     # Zugangscode (Ausdruck)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)           # öffentlich: erst nach Mail-Bestätigung
    voted: Mapped[bool] = mapped_column(Boolean, default=False)
    voted_on: Mapped[date | None] = mapped_column(Date, nullable=True)      # nur der Tag (kein Rückschluss auf die Stimme)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vote: Mapped[Vote] = relationship(back_populates="voters")


class VoteBallot(Base):
    """Stimmzettel. Zufällige ID und keine Uhrzeit: Bei geheimen und anonymen Abstimmungen lässt sich die Stimme
    nicht über Reihenfolge oder Zeitpunkt einer Person zuordnen. voter_id nur bei offenen Abstimmungen."""
    __tablename__ = "vote_ballots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    vote_id: Mapped[int] = mapped_column(ForeignKey("votes.id", ondelete="CASCADE"), index=True)
    voter_id: Mapped[int | None] = mapped_column(ForeignKey("vote_voters.id", ondelete="SET NULL"), nullable=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    receipt: Mapped[str] = mapped_column(String(16), default="", index=True)   # Quittung für die abstimmende Person


class LivePoll(Base):
    """Live-Umfrage (live.py): per QR-Code ohne Anmeldung und ohne Namen beantworten – je Gerät eine Antwort je
    Frage (änderbar). Moderiert (Frage für Frage) oder frei; Präsentationsmodus für den Beamer."""
    __tablename__ = "live_polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pacing: Mapped[str] = mapped_column(String(10), default="moderated")     # moderated | free
    current_id: Mapped[int | None] = mapped_column(Integer, nullable=True)    # moderiert: gerade gezeigte Frage
    status: Mapped[str] = mapped_column(String(10), default="draft")         # draft | open | closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship()
    questions: Mapped[list["LiveQuestion"]] = relationship(back_populates="poll", cascade="all, delete-orphan",
                                                           order_by="LiveQuestion.position, LiveQuestion.id",
                                                           passive_deletes=True)


class LiveQuestion(Base):
    __tablename__ = "live_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("live_polls.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(12), default="single")   # siehe live.KINDS
    title: Mapped[str] = mapped_column(String(500))
    options_json: Mapped[str] = mapped_column(Text, default="[]")     # [{"id", "label"}]
    settings_json: Mapped[str] = mapped_column(Text, default="{}")    # Skala, Begriffe je Person, richtige Antwort …
    chart: Mapped[str] = mapped_column(String(10), default="bar")     # bar | column | pie | donut | number | cloud | table
    show_results: Mapped[str] = mapped_column(String(10), default="immediate")   # immediate | release | never
    released: Mapped[bool] = mapped_column(Boolean, default=False)    # Ergebnis für Teilnehmende freigegeben
    locked: Mapped[bool] = mapped_column(Boolean, default=False)      # keine Antworten mehr

    poll: Mapped[LivePoll] = relationship(back_populates="questions")


class LiveAnswer(Base):
    """Antwort eines Geräts auf eine Frage (ein Eintrag je Gerät und Frage; bei Pinnwand/Q&A mehrere)."""
    __tablename__ = "live_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("live_polls.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("live_questions.id", ondelete="CASCADE"), index=True)
    device: Mapped[str] = mapped_column(String(64), index=True)       # Hash der Gerätekennung (kein Personenbezug)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    nickname: Mapped[str] = mapped_column(String(40), default="")      # nur Quiz, freiwillig
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)       # von der Moderation ausgeblendet
    approved: Mapped[bool] = mapped_column(Boolean, default=False)     # Q&A: freigegeben
    answered: Mapped[bool] = mapped_column(Boolean, default=False)     # Q&A: beantwortet
    upvotes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LiveUpvote(Base):
    """Q&A: „Diese Frage interessiert mich auch“ – je Gerät höchstens einmal je Beitrag."""
    __tablename__ = "live_upvotes"

    answer_id: Mapped[int] = mapped_column(ForeignKey("live_answers.id", ondelete="CASCADE"), primary_key=True)
    device: Mapped[str] = mapped_column(String(64), primary_key=True)


class VoteShare(Base):
    """Freigabe einer Abstimmung im Portal (Stufen wie bei Formularen, siehe shares.py)."""
    __tablename__ = "vote_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    vote_id: Mapped[int] = mapped_column(ForeignKey("votes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vote: Mapped[Vote] = relationship(back_populates="shares")
    user: Mapped[User | None] = relationship()
    group: Mapped[Group | None] = relationship()


class Resource(Base):
    """Buchbare Ressource (Bürgerhaus, Veranstaltungsraum, Grillplatz, Spülmobil …), siehe resources.py."""
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped["Organization | None"] = relationship(foreign_keys=[provider_id])
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    equipment: Mapped[str] = mapped_column(Text, default="")          # eine Zeile je Ausstattungsmerkmal
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    public: Mapped[bool] = mapped_column(Boolean, default=True)      # im öffentlichen Katalog buchbar
    mode: Mapped[str] = mapped_column(String(10), default="request")  # request (mit Freigabe) | instant (sofort)
    units: Mapped[str] = mapped_column(String(30), default="day")     # day,block,hour
    blocks_json: Mapped[str] = mapped_column(Text, default="[]")      # [{"id","label","start":"08:00","end":"13:00"}]
    hours_json: Mapped[str] = mapped_column(Text, default="{}")       # {"0": [["08:00","22:00"]], …} – fehlt = ganztags
    slot_minutes: Mapped[int] = mapped_column(Integer, default=60)
    min_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_minutes: Mapped[int] = mapped_column(Integer, default=0)
    max_days: Mapped[int] = mapped_column(Integer, default=3)
    min_notice_hours: Mapped[int] = mapped_column(Integer, default=48)
    max_advance_days: Mapped[int] = mapped_column(Integer, default=365)
    buffer_before: Mapped[int] = mapped_column(Integer, default=0)    # Minuten Rüstzeit vor/nach jeder Buchung
    buffer_after: Mapped[int] = mapped_column(Integer, default=0)
    price_day: Mapped[int] = mapped_column(Integer, default=0)        # Cent; wkd_* = Wochenende/Feiertag (0 = wie werktags)
    price_block: Mapped[int] = mapped_column(Integer, default=0)
    price_hour: Mapped[int] = mapped_column(Integer, default=0)
    wkd_day: Mapped[int] = mapped_column(Integer, default=0)
    wkd_block: Mapped[int] = mapped_column(Integer, default=0)
    wkd_hour: Mapped[int] = mapped_column(Integer, default=0)
    deposit_cents: Mapped[int] = mapped_column(Integer, default=0)
    deposit_methods: Mapped[str] = mapped_column(String(60), default="cash")
    deposit_guest_choice: Mapped[bool] = mapped_column(Boolean, default=False)
    pay_methods: Mapped[str] = mapped_column(String(60), default="paypal,transfer,cash")
    pay_days: Mapped[int] = mapped_column(Integer, default=7)
    cost_center: Mapped[str] = mapped_column(String(120), default="")
    self_cancel: Mapped[bool] = mapped_column(Boolean, default=True)
    cancel_free_days: Mapped[int] = mapped_column(Integer, default=14)
    cancel_fee_percent: Mapped[int] = mapped_column(Integer, default=0)
    fields_json: Mapped[str] = mapped_column(Text, default="[]")      # zusätzliche Angaben (Feld-Editor)
    terms_text: Mapped[str] = mapped_column(Text, default="")        # Nutzungsbedingungen (bestätigen lassen)
    terms_file: Mapped[str] = mapped_column(String(80), default="")  # Nutzungsordnung als PDF
    legal_json: Mapped[str] = mapped_column(Text, default="[]")      # verknüpfte Rechtstexte [{law_id, anchor, para, role, accept}]
    manager_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manager_group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    mailbox: Mapped[str] = mapped_column(String(255), default="")
    dms_area_id: Mapped[int | None] = mapped_column(ForeignKey("dms_areas.id", ondelete="SET NULL"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Erinnerungen: Tage vor Beginn an Buchende bzw. Zuständige (0 = aus), eigener Hinweistext (z. B. Schlüsselabholung)
    remind_days: Mapped[int] = mapped_column(Integer, default=2)
    remind_staff_days: Mapped[int] = mapped_column(Integer, default=1)
    remind_text: Mapped[str] = mapped_column(Text, default="")
    waitlist: Mapped[bool] = mapped_column(Boolean, default=True)    # bei belegtem Zeitraum auf die Warteliste
    # Übergabe durch Hausmeister:innen (Magic Link) und Protokolle
    deposit_release: Mapped[bool] = mapped_column(Boolean, default=False)   # Kaution erst nach Freigabe der Verwaltung
    protocol_to_booker: Mapped[bool] = mapped_column(Boolean, default=True)
    protocol_to_staff: Mapped[bool] = mapped_column(Boolean, default=True)
    caretaker_public: Mapped[bool] = mapped_column(Boolean, default=False)  # Kontakt vor Ort an Buchende
    caretaker_remind: Mapped[bool] = mapped_column(Boolean, default=False)  # Erinnerung an Hausmeister:innen
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    manager_user: Mapped[User | None] = relationship(foreign_keys=[manager_user_id])
    manager_group: Mapped[Group | None] = relationship()
    parts: Mapped[list["ResourceUnit"]] = relationship(back_populates="resource", cascade="all, delete-orphan",
                                                      order_by="ResourceUnit.position", passive_deletes=True)
    tariffs: Mapped[list["ResourceTariff"]] = relationship(back_populates="resource", cascade="all, delete-orphan",
                                                          order_by="ResourceTariff.position", passive_deletes=True)
    extras: Mapped[list["ResourceExtra"]] = relationship(back_populates="resource", cascade="all, delete-orphan",
                                                        order_by="ResourceExtra.position", passive_deletes=True)
    caretakers: Mapped[list["ResourceCaretaker"]] = relationship(secondary="resource_caretaker_links",
                                                                 back_populates="resources", order_by="ResourceCaretaker.name")
    photos: Mapped[list["ResourcePhoto"]] = relationship(back_populates="resource", cascade="all, delete-orphan",
                                                        order_by="ResourcePhoto.position", passive_deletes=True)
    closures: Mapped[list["ResourceClosure"]] = relationship(back_populates="resource", cascade="all, delete-orphan",
                                                            order_by="ResourceClosure.starts_at", passive_deletes=True)
    shares: Mapped[list["ResourceShare"]] = relationship(back_populates="resource", cascade="all, delete-orphan",
                                                        passive_deletes=True)


class ResourceUnit(Base):
    """Teilraum (z. B. Saal, Foyer, Küche). Buchung der ganzen Ressource belegt alle Teilräume."""
    __tablename__ = "resource_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    price_day: Mapped[int] = mapped_column(Integer, default=0)
    price_block: Mapped[int] = mapped_column(Integer, default=0)
    price_hour: Mapped[int] = mapped_column(Integer, default=0)
    wkd_day: Mapped[int] = mapped_column(Integer, default=0)
    wkd_block: Mapped[int] = mapped_column(Integer, default=0)
    wkd_hour: Mapped[int] = mapped_column(Integer, default=0)

    resource: Mapped[Resource] = relationship(back_populates="parts")


class ResourceTariff(Base):
    """Tarifgruppe (z. B. Einheimische 100 %, Auswärtige 150 %, Vereine 50 %) – gilt für die Miete."""
    __tablename__ = "resource_tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    percent: Mapped[int] = mapped_column(Integer, default=100)
    description: Mapped[str] = mapped_column(String(500), default="")
    needs_proof: Mapped[bool] = mapped_column(Boolean, default=False)   # Nachweis hochladen (z. B. Vereinsregister)
    position: Mapped[int] = mapped_column(Integer, default=0)

    resource: Mapped[Resource] = relationship(back_populates="tariffs")


class ResourceExtra(Base):
    """Zusatzleistung (WC-Wagen, Endreinigung, Besteck, Biertischgarnituren …), optional mit Bestand."""
    __tablename__ = "resource_extras"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500), default="")
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    per: Mapped[str] = mapped_column(String(8), default="once")        # once | day | hour | piece | person | persons | tier
    per_n: Mapped[int] = mapped_column(Integer, default=0)             # „je angefangene N Personen“
    tiers_json: Mapped[str] = mapped_column(Text, default="[]")       # Staffel [{"upto": 50, "cents": 2000}, {"upto": 0, …}]
    min_cents: Mapped[int] = mapped_column(Integer, default=0)         # Mindestbetrag (0 = keiner)
    max_cents: Mapped[int] = mapped_column(Integer, default=0)         # Höchstbetrag (0 = keiner)
    cancel_rule: Mapped[str] = mapped_column(String(8), default="")    # "" Storno-Regel | refund | keep | only
    cancel_days: Mapped[int] = mapped_column(Integer, default=0)       # Frist für keep/only (Tage vor Beginn)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)   # gleichzeitig verfügbar (leer = unbegrenzt)
    max_qty: Mapped[int] = mapped_column(Integer, default=1)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    resource: Mapped[Resource] = relationship(back_populates="extras")


class ResourcePhoto(Base):
    __tablename__ = "resource_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    file: Mapped[str] = mapped_column(String(80))
    thumb: Mapped[str] = mapped_column(String(80), default="")      # Vorschaubild (480 px), leer bei alten Fotos
    name: Mapped[str] = mapped_column(String(200), default="")      # ursprünglicher Dateiname
    caption: Mapped[str] = mapped_column(String(300), default="")   # Bildunterschrift (auch Alternativtext)
    position: Mapped[int] = mapped_column(Integer, default=0)       # 0 = Titelbild

    resource: Mapped[Resource] = relationship(back_populates="photos")


class ResourceClosure(Base):
    """Sperrzeit (Ferien, Wartung) – ganz oder für einen Teilraum."""
    __tablename__ = "resource_closures"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("resource_units.id", ondelete="CASCADE"), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(String(255), default="")

    resource: Mapped[Resource] = relationship(back_populates="closures")


class ResourceBooking(Base):
    """Buchung einer Ressource. Status: unconfirmed (E-Mail noch nicht bestätigt), requested (wartet auf Freigabe),
    confirmed, rejected, cancelled, expired (nicht bestätigt bzw. nicht bezahlt)."""
    __tablename__ = "resource_bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    unit_ids: Mapped[str] = mapped_column(String(200), default="")      # Komma-Liste, leer = ganze Ressource
    mode: Mapped[str] = mapped_column(String(8), default="day")
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="unconfirmed", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")          # Anlass
    organizer: Mapped[str] = mapped_column(String(255), default="")      # Verein / Veranstalter
    persons: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    street: Mapped[str] = mapped_column(String(255), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    tariff_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tariff_name: Mapped[str] = mapped_column(String(120), default="")
    extras_json: Mapped[str] = mapped_column(Text, default="[]")         # [{"id","name","qty"}]
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    lines_json: Mapped[str] = mapped_column(Text, default="[]")          # Preisposten zum Zeitpunkt der Buchung
    cancel_json: Mapped[str] = mapped_column(Text, default="[]")         # nur bei Absage fällige Posten (Nachvermietung)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    deposit_cents: Mapped[int] = mapped_column(Integer, default=0)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    confirm_code: Mapped[str] = mapped_column(String(32), default="")
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"), nullable=True)
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    series_id: Mapped[str] = mapped_column(String(16), default="", index=True)
    created_by: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str] = mapped_column(Text, default="")                  # intern
    message: Mapped[str] = mapped_column(Text, default="")               # Mitteilung an die buchende Person
    handover_json: Mapped[str] = mapped_column(Text, default="{}")       # Übergabe und Abnahme
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(255), default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    group_ref: Mapped[str] = mapped_column(String(40), default="", index=True)   # mehrere Ressourcen in einer Buchung
    club_id: Mapped[int | None] = mapped_column(ForeignKey("resource_clubs.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    billing: Mapped[str] = mapped_column(String(10), default="")       # "" sofort | invoice | monthly (Sammelrechnung)
    billed_payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    staff_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    resource: Mapped[Resource] = relationship()
    deposit_payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    deposit_payment: Mapped["Payment | None"] = relationship(foreign_keys=[deposit_payment_id])
    payment: Mapped["Payment | None"] = relationship(foreign_keys=[payment_id])
    club: Mapped["ResourceClub | None"] = relationship()


class TrashItem(Base):
    """Gelöschter Eintrag im Papierkorb: alle Zeilen (mit abhängigen Daten) als JSON, Dateien im Ordner trash/<id>.
    Nach Ablauf (Standard 30 Tage) endgültig entfernt."""
    __tablename__ = "trash_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(300), default="")
    table_name: Mapped[str] = mapped_column(String(60))
    row_id: Mapped[int] = mapped_column(Integer)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    files_json: Mapped[str] = mapped_column(Text, default="[]")       # [[Ursprungsordner, Ordner im Papierkorb]]
    deleted_by: Mapped[str] = mapped_column(String(255), default="")
    batch: Mapped[str] = mapped_column(String(32), default="", index=True)   # Sammellöschung (Bereich leeren)
    deleted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class DeletionLog(Base):
    """Protokoll: wer wann was gelöscht, wiederhergestellt oder endgültig entfernt hat."""
    __tablename__ = "deletion_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(20))       # delete | bulk | restore | purge | expire
    kind: Mapped[str] = mapped_column(String(20), default="")
    count: Mapped[int] = mapped_column(Integer, default=1)
    detail: Mapped[str] = mapped_column(Text, default="")


class ResourceCaretakerLink(Base):
    __tablename__ = "resource_caretaker_links"

    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
    caretaker_id: Mapped[int] = mapped_column(ForeignKey("resource_caretakers.id", ondelete="CASCADE"), primary_key=True)


class ResourceCaretaker(Base):
    """Hausmeister:in / Platzwart:in: übergibt und nimmt ab – ohne Portal-Konto über einen persönlichen Link
    (Magic Link), wahlweise mit einem Portal-Konto verknüpft (Name, E-Mail und Telefon kommen dann von dort)."""
    __tablename__ = "resource_caretakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(400), default="")   # SHA-256 der gültigen Links (bis zu 5)
    note: Mapped[str] = mapped_column(String(500), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User | None] = relationship(foreign_keys=[user_id])
    resources: Mapped[list[Resource]] = relationship(secondary="resource_caretaker_links", back_populates="caretakers",
                                                     order_by="Resource.name")

    @property
    def display_name(self) -> str:
        return (self.user.name if self.user else "") or self.name

    @property
    def contact_email(self) -> str:
        return (self.user.email if self.user else "") or self.email


class ResourceClub(Base):
    """Verein bzw. Dauernutzer: meldet sich per Link aus der E-Mail an, bucht ohne erneute Angaben, mit eigenem
    Tarif und eigener Zahlweise (sofort, Rechnung je Buchung oder Sammelrechnung je Monat)."""
    __tablename__ = "resource_clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    street: Mapped[str] = mapped_column(String(255), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    tariff_name: Mapped[str] = mapped_column(String(120), default="")    # Tarif mit diesem Namen, wo vorhanden
    billing: Mapped[str] = mapped_column(String(10), default="instant")  # instant | invoice | monthly
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)         # selbst registriert, wartet auf Freigabe
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    token_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    login_gen: Mapped[int] = mapped_column(Integer, default=0)            # erhöhen = alle Geräte abmelden
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResourceWait(Base):
    """Warteliste für einen belegten Zeitraum. Wird er frei, bekommt der oder die Erste 24 Stunden exklusiv
    die Möglichkeit zu buchen (status offered), danach der oder die Nächste."""
    __tablename__ = "resource_waits"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    confirm_code: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(12), default="unconfirmed", index=True)
    mode: Mapped[str] = mapped_column(String(8), default="day")
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    unit_ids: Mapped[str] = mapped_column(String(200), default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")            # Eingaben zum Vorausfüllen
    name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    club_id: Mapped[int | None] = mapped_column(ForeignKey("resource_clubs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    offered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    offer_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("resource_bookings.id", ondelete="SET NULL"), nullable=True)

    resource: Mapped[Resource] = relationship()


class ResourceCalendar(Base):
    """Geteilter Belegungskalender (iCal-Abo und Web-Ansicht) über einen geheimen Link.
    level: busy (nur belegt), title (mit Anlass/Veranstalter), full (mit Kontaktdaten)."""
    __tablename__ = "resource_calendars"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    level: Mapped[str] = mapped_column(String(8), default="busy")
    tentative: Mapped[bool] = mapped_column(Boolean, default=True)      # unbestätigte Anfragen als „vorgemerkt“
    resource_ids: Mapped[str] = mapped_column(String(500), default="")  # Komma-Liste
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    embed: Mapped[bool] = mapped_column(Boolean, default=False)          # Web-Ansicht per iframe einbettbar

    created_by: Mapped[User | None] = relationship()


class ResourceShare(Base):
    """Freigabe einer Ressource im Portal (Stufen siehe shares.py: Belegung · mit Kontaktdaten · verwalten)."""
    __tablename__ = "resource_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    resource: Mapped[Resource] = relationship(back_populates="shares")
    user: Mapped[User | None] = relationship()
    group: Mapped[Group | None] = relationship()


class CustomHoliday(Base):
    """Eigener Feiertag für Wochenend-/Feiertagspreise (z. B. Kerwe)."""
    __tablename__ = "custom_holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(120))


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
    listed: Mapped[bool] = mapped_column(Boolean, default=False)         # im öffentlichen Verzeichnis „Termine buchen“
    # Erweiterter Umfang (btypes.py): mehrere Terminarten mit eigenen Dauern, Mitarbeitenden und Sprechzeiten
    extended: Mapped[bool] = mapped_column(Boolean, default=False)
    days_ahead: Mapped[int] = mapped_column(Integer, default=60)          # so weit im Voraus buchbar
    step_minutes: Mapped[int] = mapped_column(Integer, default=15)        # Raster der Beginnzeiten
    holidays_closed: Mapped[bool] = mapped_column(Boolean, default=True)  # an Feiertagen keine Termine
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
    types: Mapped[list["BookingType"]] = relationship(back_populates="page", cascade="all, delete-orphan",
                                                      order_by="BookingType.position, BookingType.id",
                                                      passive_deletes=True)
    hours: Mapped[list["BookingHours"]] = relationship(cascade="all, delete-orphan", passive_deletes=True,
                                                       order_by="BookingHours.weekday, BookingHours.start")
    closures: Mapped[list["BookingClosure"]] = relationship(cascade="all, delete-orphan", passive_deletes=True,
                                                            order_by="BookingClosure.date_from")
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
    # Erweiterter Umfang: Terminart, zuständige Person, Antworten auf eigene Felder; status auch „requested“
    type_id: Mapped[int | None] = mapped_column(ForeignKey("booking_types.id", ondelete="SET NULL"), nullable=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
                                                    index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="")

    page: Mapped[BookingPage] = relationship(back_populates="bookings")
    type: Mapped["BookingType | None"] = relationship()
    provider: Mapped[User | None] = relationship(foreign_keys=[provider_id])


class BookingType(Base):
    """Terminart einer Buchungsseite im erweiterten Umfang (z. B. „Bauberatung, 45 Minuten“)."""
    __tablename__ = "booking_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("booking_pages.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    docs_hint: Mapped[str] = mapped_column(Text, default="")              # „Bitte mitbringen: …“
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)       # Puffer nach dem Termin
    min_notice_hours: Mapped[int] = mapped_column(Integer, default=24)    # Vorlauf
    location: Mapped[str] = mapped_column(String(255), default="")
    online: Mapped[bool] = mapped_column(Boolean, default=False)          # Videokonferenz
    approval: Mapped[bool] = mapped_column(Boolean, default=False)        # Bestätigung durch Mitarbeitende
    phone_mode: Mapped[str] = mapped_column(String(10), default="optional")   # none | optional | required
    choose_provider: Mapped[bool] = mapped_column(Boolean, default=False)     # Bürger:innen wählen die Person
    fields_json: Mapped[str] = mapped_column(Text, default="[]")          # eigene Felder (Teil 2)
    color: Mapped[str] = mapped_column(String(9), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    page: Mapped[BookingPage] = relationship(back_populates="types")
    providers: Mapped[list[User]] = relationship(secondary="booking_type_providers", order_by="User.name")


class BookingTypeProvider(Base):
    __tablename__ = "booking_type_providers"

    type_id: Mapped[int] = mapped_column(ForeignKey("booking_types.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class BookingHours(Base):
    """Wiederkehrende Sprechzeit einer Person auf einer Buchungsseite (Ortszeit, Wochentag 0 = Montag)."""
    __tablename__ = "booking_hours"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("booking_pages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    start: Mapped[str] = mapped_column(String(5))     # HH:MM
    end: Mapped[str] = mapped_column(String(5))

    user: Mapped[User] = relationship()


class BookingClosure(Base):
    """Ausnahme: an diesen Tagen keine Termine – für alle (user_id leer) oder eine Person."""
    __tablename__ = "booking_closures"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("booking_pages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    date_from: Mapped[str] = mapped_column(String(10))
    date_to: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(String(200), default="")

    user: Mapped[User | None] = relationship()


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


class Organization(Base):
    """Gebietskörperschaft, Zweckverband oder Einrichtung (Abteilung, Kita, Bauhof …) – portalweit gepflegt
    (Verwaltung › Körperschaften) und in allen Modulen genutzt: Anbieter von Ressourcen, Arbeitgeber im
    Krankmelder, Ebenen der Rechtstexte, zuständige Stelle von Anträgen. Einrichtungen hängen unter ihrer
    Körperschaft (parent), Ortsgemeinden unter der Verbandsgemeinde."""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True,
                                                  index=True)
    kind: Mapped[str] = mapped_column(String(20), default="og")          # siehe orgs.KINDS
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(80), default="")
    ags: Mapped[str] = mapped_column(String(20), default="")             # amtlicher Gemeindeschlüssel
    color: Mapped[str] = mapped_column(String(7), default="")
    logo: Mapped[str] = mapped_column(String(64), default="")            # Dateiname im Ordner orgs/
    street: Mapped[str] = mapped_column(String(255), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    contact: Mapped[str] = mapped_column(String(255), default="")        # Ansprechperson / Stelle
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parent: Mapped["Organization | None"] = relationship(remote_side="Organization.id", back_populates="children")
    children: Mapped[list["Organization"]] = relationship(back_populates="parent",
                                                          order_by="(Organization.position, Organization.name)")


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
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    org: Mapped["Organization | None"] = relationship(foreign_keys=[org_id])

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
    internal: Mapped[bool] = mapped_column(Boolean, default=False)  # published but only authenticated portal readers
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
    attachments: Mapped[list["LawAttachment"]] = relationship(back_populates="law", cascade="all, delete-orphan",
                                                              order_by="LawAttachment.position", passive_deletes=True)
    topics_json: Mapped[str] = mapped_column(Text, default="")  # empty = editorial suggestions; [] = no topics
    # Vorbereitete neue Fassung: wird am Tag des Inkrafttretens automatisch übernommen (siehe laws.apply_planned)
    planned_md: Mapped[str] = mapped_column(Text, default="")
    planned_valid_from: Mapped[str] = mapped_column(String(10), default="")
    planned_note: Mapped[str] = mapped_column(String(255), default="")
    # Unterste Ebene (Einzelvorschrift): leer = automatisch, „paragraf“ oder eine Bezeichnung (laws.OUTLINE_MODES)
    outline: Mapped[str] = mapped_column(String(20), default="")


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

    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    id: Mapped[int] = mapped_column(primary_key=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("law_texts.id", ondelete="CASCADE"), index=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    saved_by: Mapped[str] = mapped_column(String(255), default="")
    version_note: Mapped[str] = mapped_column(String(255), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    # Öffentlich abrufbare frühere Fassung mit Geltungszeitraum (sonst nur interne Sicherung einer Korrektur)
    public: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(400), default="")
    valid_from: Mapped[str] = mapped_column(String(10), default="")
    valid_until: Mapped[str] = mapped_column(String(10), default="")

    law: Mapped[LawText] = relationship(back_populates="versions")


class LawAttachment(Base):
    """Anlage zu einem Rechtstext (Plan, Gebührentabelle …) als PDF."""
    __tablename__ = "law_attachments"

    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    id: Mapped[int] = mapped_column(primary_key=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("law_texts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    file: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    law: Mapped[LawText] = relationship(back_populates="attachments")


# --- BlueOtter Krankmelder (Modul „krank“) -------------------------------------------------------
# Personenbezogene Angaben und Gesundheitsdaten liegen verschlüsselt in data_enc (siehe krank.py);
# unverschlüsselt sind nur Art, Status, Arbeitgeber und Zeitstempel für Listen, Zähler und Fristen.

class KrankEmployer(Base):
    """Arbeitgeber mit Empfängern, Zuständigen und Einstellungen (wie im Krankmelder)."""
    __tablename__ = "krank_employers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)        # inaktiv: ausgegraut, nicht wählbar
    color: Mapped[str] = mapped_column(String(7), default="#3B82F6")
    position: Mapped[int] = mapped_column(Integer, default=0)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    org: Mapped["Organization | None"] = relationship(foreign_keys=[org_id])
    emails: Mapped[str] = mapped_column(Text, default="")              # Empfänger, eine Adresse je Zeile
    send_global_copy: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_remarks: Mapped[bool] = mapped_column(Boolean, default=False)
    subject_prefix: Mapped[str] = mapped_column(String(100), default="")
    attach_files: Mapped[bool] = mapped_column(Boolean, default=False)  # Mail mit PDF/Nachweis statt nur Hinweis + Link
    dms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dms_area_id: Mapped[int | None] = mapped_column(ForeignKey("dms_areas.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    responsible: Mapped[list["KrankResponsible"]] = relationship(back_populates="employer", cascade="all, delete-orphan",
                                                                 passive_deletes=True)


class KrankResponsible(Base):
    """Zuständige Person oder Gruppe für die Meldungen eines Arbeitgebers."""
    __tablename__ = "krank_responsible"

    id: Mapped[int] = mapped_column(primary_key=True)
    employer_id: Mapped[int] = mapped_column(ForeignKey("krank_employers.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)

    employer: Mapped[KrankEmployer] = relationship(back_populates="responsible")
    user: Mapped[User | None] = relationship()
    group: Mapped[Group | None] = relationship()


class KrankReport(Base):
    """Eine Krank- bzw. Kindkrankmeldung."""
    __tablename__ = "krank_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref_no: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)          # simple | au | eau | child
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    status_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    employer_id: Mapped[int | None] = mapped_column(ForeignKey("krank_employers.id", ondelete="SET NULL"), nullable=True,
                                                    index=True)
    employer_name: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    data_enc: Mapped[str] = mapped_column(Text, default="")
    has_email: Mapped[bool] = mapped_column(Boolean, default=False)
    track_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    proof_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_by: Mapped[str] = mapped_column(String(255), default="")
    delete_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    dms_record_id: Mapped[int | None] = mapped_column(ForeignKey("dms_records.id", ondelete="SET NULL"), nullable=True)
    import_key: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    employer: Mapped[KrankEmployer | None] = relationship()
    files: Mapped[list["KrankFile"]] = relationship(back_populates="report", cascade="all, delete-orphan",
                                                    order_by="KrankFile.id", passive_deletes=True)
    events: Mapped[list["KrankEvent"]] = relationship(back_populates="report", cascade="all, delete-orphan",
                                                      order_by="KrankEvent.id", passive_deletes=True)


class KrankFile(Base):
    """Nachweis (AU, Kinderkrankbescheinigung) – auf dem Datenträger verschlüsselt gespeichert."""
    __tablename__ = "krank_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("krank_reports.id", ondelete="CASCADE"), index=True)
    name_enc: Mapped[str] = mapped_column(Text, default="")
    file: Mapped[str] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(12), default="meldung")   # meldung | nachgereicht | verwaltung | import
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    report: Mapped[KrankReport] = relationship(back_populates="files")


class KrankEvent(Base):
    """Verlauf einer Meldung: Statuswechsel, interne Notizen, Nachrichten, Nachgereichtes (Text verschlüsselt)."""
    __tablename__ = "krank_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("krank_reports.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(12))      # status | note | message | reply | file | mail | system
    by: Mapped[str] = mapped_column(String(255), default="")
    public: Mapped[bool] = mapped_column(Boolean, default=False)   # auf der Statusseite sichtbar
    text_enc: Mapped[str] = mapped_column(Text, default="")

    report: Mapped[KrankReport] = relationship(back_populates="events")


class KrankAccess(Base):
    """Zugriffsprotokoll: wer hat wann welche Meldung angesehen, heruntergeladen, geändert oder gelöscht.
    Bleibt nach dem Löschen der Meldung erhalten (nur Aktenzeichen, keine Inhalte)."""
    __tablename__ = "krank_access"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ref_no: Mapped[str] = mapped_column(String(30), default="", index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(String(500), default="")


class KrankFeedback(Base):
    """Anonyme Bewertung nach dem Absenden."""
    __tablename__ = "krank_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    rating: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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


def seed_orgs(db) -> None:
    """Einmalig: Körperschaften aus dem Rechtsbaum (Landkreis, Verbandsgemeinde, Ortsgemeinden) anlegen und
    verknüpfen; bisherige Arbeitgeber des Krankmelders als Einrichtungen übernehmen."""
    if db.get(Setting, "migrated_orgs") is not None:
        return
    db.flush()

    def walk(level, parent_org):
        org = parent_org
        if level.kind in ("vg", "og") and level.org_id is None:
            kind = "vg" if level.kind == "vg" else ("stadt" if level.name.startswith("Stadt ") else "og")
            org = Organization(name=level.name, kind=kind, parent=parent_org, position=level.position)
            db.add(org)
            level.org = org
        for child in level.children:
            walk(child, org)
    for root in db.scalars(select(LawLevel).where(LawLevel.parent_id.is_(None))):
        walk(root, None)
    for emp in db.scalars(select(KrankEmployer).order_by(KrankEmployer.position, KrankEmployer.name)):
        if emp.org_id is None:
            same = db.scalar(select(Organization).where(Organization.name == emp.name))
            emp.org = same or Organization(name=emp.name, kind="einrichtung", color=emp.color or "", position=emp.position)
    db.add(Setting(key="migrated_orgs", value="1"))


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
    "location_manager_groups": "",
    "routing_car_url": "https://routing.openstreetmap.de/routed-car",
    "routing_bike_url": "https://routing.openstreetmap.de/routed-bike",
    "routing_foot_url": "https://routing.openstreetmap.de/routed-foot",
    "geocoder_search_mode": "auto",
    "geocoder_delay_ms": "300",
    "routing_auto": "1",
    "geocoder_url": "https://nominatim.openstreetmap.org",   # Adress-/Ortssuche (eigener Nominatim-Server möglich)
    "geocoder_countries": "de",
    "geocoder_contact": "",
    # Online-Anträge (Teil des Formularservers) und öffentlicher Antragskatalog
    "module_applications": "1",
    "module_dms": "1",
    "module_circulations": "1",
    "module_resources": "1",
    "holiday_state": "RP",            # Bundesland für Feiertagspreise
    "resources_embed": "1",
    "resources_embed_origins": "",
    # Zahlungen (PayPal Checkout, Überweisung, bar) – siehe payments.py
    "epaybl_operator": "",
    "epaybl_tenant": "",
    "epaybl_interface": "",
    "epaybl_accounting_reference": "",
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
    # BlueOtter Krankmelder (siehe krank.py)
    "module_krank": "0",                    # Gesundheitsdaten: bewusst einschalten (Verwaltung › Module)
    "krank_title": "Krankmeldung",
    "krank_intro": "",
    "krank_kinds": "simple,au,eau,child",   # angebotene Meldewege
    "krank_public": "1",                    # Zugang ohne Konto (Passwort oder Zugangslink)
    # Öffentliches Menü und Startseite für Bürger:innen (siehe public_nav.py)
    "public_nav": "",                       # JSON: Reihenfolge, ausgeblendete Bereiche, eigene Links
    "public_home": "1",                     # „/“ ohne Anmeldung zeigt die Startseite (sonst Anmeldung)
    "public_home_title": "",                # Überschrift (leer = Name des Portals)
    "public_home_text": "",                 # Begrüßungstext
    "public_contact": "",                   # Kontakt: Anschrift, Telefon, E-Mail, Öffnungszeiten (Text)
    "krank_password_hash": "",
    "krank_access_token_enc": "",
    "krank_global_email": "",               # Personalverwaltung (Standard und globale Kopie)
    "krank_subject_prefix": "Krankmeldung",
    "krank_retention_days": "0",            # 0 = keine automatische Löschung
    "krank_proof_reminder_days": "3",       # 0 = keine Erinnerung
    "krank_feedback": "1",
    "krank_text_instructions": "",
    "krank_text_staff": "",
    "krank_embed": "1",
    "krank_embed_origins": "",
    "krank_seq_year": "0",
    "krank_seq": "0",
    # Eigene Domains je Modul (domain_<modul>); Kurzlinks nutzen weiterhin short_domain
    "domain_forms": "", "domain_polls": "", "domain_bookings": "", "domain_laws": "", "domain_maps": "",
    "domain_applications": "", "domain_resources": "", "domain_krank": "",
    # Update-Hinweis für Admins
    "res_club_signup": "0",       # Vereine dürfen sich selbst registrieren (mit Freigabe)
    "res_club_mailbox": "",       # Hinweis auf neue Registrierungen
    "res_category_colors": "{}",  # Art → Farbe (Karte, Katalog), sonst automatisch
    "update_check": "1",

    "update_latest": "",
    "update_checked_at": "",
}

# Spalten, die in späteren Versionen dazukamen (SQLite: ALTER TABLE ADD COLUMN)
_NEW_COLUMNS = {
    "application_requests": {"prefill_json": "TEXT NOT NULL DEFAULT '{}'"},
    "payments": {"active_refund": "VARCHAR(36) NOT NULL DEFAULT ''"},
    "groups": {"lead_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL"},
    "booking_pages": {"listed": "BOOLEAN NOT NULL DEFAULT 0", "extended": "BOOLEAN NOT NULL DEFAULT 0",
                      "days_ahead": "INTEGER NOT NULL DEFAULT 60", "step_minutes": "INTEGER NOT NULL DEFAULT 15",
                      "holidays_closed": "BOOLEAN NOT NULL DEFAULT 1"},
    "bookings": {"type_id": "INTEGER REFERENCES booking_types(id) ON DELETE SET NULL",
                 "provider_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL", "answers_json": "TEXT NOT NULL DEFAULT ''"},
    "votes": {"chart": "VARCHAR(8) NOT NULL DEFAULT 'bar'"},
    "resource_extras": {"per_n": "INTEGER NOT NULL DEFAULT 0", "tiers_json": "TEXT NOT NULL DEFAULT '[]'",
                        "min_cents": "INTEGER NOT NULL DEFAULT 0", "max_cents": "INTEGER NOT NULL DEFAULT 0",
                        "cancel_rule": "VARCHAR(8) NOT NULL DEFAULT ''", "cancel_days": "INTEGER NOT NULL DEFAULT 0"},
    "resource_photos": {"thumb": "VARCHAR(80) NOT NULL DEFAULT ''", "caption": "VARCHAR(300) NOT NULL DEFAULT ''"},
    "users": {
        "profile_data_enc": "TEXT",
        "password_set": "BOOLEAN NOT NULL DEFAULT 1",
        "must_change_password": "BOOLEAN NOT NULL DEFAULT 0",
        "token_hash": "VARCHAR(64)",
        "token_expires_at": "DATETIME",
        "permissions": "VARCHAR(255) NOT NULL DEFAULT 'video'",
        "totp_secret_enc": "TEXT", "totp_enabled": "BOOLEAN NOT NULL DEFAULT 0", "totp_last_step": "INTEGER",
        "mfa_email": "BOOLEAN NOT NULL DEFAULT 0", "recovery_json": "TEXT", "email_code_hash": "VARCHAR(64)",
        "email_code_expires": "DATETIME", "dashboard_json": "TEXT NOT NULL DEFAULT ''", "nav_json": "TEXT NOT NULL DEFAULT ''",
        "krank_history": "BOOLEAN NOT NULL DEFAULT 0", "sub_confirm": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "recordings": {"audio_path": "VARCHAR(1024)", "audio_max_db": "FLOAT", "media_deleted_at": "DATETIME",
                   "chat_json": "TEXT", "polls_json": "TEXT"},
    "meetings": {"starts_at": "DATETIME", "duration_minutes": "INTEGER", "description": "TEXT",
                 "ics_uid": "VARCHAR(255)", "ics_sequence": "INTEGER NOT NULL DEFAULT 0",
                 "cancelled_at": "DATETIME", "guest_token": "VARCHAR(64)"},
    "notifications": {"reply_to": "VARCHAR(255)", "attachments_json": "TEXT"},
    "forms": {"internal": "BOOLEAN NOT NULL DEFAULT 0", "notify_pdf": "BOOLEAN NOT NULL DEFAULT 0", "notify_files": "BOOLEAN NOT NULL DEFAULT 0",
              "pdf_uploads": "BOOLEAN NOT NULL DEFAULT 1", "confirm_csv": "BOOLEAN NOT NULL DEFAULT 0",
              "confirm_json": "BOOLEAN NOT NULL DEFAULT 0", "confirm_pdf": "BOOLEAN NOT NULL DEFAULT 1",
              "confirm_files": "BOOLEAN NOT NULL DEFAULT 0", "kind": "VARCHAR(12) NOT NULL DEFAULT 'survey'", "app_prefix": "VARCHAR(12) NOT NULL DEFAULT ''",
              "app_category": "VARCHAR(100) NOT NULL DEFAULT ''", "app_icon": "VARCHAR(48) NOT NULL DEFAULT ''",
              "app_color": "VARCHAR(7) NOT NULL DEFAULT ''", "app_info": "TEXT NOT NULL DEFAULT ''",
              "app_fee": "VARCHAR(255) NOT NULL DEFAULT ''", "app_duration": "VARCHAR(255) NOT NULL DEFAULT ''",
              "app_assignee_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
              "app_group_id": "INTEGER REFERENCES groups(id) ON DELETE SET NULL",
              "app_mailbox": "VARCHAR(255) NOT NULL DEFAULT ''", "app_routing_json": "TEXT NOT NULL DEFAULT '[]'",
              "app_deadline_days": "INTEGER NOT NULL DEFAULT 14", "app_catalog": "BOOLEAN NOT NULL DEFAULT 1",
              "app_pdf": "BOOLEAN NOT NULL DEFAULT 1", "app_seq_year": "INTEGER NOT NULL DEFAULT 0",
              "app_seq": "INTEGER NOT NULL DEFAULT 0",
              "process_id": "INTEGER REFERENCES processes(id) ON DELETE SET NULL",
              "review": "BOOLEAN NOT NULL DEFAULT 1",
              "dms_area_id": "INTEGER REFERENCES dms_areas(id) ON DELETE SET NULL",
              "fee_json": "TEXT NOT NULL DEFAULT '{}'", "legal_json": "TEXT NOT NULL DEFAULT '[]'",
              "org_id": "INTEGER REFERENCES organizations(id) ON DELETE SET NULL"},
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
                    "area_manual": "BOOLEAN NOT NULL DEFAULT 0",
                    "booking_id": "INTEGER REFERENCES resource_bookings(id) ON DELETE SET NULL"},
    "processes": {"dms_area_id": "INTEGER REFERENCES dms_areas(id) ON DELETE SET NULL"},
    "resources": {"deposit_methods": "VARCHAR(60) NOT NULL DEFAULT 'cash'", "deposit_guest_choice": "BOOLEAN NOT NULL DEFAULT 0", "provider_id": "INTEGER REFERENCES organizations(id) ON DELETE SET NULL",
                  "deposit_release": "BOOLEAN NOT NULL DEFAULT 0", "protocol_to_booker": "BOOLEAN NOT NULL DEFAULT 1",
                  "protocol_to_staff": "BOOLEAN NOT NULL DEFAULT 1", "caretaker_public": "BOOLEAN NOT NULL DEFAULT 0",
                  "caretaker_remind": "BOOLEAN NOT NULL DEFAULT 0",
                  "legal_json": "TEXT NOT NULL DEFAULT '[]'",
                  "remind_days": "INTEGER NOT NULL DEFAULT 2", "remind_staff_days": "INTEGER NOT NULL DEFAULT 1",
                  "remind_text": "TEXT NOT NULL DEFAULT ''", "waitlist": "BOOLEAN NOT NULL DEFAULT 1"},
    "resource_bookings": {"deposit_payment_id": "INTEGER REFERENCES payments(id) ON DELETE SET NULL", "group_ref": "VARCHAR(40) NOT NULL DEFAULT ''", "cancel_json": "TEXT NOT NULL DEFAULT '[]'",
                          "club_id": "INTEGER REFERENCES resource_clubs(id) ON DELETE SET NULL",
                          "billing": "VARCHAR(10) NOT NULL DEFAULT ''",
                          "billed_payment_id": "INTEGER REFERENCES payments(id) ON DELETE SET NULL",
                          "reminded_at": "DATETIME", "staff_reminded_at": "DATETIME"},
    "invitees": {"rsvp_status": "VARCHAR(16)", "rsvp_at": "DATETIME", "rsvp_comment": "TEXT",
                 "join_token": "VARCHAR(64)"},
    "law_levels": {"org_id": "INTEGER REFERENCES organizations(id) ON DELETE SET NULL"},
    "krank_employers": {"org_id": "INTEGER REFERENCES organizations(id) ON DELETE SET NULL"},
    "law_texts": {"internal": "BOOLEAN NOT NULL DEFAULT 0", "planned_md": "TEXT NOT NULL DEFAULT ''", "planned_valid_from": "VARCHAR(10) NOT NULL DEFAULT ''",
                  "planned_note": "VARCHAR(255) NOT NULL DEFAULT ''", "outline": "VARCHAR(20) NOT NULL DEFAULT ''",
                  "topics_json": "TEXT NOT NULL DEFAULT ''"},
    "law_attachments": {"internal": "BOOLEAN NOT NULL DEFAULT 0"},
    "law_versions": {"internal": "BOOLEAN NOT NULL DEFAULT 0", "public": "BOOLEAN NOT NULL DEFAULT 0", "title": "VARCHAR(400) NOT NULL DEFAULT ''",
                     "valid_from": "VARCHAR(10) NOT NULL DEFAULT ''", "valid_until": "VARCHAR(10) NOT NULL DEFAULT ''"},
}


def _migrate() -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            if table == "forms" and "confirm_pdf" not in existing:
                conn.execute(text("UPDATE forms SET confirm_pdf = CASE WHEN kind = 'application' THEN app_pdf ELSE 0 END"))
        for name, table, column in (("ix_recordings_status", "recordings", "status"),
                                    ("ix_recordings_meeting_id", "recordings", "meeting_id"),
                                    ("ix_form_responses_ref_no", "form_responses", "ref_no"),
                                    ("ix_form_responses_assignee_id", "form_responses", "assignee_id"),
                                    ("ix_form_responses_group_id", "form_responses", "group_id"),
                                    ("ix_resource_bookings_group_ref", "resource_bookings", "group_ref"),
                                    ("ix_resource_bookings_club_id", "resource_bookings", "club_id")):
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
        seed_orgs(db)
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
