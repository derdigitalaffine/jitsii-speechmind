"""BlueOtter Krankmelder als Portal-Modul: strukturierte Krank- und Kindkrankmeldungen für Beschäftigte.

Vier Meldewege (wie im eigenständigen Krankmelder, einzeln abschaltbar):
  simple  Krankmeldung ohne AU – nur für den aktuellen Tag, nur Montag bis Freitag
  au      Meldung mit AU – Bescheinigung hochladen (PDF/JPG/PNG), Erst- oder Folgebescheinigung
  eau     eAU – keine Bescheinigung, die Personalverwaltung ruft sie bei der Krankenkasse ab. Dafür werden die
          Daten exakt wie auf dem Ausdruck für Versicherte erfasst (arbeitsunfähig seit, voraussichtlich bis,
          festgestellt am, Erst-/Folgebescheinigung). Privat Versicherte haben keine eAU → Meldung mit AU.
  child   Kind krank (§ 45 SGB V) – Angaben zum Kind, Bescheinigung hochladen oder nachreichen

Datenschutz (Gesundheitsdaten, Art. 9 DSGVO):
  - Alle personenbezogenen Angaben, Notizen und Nachrichten liegen verschlüsselt in der Datenbank, hochgeladene
    Nachweise verschlüsselt auf dem Datenträger (Schlüssel abgeleitet aus PORTAL_SECRET_KEY).
  - Jeder Zugriff (Ansehen, PDF, Datei, Export, Status, Löschen) wird protokolliert (KrankAccess).
  - Mails an die Zuständigen enthalten standardmäßig nur einen Hinweis mit Link; Angaben und PDF nur, wenn das
    beim Arbeitgeber eingeschaltet ist. Nach dem Versand werden Text und Anhänge aus der Warteschlange entfernt.
  - Bearbeitete Meldungen werden nach der eingestellten Frist automatisch gelöscht (mit Protokoll).
"""

import base64
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, or_, select

from . import csvsafe, links, mailtpl, notify
from .config import settings
from .db import (
    DmsArea, DmsRecord, GroupMember, KrankAccess, KrankEmployer, KrankEvent, KrankFeedback, KrankFile, KrankReport,
    KrankResponsible, SessionLocal, User, get_settings, set_setting, to_local, utcnow,
)
from .security import hash_password, hash_token, verify_password

log = logging.getLogger("portal.krank")

KINDS = {
    "simple": ("Krankmeldung ohne AU", "fa-bed", "Nur für heute (Montag bis Freitag). Ab dem 4. Kalendertag ist eine "
               "ärztliche Bescheinigung nötig – dann „Meldung mit AU“ oder „eAU“ nutzen."),
    "au": ("Meldung mit AU", "fa-file-medical", "Ärztliche Arbeitsunfähigkeitsbescheinigung als Scan oder Foto "
           "hochladen (z. B. bei privater Krankenversicherung)."),
    "eau": ("eAU (elektronische AU)", "fa-laptop-medical", "Gesetzlich versichert? Die Praxis meldet die AU elektronisch "
            "an die Krankenkasse, die Personalverwaltung ruft sie dort ab. Sie übertragen nur die Daten vom Ausdruck."),
    "child": ("Kind krank (§ 45 SGB V)", "fa-child-reaching", "Freistellung zur Betreuung eines erkrankten Kindes, mit "
              "ärztlicher Bescheinigung (hochladen oder nachreichen)."),
}
KIND_SHORT = {"simple": "ohne AU", "au": "AU", "eau": "eAU", "child": "Kind krank"}

# Status: (Bezeichnung, Bootstrap-Farbe, Symbol)
STATUSES = {
    "new": ("Neu", "primary", "fa-circle-dot"),
    "progress": ("In Bearbeitung", "info", "fa-spinner"),
    "proof_missing": ("Nachweis fehlt", "warning", "fa-file-circle-exclamation"),
    "eau_open": ("Abruf offen", "primary", "fa-cloud-arrow-down"),
    "eau_ok": ("eAU abgerufen", "success", "fa-cloud-arrow-down"),
    "eau_failed": ("Abruf erfolglos", "danger", "fa-triangle-exclamation"),
    "done": ("Bearbeitet", "success", "fa-circle-check"),
}
KIND_STATUSES = {
    "eau": ("eau_open", "eau_ok", "eau_failed", "progress", "done"),
    "simple": ("new", "progress", "done"),
    "au": ("new", "progress", "proof_missing", "done"),
    "child": ("new", "progress", "proof_missing", "done"),
}
OPEN = ("new", "eau_open")            # wartet auf die Personalverwaltung (Zähler in der Navigation)
MAX_FILE = 5 * 1024 * 1024
MIME_EXT = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
NAME_MAX = 120


def status_label(status: str) -> str:
    return STATUSES.get(status, (status,))[0]


def kind_label(kind: str) -> str:
    return KINDS.get(kind, (kind,))[0]


# --- Verschlüsselung -------------------------------------------------------------------------------

def _fernet() -> Fernet:
    digest = hashlib.sha256(("krank-data:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def enc(text: str) -> str:
    return _fernet().encrypt((text or "").encode()).decode() if text else ""


def dec(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


def data(report: KrankReport) -> dict:
    """Entschlüsselte Angaben einer Meldung (je Objekt zwischengespeichert)."""
    cached = getattr(report, "_krank_data", None)
    if cached is None:
        try:
            cached = json.loads(dec(report.data_enc) or "{}")
        except ValueError:
            cached = {}
        report._krank_data = cached
    return cached


def set_data(report: KrankReport, values: dict) -> None:
    report.data_enc = enc(json.dumps(values, ensure_ascii=False))
    report._krank_data = values


def full_name(report: KrankReport) -> str:
    d = data(report)
    return " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x) or "–"


def event_text(event: KrankEvent) -> str:
    return dec(event.text_enc)


def file_name(f: KrankFile) -> str:
    return dec(f.name_enc) or f"Datei {f.id}"


# --- Dateien ------------------------------------------------------------------------------------------

def files_dir(report_id: int) -> Path:
    return settings.data_dir / "krank" / str(report_id)


def sniff_mime(head: bytes) -> str | None:
    """Dateityp am Inhalt erkennen (nicht an Endung oder Angabe des Browsers)."""
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def check_upload(name: str, content: bytes) -> str:
    """Prüft einen Nachweis wie der Krankmelder (PDF, JPG, PNG; Inhalt geprüft; höchstens 5 MB). Gibt den Typ zurück."""
    if not content:
        raise ValueError("Die Datei ist leer.")
    if len(content) > MAX_FILE:
        raise ValueError("Die Datei ist zu groß (höchstens 5 MB).")
    mime = sniff_mime(content[:16])
    if mime is None:
        raise ValueError("Dateityp nicht erlaubt. Erlaubt sind PDF, JPG und PNG.")
    return mime


def store_file(report: KrankReport, name: str, content: bytes, mime: str, source: str) -> KrankFile:
    target = files_dir(report.id)
    target.mkdir(parents=True, exist_ok=True)
    stored = secrets.token_hex(12) + ".bin"
    (target / stored).write_bytes(_fernet().encrypt(content))
    clean = re.sub(r"[\x00-\x1f/\\]", "_", name or "nachweis")[-NAME_MAX:] or "nachweis"
    f = KrankFile(name_enc=enc(clean), file=stored, size=len(content), mime=mime, source=source)
    report.files.append(f)
    return f


def read_file(f: KrankFile) -> bytes:
    path = files_dir(f.report_id) / f.file
    try:
        return _fernet().decrypt(path.read_bytes())
    except (OSError, InvalidToken):
        return b""


def delete_files(report_id: int) -> None:
    shutil.rmtree(files_dir(report_id), ignore_errors=True)


# --- Einstellungen und Zugang -------------------------------------------------------------------------

def enabled_kinds(cfg: dict[str, str]) -> list[str]:
    chosen = {k.strip() for k in (cfg.get("krank_kinds") or "").split(",")}
    return [k for k in KINDS if k in chosen]


def employer_groups(emps: list[KrankEmployer]) -> list[tuple[str, list[KrankEmployer]]]:
    """Arbeitgeber nach Körperschaft gruppiert (Verwaltung › Körperschaften) – für die Auswahl im Formular.
    Ohne Zuordnung: Gruppe „Weitere“. Nur eine Gruppe: keine Überschriften nötig."""
    from . import orgs
    groups: dict[str, list[KrankEmployer]] = {}
    order: list[str] = []
    for e in emps:
        body = orgs.body_of(e.org) if e.org_id else None
        key = body.name if body is not None else "Weitere"
        if key not in groups:
            groups[key], _ = [], order.append(key)
        groups[key].append(e)
    if "Weitere" in order:
        order.remove("Weitere")
        order.append("Weitere")
    return [(k, groups[k]) for k in order]


def employers(db, active_only: bool = False) -> list[KrankEmployer]:
    q = select(KrankEmployer).order_by(KrankEmployer.position, KrankEmployer.name)
    if active_only:
        q = q.where(KrankEmployer.active.is_(True))
    return db.scalars(q).all()


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=salt)


TICKET_HOURS = 12


def _ticket_generation(cfg: dict[str, str]) -> str:
    """Ändert sich mit Passwort und Zugangslink – neue Zugangsdaten machen alte Tickets ungültig."""
    raw = f"{cfg.get('krank_password_hash') or ''}|{cfg.get('krank_access_token_enc') or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def make_ticket(cfg: dict[str, str]) -> str:
    """Nachweis für den öffentlichen Zugang (Passwort oder Zugangslink geprüft). Wird als verstecktes Feld
    mitgeschickt und funktioniert damit auch eingebettet (iframe), wo Browser keine Cookies senden."""
    return _serializer("krank-access").dumps(_ticket_generation(cfg))


def ticket_valid(ticket: str | None, cfg: dict[str, str]) -> bool:
    if not ticket:
        return False
    try:
        return hmac.compare_digest(str(_serializer("krank-access").loads(ticket, max_age=TICKET_HOURS * 3600)),
                                   _ticket_generation(cfg))
    except (BadSignature, SignatureExpired):
        return False


def public_open(cfg: dict[str, str]) -> bool:
    """Zugang ohne Konto möglich (eingeschaltet und Passwort oder Zugangslink vorhanden)?"""
    return cfg.get("krank_public") == "1" and bool(cfg.get("krank_password_hash") or cfg.get("krank_access_token_enc"))


def check_password(cfg: dict[str, str], password: str) -> bool:
    stored = cfg.get("krank_password_hash") or ""
    return bool(stored and password and verify_password(stored, password))


def set_password(db, password: str) -> None:
    set_setting(db, "krank_password_hash", hash_password(password) if password else "")


def access_token(cfg: dict[str, str]) -> str:
    from .security import decrypt
    return decrypt(cfg.get("krank_access_token_enc"))


def new_access_token(db) -> str:
    from .security import encrypt
    token = secrets.token_urlsafe(18)
    set_setting(db, "krank_access_token_enc", encrypt(token))
    return token


def token_matches(cfg: dict[str, str], token: str) -> bool:
    import hmac
    expected = access_token(cfg)
    return bool(expected and token and hmac.compare_digest(expected, token))


def access_link(db, cfg: dict[str, str]) -> str:
    token = access_token(cfg)
    return links.module_url(db, "krank", f"/krank/z/{token}", cfg) if token else ""


def download_token(report_id: int) -> str:
    return _serializer("krank-pdf").dumps(report_id)


def download_valid(report_id: int, token: str | None) -> bool:
    if not token:
        return False
    try:
        return _serializer("krank-pdf").loads(token, max_age=3600) == report_id
    except (BadSignature, SignatureExpired):
        return False


def by_track(db, token: str) -> KrankReport | None:
    if not token or len(token) > 100:
        return None
    return db.scalar(select(KrankReport).where(KrankReport.track_hash == hash_token(token)))


def status_link(db, report: KrankReport, cfg: dict[str, str] | None = None) -> str:
    token = data(report).get("_track", "")
    return links.module_url(db, "krank", f"/krank/s/{token}", cfg) if token else ""


def staff_link(report: KrankReport) -> str:
    return f"{settings.portal_base_url}/krankmelder/{report.id}"


# --- Sichtbarkeit -----------------------------------------------------------------------------------

def manager(user: User) -> bool:
    return bool(user.is_admin or user.can("krank_admin"))


def scope(db, user: User) -> set[int] | None:
    """Arbeitgeber, deren Meldungen die Person sehen darf. None = alle (Admins, „Krankmelder verwalten“)."""
    if manager(user):
        return None
    if not user.can("krank"):
        return set()
    groups = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
    return set(db.scalars(select(KrankResponsible.employer_id).where(
        or_(KrankResponsible.user_id == user.id, KrankResponsible.group_id.in_(groups)))).all())


def reports_query(db, user: User):
    q = select(KrankReport)
    ids = scope(db, user)
    if ids is not None:
        q = q.where(KrankReport.employer_id.in_(ids or [-1]))
    return q


def can_see(db, user: User, report: KrankReport) -> bool:
    ids = scope(db, user)
    return ids is None or report.employer_id in ids


def uses_module(db, user: User | None) -> bool:
    """Bearbeitet die Person Krankmeldungen (für Navigation und Startseite)?"""
    if user is None:
        return False
    if manager(user):
        return True
    return user.can("krank") and bool(scope(db, user))


def open_count(db, user: User) -> int:
    q = reports_query(db, user).where(KrankReport.status.in_(OPEN))
    return db.scalar(select(func.count()).select_from(q.subquery())) or 0


# --- Prüfung der Angaben (fachliche Regeln wie im Krankmelder) -----------------------------------------

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def today() -> date:
    return to_local(utcnow()).date()


def parse_day(value: str, label: str, required: bool = True, near: bool = True) -> date | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise ValueError(f"Bitte „{label}“ angeben.")
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"„{label}“ ist kein gültiges Datum.") from None
    if near and abs((day - today()).days) > 400:
        raise ValueError(f"„{label}“ liegt mehr als ein Jahr zurück oder voraus – bitte prüfen.")
    return day


def de(day: date | str | None) -> str:
    if not day:
        return "–"
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day)
        except ValueError:
            return day
    return day.strftime("%d.%m.%Y")


def calendar_days(start: date, end: date) -> int:
    return (end - start).days + 1


def _same_person(a: dict, b: dict) -> bool:
    norm = lambda s: " ".join(str(s or "").lower().split())  # noqa: E731
    return norm(a.get("first_name")) == norm(b.get("first_name")) and norm(a.get("last_name")) == norm(b.get("last_name"))


def predecessor(db, kind: str, employer_id: int | None, values: dict, exclude_id: int | None = None) -> dict | None:
    """Letzte Meldung derselben Person beim selben Arbeitgeber und gleicher Art (für Folgebescheinigungen)."""
    rows = db.scalars(select(KrankReport).where(KrankReport.kind == kind, KrankReport.employer_id == employer_id)
                      .order_by(KrankReport.created_at.desc()).limit(300)).all()
    for r in rows:
        if r.id != exclude_id and _same_person(data(r), values):
            return data(r)
    return None


def validate(db, kind: str, form: dict, employer: KrankEmployer | None, has_file: bool) -> tuple[dict, list[str]]:
    """Prüft die Angaben eines Meldewegs. Gibt (Angaben, Hinweise) zurück oder löst ValueError aus."""
    if kind not in KINDS:
        raise ValueError("Unbekannter Meldeweg.")
    get = lambda k: str(form.get(k) or "").strip()  # noqa: E731
    values = {"first_name": get("first_name")[:100], "last_name": get("last_name")[:100], "email": get("email")[:200].lower()}
    if not values["first_name"] or not values["last_name"]:
        raise ValueError("Bitte Vor- und Nachnamen angeben.")
    if employer is None:
        raise ValueError("Bitte den Arbeitgeber auswählen.")
    if not employer.active:
        raise ValueError(f"Für „{employer.name}“ ist die digitale Meldung noch nicht freigeschaltet. "
                         "Bitte melden Sie sich bis auf Weiteres auf dem bisherigen Weg.")
    if values["email"] and not EMAIL_RE.match(values["email"]):
        raise ValueError("Die E-Mail-Adresse ist ungültig.")
    if employer.allow_remarks and get("remarks"):
        values["remarks"] = get("remarks")[:2000]
    warnings: list[str] = []
    now = today()

    if kind == "simple":
        if now.weekday() > 4:
            raise ValueError("Die einfache Krankmeldung ist nur montags bis freitags für den aktuellen Tag möglich.")
        values["date"] = now.isoformat()
        values["days"] = 1
        return values, warnings

    first = get("first") != "0"
    values["first"] = first

    if kind == "eau":
        if get("insured") == "private":
            raise ValueError("Privat Versicherte erhalten keine eAU. Bitte nutzen Sie die „Meldung mit AU“ und laden "
                             "Sie die Bescheinigung hoch.")
        values["personnel_no"] = get("personnel_no")[:40]
        start = parse_day(get("from"), "Arbeitsunfähig seit")
        end = parse_day(get("to"), "Voraussichtlich arbeitsunfähig bis")
        seen = parse_day(get("doctor"), "Festgestellt am")
        if start > end:
            raise ValueError("„Arbeitsunfähig seit“ darf nicht nach „voraussichtlich arbeitsunfähig bis“ liegen.")
        if seen > now:
            raise ValueError("„Festgestellt am“ darf nicht in der Zukunft liegen.")
        if seen > end:
            raise ValueError("„Festgestellt am“ darf nicht nach „voraussichtlich arbeitsunfähig bis“ liegen.")
        if first and start < seen - timedelta(days=3):
            warnings.append(f"Der AU-Beginn ({de(start)}) liegt mehr als drei Tage vor der Feststellung ({de(seen)}). "
                            "Eine Rückdatierung ist nur bis zu drei Tage zulässig – bitte die Daten mit dem Ausdruck abgleichen.")
        if first and seen < start:
            warnings.append(f"Festgestellt am ({de(seen)}) liegt vor dem AU-Beginn ({de(start)}) – bitte mit dem Ausdruck abgleichen.")
        if not first:
            prev = predecessor(db, "eau", employer.id, values)
            if prev is None:
                warnings.append("Keine vorherige eAU-Meldung dieser Person gefunden – bitte prüfen, ob „Folgebescheinigung“ stimmt.")
            else:
                if prev.get("from") and prev["from"] != start.isoformat():
                    warnings.append(f"Bei einer Folgebescheinigung bleibt „arbeitsunfähig seit“ der erste Tag der AU "
                                    f"(bisher gemeldet: {de(prev['from'])}, jetzt: {de(start)}).")
                if prev.get("to") and seen > date.fromisoformat(prev["to"]) + timedelta(days=1):
                    warnings.append(f"Mögliche Lücke: Die vorherige AU lief bis {de(prev['to'])}, die Folgebescheinigung "
                                    f"wurde am {de(seen)} festgestellt.")
        values.update({"from": start.isoformat(), "to": end.isoformat(), "doctor": seen.isoformat(),
                       "days": calendar_days(start, end)})
        return values, warnings

    # Meldung mit AU und Kind krank: Folgebescheinigung braucht kein Startdatum (aus der Vorgängermeldung)
    end = parse_day(get("to"), "bis")
    start = parse_day(get("from"), "von", required=False)
    prev = None if first else predecessor(db, kind, employer.id, values)
    if not first and start is None:
        if prev and prev.get("to"):
            start = date.fromisoformat(prev["to"]) + timedelta(days=1)
        elif kind == "child":
            raise ValueError("Keine vorherige Meldung gefunden – bitte das Startdatum angeben.")
    if first and start is None:
        raise ValueError("Bitte das Startdatum angeben.")
    if start and start > end:
        raise ValueError("Das Startdatum kann nicht nach dem Enddatum liegen.")
    if not first:
        if prev is None:
            warnings.append("Keine vorangehende Meldung gefunden. Bitte überprüfen Sie, ob „Folgebescheinigung“ korrekt ist.")
        elif start and prev.get("to") and start != date.fromisoformat(prev["to"]) + timedelta(days=1):
            expected = date.fromisoformat(prev["to"]) + timedelta(days=1)
            warnings.append(f"Datenlücke: Die vorherige Bescheinigung endet am {de(prev['to'])}, die Folgebescheinigung "
                            f"beginnt am {de(start)}. Erwartet: {de(expected)}.")
    values.update({"from": start.isoformat() if start else "", "to": end.isoformat(),
                   "days": calendar_days(start, end) if start else None})
    if kind == "au":
        doctor = parse_day(get("doctor"), "Feststellungsdatum", required=False)
        values["doctor"] = doctor.isoformat() if doctor else ""
        if not has_file:
            warnings.append("Es wurde keine Bescheinigung hochgeladen – bitte zeitnah nachreichen.")
    else:
        values["child_name"] = get("child_name")[:150]
        if not values["child_name"]:
            raise ValueError("Bitte den Namen des Kindes angeben.")
        dob = parse_day(get("child_dob"), "Geburtsdatum des Kindes", near=False) if get("child_dob") else None
        if dob is None:
            raise ValueError("Bitte das Geburtsdatum des Kindes angeben.")
        values["child_dob"] = dob.isoformat()
        if dob > now or dob.year < now.year - 30:
            raise ValueError("Das Geburtsdatum des Kindes ist nicht plausibel.")
        ref = start or end
        twelfth = date(dob.year + 12, dob.month, 28 if (dob.month, dob.day) == (2, 29) else dob.day)
        if ref >= twelfth:
            warnings.append("Das Kind hat das 12. Lebensjahr vollendet. Ein Anspruch nach § 45 SGB V besteht dann nur, "
                            "wenn das Kind behindert und auf Hilfe angewiesen ist.")
        if not has_file:
            warnings.append("Sie haben Ihrer Meldung keinen Nachweis beigefügt. Bitte reichen Sie den Nachweis zeitnah "
                            "über Ihre Statusseite nach.")
    return values, warnings


def rows(report: KrankReport) -> list[tuple[str, str]]:
    """Angaben zur Anzeige (Portal, PDF, Mail) als (Bezeichnung, Wert)."""
    d = data(report)
    out = [("Name", full_name(report)), ("Arbeitgeber", report.employer_name or "–")]
    if d.get("personnel_no"):
        out.append(("Personalnummer", d["personnel_no"]))
    out.append(("E-Mail (für Rückmeldungen)", d.get("email") or "nicht angegeben"))
    if report.kind == "simple":
        out.append(("Krank am", de(d.get("date"))))
    elif report.kind == "eau":
        out += [("Arbeitsunfähig seit", de(d.get("from"))), ("Voraussichtlich arbeitsunfähig bis", de(d.get("to"))),
                ("Festgestellt am", de(d.get("doctor"))),
                ("Bescheinigung", "Erstbescheinigung" if d.get("first", True) else "Folgebescheinigung")]
    else:
        out += [("Von", de(d.get("from")) if d.get("from") else "aus Vorgängermeldung"), ("Bis", de(d.get("to")))]
        if report.kind == "au" and d.get("doctor"):
            out.append(("Feststellungsdatum (Arzt)", de(d["doctor"])))
        out.append(("Bescheinigung", "Erstbescheinigung" if d.get("first", True) else "Folgebescheinigung"))
        if report.kind == "child":
            out += [("Kind", d.get("child_name") or "–"), ("Geburtsdatum des Kindes", de(d.get("child_dob")))]
    if d.get("days"):
        out.append(("Kalendertage", str(d["days"])))
    if d.get("remarks"):
        out.append(("Bemerkung", d["remarks"]))
    return out


def period(report: KrankReport) -> str:
    d = data(report)
    if report.kind == "simple":
        return de(d.get("date"))
    text = f"{de(d.get('from')) if d.get('from') else '…'} bis {de(d.get('to'))}"
    return text + (f" ({d['days']} Kalendertag{'e' if d['days'] != 1 else ''})" if d.get("days") else "")


# --- Anlegen, Status, Verlauf ----------------------------------------------------------------------------

def next_ref(db) -> str:
    cfg = get_settings(db)
    year = to_local(utcnow()).year
    seq = int(cfg.get("krank_seq") or 0) + 1 if str(year) == cfg.get("krank_seq_year") else 1
    set_setting(db, "krank_seq_year", str(year))
    set_setting(db, "krank_seq", str(seq))
    ref = f"KM-{year}-{seq:05d}"
    while db.scalar(select(KrankReport.id).where(KrankReport.ref_no == ref)) is not None:
        seq += 1
        set_setting(db, "krank_seq", str(seq))
        ref = f"KM-{year}-{seq:05d}"
    return ref


def add_event(report: KrankReport, kind: str, text: str, by: str = "", public: bool = False) -> KrankEvent:
    ev = KrankEvent(kind=kind, by=by[:255], public=public, text_enc=enc(text))
    report.events.append(ev)
    report.updated_at = utcnow()
    return ev


def audit(db, user: User | None, report: KrankReport | None, action: str, detail: str = "", ref_no: str = "") -> None:
    db.add(KrankAccess(ref_no=(report.ref_no if report else ref_no)[:30], user_id=user.id if user else None,
                       user_name=(user.name if user else "System")[:255], action=action[:30], detail=detail[:500]))


def initial_status(kind: str, has_file: bool) -> str:
    if kind == "eau":
        return "eau_open"
    if kind in ("au", "child") and not has_file:
        return "proof_missing"
    return "new"


def create(db, kind: str, form: dict, employer: KrankEmployer | None, upload: tuple[str, bytes] | None,
           user: User | None) -> tuple[KrankReport, str, list[str]]:
    """Meldung anlegen, Mails einreihen, ablegen. Gibt (Meldung, Statuslink-Token, Hinweise) zurück."""
    if kind in ("simple", "eau"):
        upload = None                      # bei diesen Meldewegen gibt es keinen Nachweis
    mime = check_upload(*upload) if upload else None
    values, warnings = validate(db, kind, form, employer, has_file=bool(upload))
    token = secrets.token_urlsafe(24)
    values["_track"] = token
    values["warnings"] = warnings
    if user is not None:
        values["by_user"] = user.email
    report = KrankReport(ref_no=next_ref(db), kind=kind, status=initial_status(kind, bool(upload)),
                         employer_id=employer.id, employer_name=employer.name, has_email=bool(values.get("email")),
                         track_hash=hash_token(token))
    if user is not None and user.krank_history:
        report.user_id = user.id
    set_data(report, values)
    db.add(report)
    db.flush()
    add_event(report, "status", f"Eingegangen ({kind_label(kind)}) – Stand: {status_label(report.status)}",
              by=user.name if user else "Online-Meldung", public=True)
    if upload:
        store_file(report, upload[0], upload[1], mime, "meldung")
    db.flush()
    cfg = get_settings(db)
    _mail_staff_new(db, report, cfg)
    if values.get("email"):
        _mail(db, cfg, values["email"], "krank_confirm", report)
    sync_dms(db, report)
    retention(db, report, cfg)
    return report, token, warnings


def allowed_statuses(report: KrankReport) -> tuple[str, ...]:
    return KIND_STATUSES.get(report.kind, ("new", "progress", "done"))


def set_status(db, report: KrankReport, status: str, user: User, note: str = "") -> bool:
    if status not in allowed_statuses(report) or status == report.status:
        return False
    old = report.status
    report.status, report.status_at = status, utcnow()
    if status == "done":
        report.processed_at, report.processed_by = utcnow(), user.name
    elif old == "done":
        report.processed_at, report.processed_by = None, ""
    add_event(report, "status", f"{status_label(old)} → {status_label(status)}" + (f"\n{note}" if note else ""),
              by=user.name, public=True)
    audit(db, user, report, "status", f"{status_label(old)} → {status_label(status)}")
    retention(db, report)
    sync_dms(db, report, final=status == "done")
    return True


def add_note(db, report: KrankReport, user: User, text: str) -> None:
    add_event(report, "note", text[:4000], by=user.name)
    audit(db, user, report, "notiz")


def message(db, report: KrankReport, user: User, text: str) -> bool:
    """Nachricht/Rückfrage an die meldende Person: auf der Statusseite sichtbar, per Mail, falls Adresse bekannt."""
    add_event(report, "message", text[:4000], by=user.name, public=True)
    audit(db, user, report, "nachricht")
    email = data(report).get("email")
    if email:
        _mail(db, get_settings(db), email, "krank_message", report, nachricht=text[:4000])
    return bool(email)


def employee_reply(db, report: KrankReport, text: str, upload: tuple[str, bytes] | None) -> None:
    """Antwort bzw. Nachweis über die Statusseite."""
    mime = check_upload(*upload) if upload else None
    parts = []
    if upload:
        f = store_file(report, upload[0], upload[1], mime, "nachgereicht")
        db.flush()
        add_event(report, "file", f"Nachweis nachgereicht: {file_name(f)}", by="meldende Person", public=True)
        parts.append("Nachweis nachgereicht")
        if report.status == "proof_missing":
            report.status, report.status_at = "new", utcnow()
            add_event(report, "status", f"{status_label('proof_missing')} → {status_label('new')}", by="System", public=True)
    if text.strip():
        add_event(report, "reply", text.strip()[:4000], by="meldende Person", public=True)
        parts.append("Antwort der meldenden Person")
    if not parts:
        raise ValueError("Bitte eine Datei auswählen oder eine Nachricht schreiben.")
    audit(db, None, report, "nachgereicht", ", ".join(parts))
    cfg = get_settings(db)
    for to in staff_recipients(db, report.employer, cfg):
        _mail(db, cfg, to, "krank_staff_update", report, ereignis=" und ".join(parts))
    sync_dms(db, report)


def add_staff_file(db, report: KrankReport, user: User, name: str, content: bytes) -> KrankFile:
    mime = check_upload(name, content)
    f = store_file(report, name, content, mime, "verwaltung")
    db.flush()
    add_event(report, "file", f"Datei hinzugefügt: {file_name(f)}", by=user.name)
    audit(db, user, report, "datei hinzugefügt", file_name(f))
    return f


def keep_for_user(db, report: KrankReport, user: User) -> None:
    """Meldung nachträglich unter „Meine Krankmeldungen“ führen."""
    if not user.krank_history:
        user.krank_history = True
    report.user_id = user.id


def forget_user(db, user: User) -> int:
    """„Meine Krankmeldungen“ ausschalten: Verknüpfungen lösen (die Meldungen selbst bleiben bei der Verwaltung)."""
    n = 0
    for r in db.scalars(select(KrankReport).where(KrankReport.user_id == user.id)):
        r.user_id = None
        n += 1
    user.krank_history = False
    return n


# --- Mails ---------------------------------------------------------------------------------------------

def staff_recipients(db, employer: KrankEmployer | None, cfg: dict[str, str]) -> list[str]:
    """Hinterlegte Adressen des Arbeitgebers, Portal-Zuständige (Personen und Gruppen), globale Kopie;
    ohne Empfänger die Adresse der Personalverwaltung aus den Einstellungen."""
    out: list[str] = []
    glob = (cfg.get("krank_global_email") or "").strip().lower()
    if employer is not None:
        out += [a.strip().lower() for a in re.split(r"[\s,;]+", employer.emails or "") if EMAIL_RE.match(a.strip())]
        for resp in employer.responsible:
            if resp.user is not None and resp.user.active:
                out.append(resp.user.email.lower())
            if resp.group is not None:
                out += [m.email.lower() for m in resp.group.members if m.active]
        if employer.send_global_copy and glob:
            out.append(glob)
    if not out and glob:
        out.append(glob)
    return list(dict.fromkeys(out))


def _values(db, report: KrankReport, cfg: dict[str, str]) -> dict[str, str]:
    d = data(report)
    prefix = (report.employer.subject_prefix if report.employer and report.employer.subject_prefix else "") \
        or cfg.get("krank_subject_prefix") or "Krankmeldung"
    return {"name": full_name(report), "art": kind_label(report.kind), "arbeitgeber": report.employer_name,
            "aktenzeichen": report.ref_no, "zeitraum": period(report),
            "eingang": to_local(report.created_at).strftime("%d.%m.%Y, %H:%M Uhr"),
            "angaben": "\n".join(f"{a}: {b}" for a, b in rows(report)),
            "hinweise": ("Hinweise:\n" + "\n".join(f"– {w}" for w in d.get("warnings", []))) if d.get("warnings") else "",
            "status": status_label(report.status), "status_link": status_link(db, report, cfg),
            "link": staff_link(report), "praefix": prefix}


def _mail(db, cfg: dict[str, str], to: str, key: str, report: KrankReport, attachments: list[dict] | None = None,
          **extra) -> bool:
    subject, body = mailtpl.render(db, key, _values(db, report, cfg) | extra, cfg)
    queued = notify.enqueue(db, to, subject, body, "krank", cfg, attachments=attachments)
    if queued:
        add_event(report, "mail", f"E-Mail „{mailtpl.TEMPLATES[key]['label']}“ an {to}", by="System")
    return queued


def _mail_staff_new(db, report: KrankReport, cfg: dict[str, str]) -> None:
    employer = report.employer
    full = bool(employer and employer.attach_files)
    attachments = None
    if full:
        try:
            attachments = [{"filename": f"{report.ref_no}.pdf", "mime": "application/pdf",
                            "content_b64": base64.b64encode(pdf(report)).decode()}]
        except Exception:  # noqa: BLE001  (Mail ohne PDF ist besser als keine Mail)
            log.exception("PDF für %s nicht erzeugt", report.ref_no)
    for to in staff_recipients(db, employer, cfg):
        _mail(db, cfg, to, "krank_staff_full" if full else "krank_staff_notice", report, attachments=attachments)


def purge_sent(n) -> None:
    """Nach dem Versand: Inhalt und Anhänge aus der Mail-Warteschlange entfernen (Gesundheitsdaten)."""
    n.body = "(Inhalt nach dem Versand aus Datenschutzgründen entfernt)"
    n.attachments_json = None


def send_proof_reminders() -> int:
    """Einmalige Erinnerung, wenn der Nachweis nach der eingestellten Zahl von Tagen noch fehlt."""
    n = 0
    with SessionLocal() as db:
        cfg = get_settings(db)
        if cfg.get("module_krank") != "1":
            return 0
        days = int(cfg.get("krank_proof_reminder_days") or 0)
        if days <= 0:
            return 0
        due = db.scalars(select(KrankReport).where(KrankReport.status == "proof_missing", KrankReport.has_email.is_(True),
                                                   KrankReport.proof_reminded_at.is_(None),
                                                   KrankReport.created_at < utcnow() - timedelta(days=days))).all()
        for report in due:
            email = data(report).get("email")
            if email and _mail(db, cfg, email, "krank_proof_reminder", report):
                n += 1
            report.proof_reminded_at = utcnow()
        db.commit()
    return n


# --- Löschfrist ---------------------------------------------------------------------------------------

def retention(db, report: KrankReport, cfg: dict[str, str] | None = None) -> None:
    days = int((cfg or get_settings(db)).get("krank_retention_days") or 0)
    report.delete_after = report.processed_at + timedelta(days=days) if days > 0 and report.processed_at else None


def recompute_retention(db) -> None:
    cfg = get_settings(db)
    for report in db.scalars(select(KrankReport).where(KrankReport.processed_at.is_not(None))):
        retention(db, report, cfg)


def delete_report(db, report: KrankReport, user: User | None, reason: str) -> None:
    audit(db, user, report, "gelöscht", reason)
    delete_files(report.id)
    db.delete(report)


def purge_expired() -> int:
    n = 0
    with SessionLocal() as db:
        for report in db.scalars(select(KrankReport).where(KrankReport.delete_after.is_not(None),
                                                           KrankReport.delete_after < utcnow())).all():
            delete_report(db, report, None, "Löschfrist abgelaufen")
            n += 1
        db.commit()
    if n:
        log.info("Krankmelder: %s Meldung(en) nach Ablauf der Löschfrist gelöscht", n)
    return n


# --- PDF ------------------------------------------------------------------------------------------------

def pdf(report: KrankReport) -> bytes:
    """Meldung als PDF; hochgeladene Nachweise (PDF, Bilder) werden angehängt."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from . import branding
    from .applications import _image_pdf, _latin, _stamp

    brand = branding.load()
    styles = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=13)
    small = ParagraphStyle("s", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    title = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19, spaceAfter=4)
    p = lambda text, st=base: Paragraph(escape(_latin(str(text))).replace("\n", "<br/>"), st)  # noqa: E731

    d = data(report)
    story = [p(f"{brand['name']} · Krankmelder", small), Spacer(1, 4 * mm), p(kind_label(report.kind), title)]
    meta = [("Aktenzeichen", report.ref_no), ("Eingang", to_local(report.created_at).strftime("%d.%m.%Y, %H:%M:%S Uhr")),
            ("Stand", status_label(report.status))]
    if report.processed_at:
        meta.append(("Bearbeitet", f"{to_local(report.processed_at).strftime('%d.%m.%Y, %H:%M')} von {report.processed_by}"))
    t = Table([[p(a, bold), p(b)] for a, b in meta], colWidths=[50 * mm, 115 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f4f7"))]))
    story += [t, Spacer(1, 6 * mm)]
    t = Table([[p(a, bold), p(b)] for a, b in rows(report)], colWidths=[60 * mm, 105 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d5dd"))]))
    story.append(t)
    if d.get("warnings"):
        story += [Spacer(1, 5 * mm), p("Prüfhinweise", bold)] + [p(f"– {w}") for w in d["warnings"]]
    attach = []
    for n, f in enumerate(report.files, start=1):
        content = read_file(f)
        entry = {"n": n, "name": file_name(f), "reader": None}
        try:
            if f.mime == "application/pdf":
                entry["reader"] = PdfReader(io.BytesIO(content))
                if entry["reader"].is_encrypted and not entry["reader"].decrypt(""):
                    entry["reader"] = None
            elif f.mime.startswith("image/"):
                entry["reader"] = PdfReader(io.BytesIO(_image_pdf(io.BytesIO(content), f"Anlage {n}: {entry['name']}")))
        except Exception:  # noqa: BLE001
            entry["reader"] = None
        attach.append(entry)
    if attach:
        story += [Spacer(1, 5 * mm), p("Anlagen", bold)]
        story += [p(f"{e['n']}. {e['name']}" + ("" if e["reader"] else " (nicht einbindbar – eigene Datei)")) for e in attach]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(20 * mm, 12 * mm, _latin(f"{report.ref_no} · {kind_label(report.kind)} · vertraulich (Gesundheitsdaten)"))
        canvas.drawRightString(190 * mm, 12 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=20 * mm, title=_latin(f"{report.ref_no} {kind_label(report.kind)}"),
                            author=_latin(brand["name"]), subject="Krankmeldung")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    if not any(e["reader"] for e in attach):
        return buf.getvalue()
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(buf.getvalue())))
    for e in attach:
        if not e["reader"]:
            continue
        total = len(e["reader"].pages)
        for i, page in enumerate(e["reader"].pages, start=1):
            added = writer.add_page(page)   # erst übernehmen, dann stempeln (pypdf 7 verlangt die Seite im Writer)
            try:
                w, h = float(added.mediabox.width), float(added.mediabox.height)
                added.merge_page(PdfReader(io.BytesIO(_stamp(f"{report.ref_no} · Anlage {e['n']} · Seite {i}/{total}", w, h))).pages[0])
            except Exception:  # noqa: BLE001
                pass
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# --- Ablage (DMS) -------------------------------------------------------------------------------------

def sync_dms(db, report: KrankReport, final: bool = False) -> None:
    """Optional je Arbeitgeber: Eintrag in der Ablage; bei „Bearbeitet“ zusätzlich das PDF als Abschlussstand.
    In der Ablage gelten deren Rechte und Löschfristen."""
    from . import dms
    employer = report.employer
    if employer is None or not employer.dms_enabled or not dms.enabled(db):
        return
    record = db.get(DmsRecord, report.dms_record_id) if report.dms_record_id else None
    if record is None:
        area_id = employer.dms_area_id if employer.dms_area_id and db.get(DmsArea, employer.dms_area_id) else dms.unsorted(db).id
        record = DmsRecord(area_id=area_id, kind="krank", received_at=report.created_at, created_by="Krankmelder")
        db.add(record)
        db.flush()
        report.dms_record_id = record.id
    record.title = f"{kind_label(report.kind)} {report.ref_no}"[:300]
    record.ref_no, record.form_title = report.ref_no, f"Krankmelder: {kind_label(report.kind)}"[:255]
    record.applicant, record.applicant_email = full_name(report)[:255], (data(report).get("email") or "")[:255]
    record.status = status_label(report.status)[:16]
    record.note = f"{report.employer_name} · {period(report)}"[:2000]
    record.text = " ".join([report.ref_no, full_name(report), report.employer_name, kind_label(report.kind)]).lower()
    if final and report.processed_at and not record.closed_at:
        record.closed_at = report.processed_at
        try:
            dms._store(record, f"{report.ref_no} {kind_label(report.kind)} (Abschlussstand).pdf", pdf(report), "abschluss",
                       "Krankmelder", f"Stand bei Bearbeitung am {to_local(report.processed_at).strftime('%d.%m.%Y %H:%M')}",
                       "application/pdf")
        except Exception:  # noqa: BLE001
            log.exception("PDF für die Ablage von %s nicht erzeugt", report.ref_no)
        by_id = {a.id: a for a in dms.areas(db)}
        area = by_id.get(record.area_id)
        record.retention_until = dms.retention_date(record.closed_at, dms.retention_years(area, by_id)) if area else None
    record.updated_at = utcnow()


# --- Liste, Export, Statistik ---------------------------------------------------------------------------

FILTERS = ("q", "kind", "status", "employer", "from", "to", "sort")


def search(db, user: User, f: dict) -> list[KrankReport]:
    q = reports_query(db, user)
    if f.get("kind") in KINDS:
        q = q.where(KrankReport.kind == f["kind"])
    if f.get("status") == "open":
        q = q.where(KrankReport.status != "done")
    elif f.get("status") in STATUSES:
        q = q.where(KrankReport.status == f["status"])
    if (f.get("employer") or "").isdigit():
        q = q.where(KrankReport.employer_id == int(f["employer"]))
    for key, op in (("from", ">="), ("to", "<")):
        try:
            day = date.fromisoformat(f.get(key) or "")
        except ValueError:
            continue
        local = datetime.combine(day + timedelta(days=1 if key == "to" else 0), datetime.min.time())
        from .db import LOCAL_TZ
        from datetime import timezone
        bound = local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        q = q.where(KrankReport.created_at >= bound if op == ">=" else KrankReport.created_at < bound)
    q = q.order_by(KrankReport.created_at.asc() if f.get("sort") == "old" else KrankReport.created_at.desc())
    items = db.scalars(q.limit(5000)).all()
    text = " ".join((f.get("q") or "").lower().split())
    if text:
        items = [r for r in items if all(word in f"{r.ref_no} {full_name(r)} {data(r).get('personnel_no', '')} "
                                         f"{data(r).get('child_name', '')}".lower() for word in text.split())]
    return items


CSV_HEAD = ["Aktenzeichen", "Eingang", "Art", "Status", "Arbeitgeber", "Nachname", "Vorname", "E-Mail", "Personalnummer",
            "Datum/von", "bis", "Kalendertage", "festgestellt am", "Bescheinigung", "Kind", "Geburtsdatum Kind",
            "Bemerkung", "Nachweise", "Bearbeitet am", "Bearbeitet von", "Hinweise"]


def csv_export(reports: list[KrankReport]) -> str:
    buf = io.StringIO()
    w = csvsafe.writer(buf, delimiter=";")
    w.writerow(CSV_HEAD)
    for r in reports:
        d = data(r)
        first = "" if r.kind == "simple" else ("Erstbescheinigung" if d.get("first", True) else "Folgebescheinigung")
        w.writerow([r.ref_no, to_local(r.created_at).strftime("%d.%m.%Y %H:%M"), kind_label(r.kind), status_label(r.status),
                    r.employer_name, d.get("last_name", ""), d.get("first_name", ""), d.get("email", ""),
                    d.get("personnel_no", ""), de(d.get("date") or d.get("from")) if (d.get("date") or d.get("from")) else "",
                    de(d.get("to")) if d.get("to") else "", d.get("days") or "", de(d.get("doctor")) if d.get("doctor") else "",
                    first, d.get("child_name", ""), de(d.get("child_dob")) if d.get("child_dob") else "",
                    d.get("remarks", ""), len(r.files),
                    to_local(r.processed_at).strftime("%d.%m.%Y %H:%M") if r.processed_at else "", r.processed_by,
                    " | ".join(d.get("warnings", []))])
    return "﻿" + buf.getvalue()


def stats(db, user: User) -> dict:
    reports = db.scalars(reports_query(db, user)).all()
    now_local = to_local(utcnow())
    day0 = now_local.date()
    week0 = day0 - timedelta(days=day0.weekday())
    created = [(r, to_local(r.created_at).date()) for r in reports]
    months = []
    y, m = day0.year, day0.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    per_month = {ym: 0 for ym in months}
    for _, d in created:
        if (d.year, d.month) in per_month:
            per_month[(d.year, d.month)] += 1
    by_employer: dict[str, int] = {}
    for r in reports:
        by_employer[r.employer_name or "–"] = by_employer.get(r.employer_name or "–", 0) + 1
    fb = db.execute(select(func.count(KrankFeedback.id), func.avg(KrankFeedback.rating))).one()
    dist = dict(db.execute(select(KrankFeedback.rating, func.count(KrankFeedback.id)).group_by(KrankFeedback.rating)).all())
    return {
        "total": len(reports),
        "today": sum(1 for _, d in created if d == day0),
        "week": sum(1 for _, d in created if d >= week0),
        "month": sum(1 for _, d in created if (d.year, d.month) == (day0.year, day0.month)),
        "year": sum(1 for _, d in created if d.year == day0.year),
        "open": sum(1 for r in reports if r.status in OPEN),
        "proof_missing": sum(1 for r in reports if r.status == "proof_missing"),
        "by_kind": {k: sum(1 for r in reports if r.kind == k) for k in KINDS},
        "by_status": {s: sum(1 for r in reports if r.status == s) for s in STATUSES},
        "by_employer": sorted(by_employer.items(), key=lambda x: -x[1]),
        "per_month": [(f"{m:02d}/{y % 100:02d}", per_month[(y, m)]) for y, m in months],
        "feedback_count": fb[0] or 0, "feedback_avg": round(float(fb[1]), 1) if fb[1] is not None else None,
        "feedback_dist": [(i, dist.get(i, 0)) for i in range(5, -1, -1)],
    }


def today_list(db, user: User) -> list[KrankReport]:
    start = datetime.combine(today(), datetime.min.time())
    from .db import LOCAL_TZ
    from datetime import timezone
    bound = start.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    return db.scalars(reports_query(db, user).where(KrankReport.created_at >= bound)
                      .order_by(KrankReport.created_at.desc())).all()


# --- Import aus dem eigenständigen Krankmelder ----------------------------------------------------------

TYPE_MAP = {"simple": "simple", "auscan": "au", "eau": "eau", "childcare": "child"}


def _old_dt(value) -> datetime:
    """Zeitstempel aus SQLite (CURRENT_TIMESTAMP = UTC, „YYYY-MM-DD HH:MM:SS“ oder ISO)."""
    text = str(value or "").strip().replace("T", " ").rstrip("Z")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return utcnow()


def _day(value) -> str:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def import_archive(db, archive: Path, user: User | None) -> dict:
    """Übernimmt Arbeitgeber, Empfänger, Einstellungen, Anleitung, Meldungen mit Dateien und Bewertungen aus
    einer ZIP-Datei mit krankmeldungen.db (und optional dem Ordner uploads/). Mehrfaches Importieren legt
    nichts doppelt an (Erkennung über die ursprüngliche Meldungsnummer)."""
    counts = {"employers": 0, "reports": 0, "skipped": 0, "files": 0, "missing_files": 0, "feedback": 0, "settings": 0}
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        db_member = next((m for m in members if PurePosixPath(m.filename).name == "krankmeldungen.db"), None)
        if db_member is None:
            raise ValueError("In der ZIP-Datei fehlt krankmeldungen.db (aus dem Ordner data/ des Krankmelders).")
        if db_member.file_size > 1024 ** 3 or sum(m.file_size for m in members) > 20 * 1024 **3:
            raise ValueError("Die ZIP-Datei ist entpackt zu groß (Datenbank höchstens 1 GB, insgesamt 20 GB).")
        uploads = {PurePosixPath(m.filename).name: m for m in members
                   if "uploads" in PurePosixPath(m.filename).parts[:-1] and m.file_size <= 50 * 1024 * 1024}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "krank.db"
            with zf.open(db_member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            try:
                _import_rows(db, con, zf, uploads, counts, user)
            finally:
                con.close()
    audit(db, user, None, "import", json.dumps(counts, ensure_ascii=False), ref_no="Import")
    return counts


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _import_rows(db, con, zf, uploads, counts, user) -> None:
    tables = _tables(con)
    cfg = get_settings(db)
    by_name = {e.name: e for e in employers(db)}
    if "employers" in tables:
        cols = {r[1] for r in con.execute("PRAGMA table_info('employers')")}
        for row in con.execute("SELECT * FROM employers"):
            name = str(row["name"] or "").strip()[:200]
            if not name or name in by_name:
                continue
            emp = KrankEmployer(name=name, active=bool(row["active"]) if "active" in cols else True,
                                color=(row["color"] if "color" in cols and re.fullmatch(r"#[0-9A-Fa-f]{6}", str(row["color"] or "")) else "#3B82F6"),
                                position=int(row["sort_order"] or 0) if "sort_order" in cols else len(by_name))
            db.add(emp)
            by_name[name] = emp
            counts["employers"] += 1
    if "employer_settings" in tables:
        cols = {r[1] for r in con.execute("PRAGMA table_info('employer_settings')")}
        for row in con.execute("SELECT * FROM employer_settings"):
            emp = by_name.get(str(row["employer"] or "").strip())
            if emp is None:
                emp = KrankEmployer(name=str(row["employer"]).strip()[:200], position=len(by_name))
                db.add(emp)
                by_name[emp.name] = emp
                counts["employers"] += 1
            addrs = []
            if "sb_emails" in cols and row["sb_emails"]:
                try:
                    addrs = [a for a in json.loads(row["sb_emails"]) if isinstance(a, str)]
                except ValueError:
                    addrs = []
            if not addrs and "sb_email" in cols and row["sb_email"]:
                addrs = [row["sb_email"]]
            if not emp.emails and addrs:
                emp.emails = "\n".join(a.strip() for a in addrs if EMAIL_RE.match(a.strip()))
            if "send_global_copy" in cols:
                emp.send_global_copy = bool(row["send_global_copy"])
            if "requires_remarks" in cols:
                emp.allow_remarks = bool(row["requires_remarks"])
            if "subject_prefix" in cols and row["subject_prefix"] and not emp.subject_prefix:
                emp.subject_prefix = str(row["subject_prefix"])[:100]
    db.flush()
    if "global_settings" in tables:
        old = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM global_settings")}
        if old.get("SB_EMAIL") and not cfg.get("krank_global_email") and EMAIL_RE.match(old["SB_EMAIL"].strip()):
            set_setting(db, "krank_global_email", old["SB_EMAIL"].strip().lower())
            counts["settings"] += 1
        if old.get("EMAIL_SUBJECT_PREFIX"):
            set_setting(db, "krank_subject_prefix", old["EMAIL_SUBJECT_PREFIX"][:100])
            counts["settings"] += 1
        if old.get("PUBLIC_PASSWORD") and not cfg.get("krank_password_hash"):
            set_password(db, old["PUBLIC_PASSWORD"])
            counts["settings"] += 1
        if old.get("PUBLIC_ACCESS_TOKEN") and not cfg.get("krank_access_token_enc"):
            from .security import encrypt
            set_setting(db, "krank_access_token_enc", encrypt(old["PUBLIC_ACCESS_TOKEN"]))
            counts["settings"] += 1
        if old.get("NEXT_PUBLIC_APP_NAME") and cfg.get("krank_title") in ("", "Krankmeldung"):
            set_setting(db, "krank_title", old["NEXT_PUBLIC_APP_NAME"][:120])
    if "cms_content" in tables and not cfg.get("krank_text_instructions"):
        row = con.execute("SELECT content FROM cms_content WHERE slug = 'instructions'").fetchone()
        if row and row[0]:
            set_setting(db, "krank_text_instructions", str(row[0])[:50000])
            counts["settings"] += 1
    if "submissions" in tables:
        scans: dict[int, list] = {}
        if "au_scans" in tables:
            for s in con.execute("SELECT * FROM au_scans"):
                scans.setdefault(int(s["submission_id"]), []).append(s)
        days = int(get_settings(db).get("krank_retention_days") or 0)
        for row in con.execute("SELECT * FROM submissions ORDER BY id"):
            key = f"krankmelder:{row['id']}:{row['created_at']}"[:80]
            if db.scalar(select(KrankReport.id).where(KrankReport.import_key == key)) is not None:
                counts["skipped"] += 1
                continue
            try:
                old = json.loads(row["data_json"] or "{}")
            except ValueError:
                old = {}
            kind = TYPE_MAP.get(str(row["type"] or old.get("type") or ""), "simple")
            emp = by_name.get(str(old.get("employer") or "").strip())
            first = old.get("is_first_cert", old.get("is_first_submission", True))
            values = {"first_name": str(old.get("employee_vorname") or "")[:100],
                      "last_name": str(old.get("employee_name") or row["employee_name"] or "")[:100],
                      "email": str(old.get("employee_email") or row["employee_email"] or "")[:200].lower(),
                      "personnel_no": str(old.get("employee_id") or "")[:40],
                      "first": first not in (False, "false", 0, "0"),
                      "remarks": str(old.get("remarks") or "")[:2000],
                      "warnings": [w for w in (old.get("validation_warning"), row["error_message"] if "error_message" in row.keys() else None) if w],
                      "_track": secrets.token_urlsafe(24)}
            if kind == "simple":
                values["date"] = _day(old.get("date"))
                values["days"] = 1
            else:
                values.update({"from": _day(old.get("from_date")), "to": _day(old.get("to_date")),
                               "doctor": _day(old.get("doctor_date")), "days": old.get("days_count") or None})
            if kind == "child":
                values.update({"child_name": str(old.get("child_name") or "")[:150], "child_dob": _day(old.get("child_dob"))})
            created = _old_dt(row["created_at"])
            processed = row["status"] == "processed" if "status" in row.keys() else False
            status = "done" if processed else ("eau_open" if kind == "eau" else "new")
            report = KrankReport(ref_no=next_ref(db), kind=kind, status=status, status_at=created,
                                 employer_id=emp.id if emp else None, employer_name=emp.name if emp else str(old.get("employer") or "")[:200],
                                 has_email=bool(values["email"]), track_hash=hash_token(values["_track"]), import_key=key,
                                 created_at=created, updated_at=created)
            if processed:
                report.processed_at = _old_dt(row["processed_at"]) if "processed_at" in row.keys() and row["processed_at"] else created
                report.processed_by = str(row["processed_by"] or "Krankmelder")[:255] if "processed_by" in row.keys() else "Krankmelder"
                if days > 0:
                    report.delete_after = report.processed_at + timedelta(days=days)
            set_data(report, values)
            db.add(report)
            db.flush()
            add_event(report, "system", f"Übernommen aus dem Krankmelder (Meldung #{row['id']})", by=user.name if user else "Import")
            report.events[-1].at = created
            for s in scans.get(int(row["id"]), []):
                member = uploads.get(PurePosixPath(str(s["file_path"] or "").replace("\\", "/")).name)
                if member is None:
                    counts["missing_files"] += 1
                    continue
                content = zf.read(member)
                mime = sniff_mime(content[:16])
                if mime is None:
                    counts["missing_files"] += 1
                    continue
                store_file(report, str(s["file_name"] or member.filename), content, mime, "import")
                counts["files"] += 1
            counts["reports"] += 1
            if counts["reports"] % 200 == 0:
                db.flush()
    if "feedback" in tables:
        existing = db.scalar(select(func.count(KrankFeedback.id))) or 0
        if existing == 0:
            for row in con.execute("SELECT rating, note, created_at FROM feedback"):
                try:
                    rating = int(row["rating"])
                except (TypeError, ValueError):
                    continue
                if 0 <= rating <= 5:
                    db.add(KrankFeedback(rating=rating, note=str(row["note"] or "")[:1000], created_at=_old_dt(row["created_at"])))
                    counts["feedback"] += 1


def status_link_path(report: KrankReport) -> str:
    """Relativer Pfad zur Statusseite (für Seiten im Portal)."""
    token = data(report).get("_track", "")
    return f"/krank/s/{token}" if token else "/krank"
