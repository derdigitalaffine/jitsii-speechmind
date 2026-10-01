"""Bearbeitbare E-Mail-Vorlagen.

Jede Vorlage hat Betreff und Text mit Platzhaltern in geschweiften Klammern, z. B. {name}.
Unbekannte Platzhalter bleiben unverändert stehen (kein Absturz bei Tippfehlern).
Eigene Fassungen liegen in den Einstellungen unter tpl_<schlüssel>_subject/_body;
leer bedeutet: Standardtext verwenden.
"""

import re

from . import branding
from .config import settings
from .db import get_settings

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

COMMON_VARS = {
    "organisation": "Name der Organisation",
    "produkt": "Produktbezeichnung",
    "portal_link": "Adresse des Portals",
    "fusszeile": "Standard-Signatur (Produkt, Organisation, Portal-Adresse)",
}

_MEETING_VARS = {
    "name": "Name der eingeladenen Person",
    "titel": "Titel der Besprechung",
    "datum": "Datum, z. B. Donnerstag, 01.10.2026",
    "uhrzeit": "Uhrzeit, z. B. 10:00–11:00 Uhr",
    "dauer": "Dauer, z. B. 60 Minuten",
    "link": "Einwahllink zur Konferenz",
    "beschreibung": "Beschreibung bzw. Tagesordnung",
    "organisator": "Name der planenden Person",
    "organisator_email": "E-Mail der planenden Person",
}

_RECORDING_VARS = {
    "aufnahme": "Bezeichnung der Aufnahme (Meeting, Datum, Uhrzeit)",
    "link": "Link zur Aufnahme im Portal",
    "fehler": "Fehlermeldung (nur bei Fehlern)",
}

TEMPLATES: dict[str, dict] = {
    "account_invite": {
        "group": "Konten", "label": "Einladung zum Konto",
        "vars": {"name": "Name der Person", "email": "E-Mail-Adresse (Benutzername)",
                 "link": "Link zum Festlegen des Passworts", "gueltig_stunden": "Gültigkeit des Links in Stunden"},
        "subject": "Einladung zum {produkt} der {organisation}",
        "body": ("Guten Tag {name},\n\n"
                 "für Sie wurde ein Konto im {produkt} der {organisation} angelegt. "
                 "Über den folgenden Link legen Sie Ihr Passwort fest und melden sich an:\n\n{link}\n\n"
                 "Der Link ist {gueltig_stunden} Stunden gültig und kann nur einmal verwendet werden.\n"
                 "Ihr Benutzername ist Ihre E-Mail-Adresse: {email}\n\n{fusszeile}"),
    },
    "password_reset": {
        "group": "Konten", "label": "Passwort zurücksetzen",
        "vars": {"name": "Name der Person", "email": "E-Mail-Adresse",
                 "link": "Link zum Festlegen des Passworts", "gueltig_stunden": "Gültigkeit des Links in Stunden"},
        "subject": "Passwort zurücksetzen – {produkt}",
        "body": ("Guten Tag {name},\n\n"
                 "für Ihr Konto wurde das Zurücksetzen des Passworts angefordert. Über diesen Link "
                 "vergeben Sie ein neues Passwort:\n\n{link}\n\n"
                 "Der Link ist {gueltig_stunden} Stunden gültig. Haben Sie das nicht angefordert, "
                 "können Sie diese Nachricht ignorieren.\n\n{fusszeile}"),
    },
    "meeting_invite": {
        "group": "Besprechungen", "label": "Einladung zur Besprechung",
        "vars": _MEETING_VARS,
        "subject": "Einladung: {titel} – {datum}, {uhrzeit}",
        "body": ("Guten Tag {name},\n\n"
                 "{organisator} lädt Sie zur Videokonferenz „{titel}“ ein.\n\n"
                 "Wann:      {datum}, {uhrzeit}\n"
                 "Einwahl:   {link}\n\n"
                 "{beschreibung}\n\n"
                 "So nehmen Sie teil: Öffnen Sie kurz vor Beginn den Einwahllink im Browser "
                 "(Chrome, Edge, Firefox oder Safari). Eine Installation ist nicht nötig.\n"
                 "Der Termin hängt als Kalendereintrag an dieser Mail.\n\n{fusszeile}"),
    },
    "meeting_update": {
        "group": "Besprechungen", "label": "Geänderte Besprechung",
        "vars": _MEETING_VARS,
        "subject": "Geändert: {titel} – {datum}, {uhrzeit}",
        "body": ("Guten Tag {name},\n\n"
                 "die Videokonferenz „{titel}“ wurde geändert. Es gilt jetzt:\n\n"
                 "Wann:      {datum}, {uhrzeit}\n"
                 "Einwahl:   {link}\n\n"
                 "{beschreibung}\n\n"
                 "Der aktualisierte Kalendereintrag hängt an dieser Mail.\n\n{fusszeile}"),
    },
    "meeting_cancel": {
        "group": "Besprechungen", "label": "Abgesagte Besprechung",
        "vars": _MEETING_VARS,
        "subject": "Abgesagt: {titel} – {datum}, {uhrzeit}",
        "body": ("Guten Tag {name},\n\n"
                 "die Videokonferenz „{titel}“ am {datum}, {uhrzeit} wurde abgesagt.\n"
                 "Der Termin wird aus Ihrem Kalender entfernt, wenn Sie die angehängte Absage übernehmen.\n\n"
                 "{fusszeile}"),
    },
    "recording_new": {
        "group": "Aufnahmen", "label": "Neue Aufnahme liegt vor",
        "vars": _RECORDING_VARS,
        "subject": "Neue Aufnahme: {aufnahme}",
        "body": ("Die Aufnahme „{aufnahme}“ ist abgeschlossen und liegt als MP3 vor.\n\n"
                 "Dort können Sie die MP3 herunterladen oder die Transkription in SpeechMind starten:\n"
                 "{link}\n\n{fusszeile}"),
    },
    "recording_done": {
        "group": "Aufnahmen", "label": "Transkript fertig",
        "vars": _RECORDING_VARS,
        "subject": "Transkript fertig: {aufnahme}",
        "body": "SpeechMind hat die Aufnahme „{aufnahme}“ verarbeitet.\n\nProtokoll und Wortlaut:\n{link}\n\n{fusszeile}",
    },
    "recording_failed": {
        "group": "Aufnahmen", "label": "Verarbeitung fehlgeschlagen",
        "vars": _RECORDING_VARS,
        "subject": "Transkription fehlgeschlagen: {aufnahme}",
        "body": ("Bei der Aufnahme „{aufnahme}“ ist ein Fehler aufgetreten:\n\n{fehler}\n\n"
                 "Details und erneuter Versuch:\n{link}\n\n{fusszeile}"),
    },
    "recording_silent": {
        "group": "Aufnahmen", "label": "Aufnahme ohne Ton",
        "vars": _RECORDING_VARS,
        "subject": "Aufnahme ohne Ton: {aufnahme}",
        "body": "Die Aufnahme „{aufnahme}“ enthält keinen hörbaren Ton.\n\n{fehler}\n\nDetails:\n{link}\n\n{fusszeile}",
    },
}

SAMPLE = {
    "name": "Erika Mustermann", "email": "erika.mustermann@example.org", "link": "https://meet.example.org/teamrunde",
    "gueltig_stunden": "72", "titel": "Teamrunde Bauamt", "datum": "Donnerstag, 01.10.2026",
    "uhrzeit": "10:00–11:00 Uhr", "dauer": "60 Minuten",
    "beschreibung": "Tagesordnung:\n1. Bericht\n2. Termine", "organisator": "Max Muster",
    "organisator_email": "max.muster@example.org", "aufnahme": "Teamrunde Bauamt, 01.10.2026 10:00 Uhr",
    "fehler": "Beispiel einer Fehlermeldung",
}


def common_vars() -> dict[str, str]:
    b = branding.load()
    return {
        "organisation": b["name"], "produkt": b["product"], "portal_link": settings.portal_base_url,
        "fusszeile": f"--\n{b['product']} der {b['name']}\n{settings.portal_base_url}",
    }


def fill(text: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def current(cfg: dict[str, str], key: str) -> tuple[str, str]:
    """Aktueller Betreff und Text (eigene Fassung oder Standard)."""
    t = TEMPLATES[key]
    return (cfg.get(f"tpl_{key}_subject") or t["subject"], cfg.get(f"tpl_{key}_body") or t["body"])


def render(db, key: str, values: dict[str, str], cfg: dict[str, str] | None = None) -> tuple[str, str]:
    subject, body = current(cfg or get_settings(db), key)
    data = {**common_vars(), **{k: ("" if v is None else str(v)) for k, v in values.items()}}
    # Betreff ist eine Zeile; überflüssige Leerzeilen im Text (z. B. leere Beschreibung) zusammenziehen
    subject = " ".join(fill(subject, data).split())
    body = re.sub(r"\n{3,}", "\n\n", fill(body, data)).strip() + "\n"
    return subject, body
