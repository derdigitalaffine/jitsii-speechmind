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
    "link": "Persönlicher Einwahllink der Person",
    "beschreibung": "Beschreibung bzw. Tagesordnung",
    "organisator": "Name der planenden Person",
    "organisator_email": "E-Mail der planenden Person",
    "antwort_link": "Link zum Zu- oder Absagen im Browser (funktioniert in jedem Mailprogramm)",
}

_RECORDING_VARS = {
    "aufnahme": "Bezeichnung der Aufnahme (Meeting, Datum, Uhrzeit)",
    "link": "Link zur Aufnahme im Portal",
    "fehler": "Fehlermeldung (nur bei Fehlern)",
}

_FORM_VARS = {
    "name": "Name der eingeladenen Person",
    "titel": "Titel des Formulars",
    "beschreibung": "Beschreibung des Formulars",
    "link": "Persönlicher Link zum Ausfüllen",
    "absender": "Name der Person, die einlädt",
    "frist": "Hinweis auf die Frist (leer, wenn keine gesetzt ist)",
}

_APP_VARS = {
    "titel": "Bezeichnung des Antrags",
    "aktenzeichen": "Aktenzeichen, z. B. GEW-2026-00042",
    "status": "Aktueller Stand, z. B. In Bearbeitung",
    "status_link": "Link, unter dem die antragstellende Person den Stand sieht und antwortet",
    "link": "Link zum Antrag im Portal (für die Verwaltung)",
    "zeitpunkt": "Eingang des Antrags",
    "frist": "Bearbeitungsfrist",
    "zustaendig": "Zuständige Person, Gruppe oder Postfach",
}

_POLL_VARS = {
    "name": "Name der eingeladenen Person",
    "titel": "Titel der Umfrage",
    "beschreibung": "Beschreibung",
    "ort": "Ort bzw. Hinweis zum Ort",
    "link": "Persönlicher Link zur Abstimmung",
    "absender": "Name der planenden Person",
    "frist": "Hinweis auf die Frist (leer, wenn keine gesetzt ist)",
    "vorschlaege": "Anzahl der Terminvorschläge",
}

_BOOKING_VARS = {
    "name": "Name des Gastes",
    "titel": "Titel der Buchungsseite",
    "termin": "Termin, z. B. Dienstag, 13.10.2026, 09:00–09:30 Uhr",
    "ort": "Ort (leer bei Videokonferenz)",
    "videolink": "Persönlicher Einwahllink (nur bei Videokonferenz)",
    "verwalten": "Link zum Verschieben oder Absagen",
    "absagefrist": "Bis wann vorher abgesagt werden kann",
    "hinweis": "Zusatztext der Buchungsseite",
    "anbieter": "Name der anbietenden Person",
}

_BOOKING_INVITE_VARS = {
    "name": "Name der eingeladenen Person",
    "titel": "Titel der Buchungsseite",
    "beschreibung": "Beschreibung",
    "link": "Persönlicher Link zur Terminauswahl",
    "absender": "Name der einladenden Person",
    "zeitraum": "Zeitraum der freien Termine",
    "dauer": "Dauer eines Termins",
    "ort": "Ort bzw. Hinweis auf Videokonferenz",
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
    "login_code": {
        "group": "Konten", "label": "Anmeldecode (Zwei-Faktor per E-Mail)",
        "vars": {"name": "Name der Person", "code": "Sechsstelliger Einmalcode", "minuten": "Gültigkeit in Minuten"},
        "subject": "Ihr Anmeldecode: {code}",
        "body": ("Guten Tag {name},\n\n"
                 "Ihr Code für die Anmeldung im {produkt} lautet:\n\n    {code}\n\n"
                 "Er ist {minuten} Minuten gültig und kann nur einmal verwendet werden. Haben Sie sich nicht gerade "
                 "angemeldet, ändern Sie bitte Ihr Passwort – jemand kennt es.\n\n{fusszeile}"),
    },
    "meeting_invite": {
        "group": "Besprechungen", "label": "Einladung zur Besprechung",
        "vars": _MEETING_VARS,
        "subject": "Einladung: {titel} – {datum}, {uhrzeit}",
        "body": ("Guten Tag {name},\n\n"
                 "{organisator} lädt Sie zur Videokonferenz „{titel}“ ein.\n\n"
                 "Wann:      {datum}, {uhrzeit}\n"
                 "Einwahl:   {link}\n"
                 "(persönlicher Link, bitte nicht weitergeben)\n\n"
                 "Zu- oder absagen: {antwort_link}\n\n"
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
                 "Bitte antworten Sie erneut: {antwort_link}\n\n"
                 "{beschreibung}\n\n"
                 "Der aktualisierte Kalendereintrag hängt an dieser Mail.\n\n{fusszeile}"),
    },
    "meeting_cancel": {
        "group": "Besprechungen", "label": "Abgesagte Besprechung",
        "vars": {**_MEETING_VARS, "nachricht": "Optionale Nachricht der planenden Person zur Absage"},
        "subject": "Abgesagt: {titel} – {datum}, {uhrzeit}",
        "body": ("Guten Tag {name},\n\n"
                 "die Videokonferenz „{titel}“ am {datum}, {uhrzeit} wurde abgesagt.\n"
                 "Der Termin wird aus Ihrem Kalender entfernt, wenn Sie die angehängte Absage übernehmen.\n\n"
                 "{nachricht}\n\n"
                 "{fusszeile}"),
    },
    "meeting_rsvp": {
        "group": "Besprechungen", "label": "Antwort auf Einladung (an die planende Person)",
        "vars": {"name": "Name der planenden Person", "teilnehmer": "Name und Adresse der antwortenden Person",
                 "antwort": "Zugesagt, Abgesagt, Mit Vorbehalt …", "kommentar": "Kommentar aus der Antwort",
                 "titel": "Titel der Besprechung", "datum": "Datum", "uhrzeit": "Uhrzeit",
                 "stand": "Übersicht aller Antworten", "link": "Link zur Besprechung im Portal"},
        "subject": "{antwort}: {teilnehmer} – {titel}",
        "body": ("Guten Tag {name},\n\n"
                 "{teilnehmer} hat auf Ihre Einladung zu „{titel}“ ({datum}, {uhrzeit}) geantwortet: {antwort}.\n\n"
                 "{kommentar}\n\n"
                 "Stand der Antworten: {stand}\n"
                 "Übersicht: {link}\n\n{fusszeile}"),
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
    "form_invite": {
        "group": "Formulare", "label": "Einladung zum Ausfüllen",
        "vars": _FORM_VARS,
        "subject": "Bitte ausfüllen: {titel}",
        "body": ("Guten Tag {name},\n\n"
                 "{absender} bittet Sie, das Formular „{titel}“ auszufüllen.\n\n"
                 "{beschreibung}\n\n"
                 "Zum Formular (persönlicher Link):\n{link}\n\n"
                 "{frist}\n\n{fusszeile}"),
    },
    "form_reminder": {
        "group": "Formulare", "label": "Erinnerung zum Ausfüllen",
        "vars": _FORM_VARS,
        "subject": "Erinnerung: {titel}",
        "body": ("Guten Tag {name},\n\n"
                 "das Formular „{titel}“ ist noch nicht ausgefüllt. Hier geht es direkt dazu:\n{link}\n\n"
                 "{frist}\n\n{fusszeile}"),
    },
    "form_response": {
        "group": "Formulare", "label": "Neue Antwort (an die Verantwortlichen)",
        "vars": {"titel": "Titel des Formulars", "nummer": "Laufende Nummer der Antwort",
                 "zeitpunkt": "Eingang der Antwort", "von": "Wer geantwortet hat (oder „anonym“)",
                 "antworten": "Die Antworten als Text (abschaltbar in den Formular-Einstellungen)",
                 "anzahl": "Anzahl aller Antworten", "link": "Link zur Antwort im Portal"},
        "subject": "Neue Antwort Nr. {nummer}: {titel}",
        "body": ("Zum Formular „{titel}“ ist eine neue Antwort eingegangen ({zeitpunkt}, von {von}).\n\n"
                 "{antworten}\n\n"
                 "Antworten insgesamt: {anzahl}\nIm Portal ansehen: {link}\n\n{fusszeile}"),
    },
    "form_confirmation": {
        "group": "Formulare", "label": "Eingangsbestätigung (an die ausfüllende Person)",
        "vars": {"name": "Name der Person", "titel": "Titel des Formulars", "zeitpunkt": "Eingang der Antwort",
                 "antworten": "Kopie der Antworten als Text"},
        "subject": "Eingangsbestätigung: {titel}",
        "body": ("Guten Tag {name},\n\n"
                 "vielen Dank, Ihre Angaben zum Formular „{titel}“ sind am {zeitpunkt} eingegangen. "
                 "Zur Kontrolle eine Kopie:\n\n{antworten}\n\n{fusszeile}"),
    },
    "poll_invite": {
        "group": "Terminumfragen", "label": "Einladung zur Terminumfrage",
        "vars": _POLL_VARS,
        "subject": "Terminumfrage: {titel}",
        "body": ("Guten Tag {name},\n\n"
                 "{absender} sucht einen Termin für „{titel}“ und bittet Sie, anzugeben, wann Sie können "
                 "({vorschlaege} Vorschläge).\n\n{beschreibung}\n\n"
                 "Zur Abstimmung (persönlicher Link, Ihre Antwort lässt sich später ändern):\n{link}\n\n"
                 "{frist}\n\n{fusszeile}"),
    },
    "poll_reminder": {
        "group": "Terminumfragen", "label": "Erinnerung zur Terminumfrage",
        "vars": _POLL_VARS,
        "subject": "Erinnerung: Terminumfrage {titel}",
        "body": ("Guten Tag {name},\n\n"
                 "für die Terminumfrage „{titel}“ fehlt noch Ihre Antwort. Hier geht es direkt dazu:\n{link}\n\n"
                 "{frist}\n\n{fusszeile}"),
    },
    "poll_vote": {
        "group": "Terminumfragen", "label": "Neue Antwort (an die planende Person)",
        "vars": {"name": "Name der planenden Person", "titel": "Titel der Umfrage",
                 "teilnehmer": "Name und Adresse der antwortenden Person", "aktion": "„hat abgestimmt“ oder „hat die Antwort geändert“",
                 "antworten": "Antworten je Termin", "kommentar": "Kommentar der Person",
                 "stand": "Termine mit den meisten Zusagen", "anzahl": "Anzahl Antworten",
                 "link": "Link zur Umfrage im Portal"},
        "subject": "{teilnehmer} {aktion}: {titel}",
        "body": ("Guten Tag {name},\n\n{teilnehmer} {aktion} („{titel}“):\n\n{antworten}\n\n{kommentar}\n\n"
                 "Bisher {anzahl} Antwort(en). Am besten passt: {stand}\n\nÜbersicht: {link}\n\n{fusszeile}"),
    },
    "poll_final": {
        "group": "Terminumfragen", "label": "Termin steht fest (an die Teilnehmenden)",
        "vars": {**_POLL_VARS, "termin": "Der festgelegte Termin"},
        "subject": "Termin steht fest: {titel} – {termin}",
        "body": ("Guten Tag {name},\n\n"
                 "vielen Dank fürs Abstimmen. Für „{titel}“ steht der Termin fest:\n\n    {termin}\n\n"
                 "{ort}\n\nDen Termin können Sie mit der angehängten Datei in Ihren Kalender übernehmen.\n\n"
                 "{fusszeile}"),
    },
    "booking_confirm": {
        "group": "Terminbuchung", "label": "Buchungsbestätigung (an den Gast)",
        "vars": _BOOKING_VARS,
        "subject": "Terminbestätigung: {titel} – {termin}",
        "body": ("Guten Tag {name},\n\nvielen Dank für Ihre Buchung. Ihr Termin:\n\n    {termin}\n\n"
                 "{ort}\n\n{videolink}\n\n{hinweis}\n\n"
                 "Mit der angehängten Datei übernehmen Sie den Termin in Ihren Kalender.\n"
                 "Termin verschieben oder absagen (bis {absagefrist} vorher):\n{verwalten}\n\n{fusszeile}"),
    },
    "booking_update": {
        "group": "Terminbuchung", "label": "Termin verschoben (an den Gast)",
        "vars": _BOOKING_VARS,
        "subject": "Termin verschoben: {titel} – {termin}",
        "body": ("Guten Tag {name},\n\nIhr Termin wurde verschoben. Neuer Termin:\n\n    {termin}\n\n"
                 "{ort}\n\n{videolink}\n\nDer Kalendereintrag im Anhang ersetzt den bisherigen.\n"
                 "Verschieben oder absagen: {verwalten}\n\n{fusszeile}"),
    },
    "booking_cancelled": {
        "group": "Terminbuchung", "label": "Termin abgesagt (an den Gast)",
        "vars": {**_BOOKING_VARS, "wer": "„Sie haben“ oder „<Anbieter> hat“", "grund": "Begründung (falls angegeben)"},
        "subject": "Abgesagt: {titel} – {termin}",
        "body": ("Guten Tag {name},\n\n{wer} den Termin am {termin} abgesagt.\n\n{grund}\n\n"
                 "Mit der angehängten Datei wird der Termin aus Ihrem Kalender entfernt.\n\n{fusszeile}"),
    },
    "booking_reminder": {
        "group": "Terminbuchung", "label": "Erinnerung an den Termin (an den Gast)",
        "vars": _BOOKING_VARS,
        "subject": "Erinnerung: {titel} – {termin}",
        "body": ("Guten Tag {name},\n\nwir erinnern an Ihren Termin:\n\n    {termin}\n\n{ort}\n\n{videolink}\n\n"
                 "Falls Sie nicht kommen können: {verwalten}\n\n{fusszeile}"),
    },
    "booking_owner": {
        "group": "Terminbuchung", "label": "Neue Buchung, Verschiebung, Absage (an die anbietende Person)",
        "vars": {"name": "Name der anbietenden Person", "ereignis": "Neue Buchung, Termin verschoben oder Absage",
                 "titel": "Titel der Buchungsseite", "termin": "Termin", "gast": "Name, E-Mail und Telefon des Gastes",
                 "nachricht": "Nachricht des Gastes", "frei": "Noch freie Plätze", "link": "Link zur Buchungsseite im Portal"},
        "subject": "{ereignis}: {gast} – {termin}",
        "body": ("Guten Tag {name},\n\n{ereignis} für „{titel}“:\n\n    {termin}\n    {gast}\n\n{nachricht}\n\n"
                 "Noch {frei} freie Plätze. Übersicht: {link}\n\n{fusszeile}"),
    },
    "booking_invite": {
        "group": "Terminbuchung", "label": "Einladung zur Terminbuchung",
        "vars": _BOOKING_INVITE_VARS,
        "subject": "Bitte wählen Sie Ihren Termin: {titel}",
        "body": ("Guten Tag {name},\n\n{absender} lädt Sie ein, einen Termin für „{titel}“ zu wählen "
                 "(Dauer {dauer}, {zeitraum}).\n\n{beschreibung}\n\n{ort}\n\n"
                 "Zur Terminauswahl (persönlicher Link):\n{link}\n\n{fusszeile}"),
    },
    "booking_invite_reminder": {
        "group": "Terminbuchung", "label": "Erinnerung an die Terminbuchung",
        "vars": _BOOKING_INVITE_VARS,
        "subject": "Erinnerung: Bitte wählen Sie Ihren Termin – {titel}",
        "body": ("Guten Tag {name},\n\nfür „{titel}“ haben Sie noch keinen Termin gewählt. Hier geht es direkt "
                 "zur Auswahl:\n{link}\n\n{fusszeile}"),
    },
    "app_received": {
        "group": "Online-Anträge", "label": "Eingangsbestätigung mit Aktenzeichen (an die antragstellende Person)",
        "vars": _APP_VARS | {"name": "Name der antragstellenden Person", "antworten": "Kopie der Angaben",
                             "hinweise": "Hinweise zum Antrag (Unterlagen, Gebühr, Bearbeitungsdauer)"},
        "subject": "Eingangsbestätigung {aktenzeichen}: {titel}",
        "body": ("Guten Tag {name},\n\nIhr Antrag „{titel}“ ist am {zeitpunkt} bei uns eingegangen.\n\n"
                 "    Aktenzeichen: {aktenzeichen}\n\nBitte geben Sie das Aktenzeichen bei Rückfragen an. Den Stand der "
                 "Bearbeitung sehen Sie jederzeit hier:\n{status_link}\n\n{hinweise}\n\nIhre Angaben:\n\n{antworten}\n\n"
                 "{fusszeile}"),
    },
    "app_new": {
        "group": "Online-Anträge", "label": "Neuer Antrag (an die Zuständigen)",
        "vars": _APP_VARS | {"von": "Antragsteller:in", "antworten": "Angaben (abschaltbar in den Formular-Einstellungen)"},
        "subject": "Neuer Antrag {aktenzeichen}: {titel}",
        "body": ("Ein neuer Antrag ist eingegangen ({zeitpunkt}).\n\n    Aktenzeichen: {aktenzeichen}\n"
                 "    Antragsteller:in: {von}\n    Zuständig: {zustaendig}\n    Frist: {frist}\n\n{antworten}\n\n"
                 "Bearbeiten: {link}\n\n{fusszeile}"),
    },
    "app_status": {
        "group": "Online-Anträge", "label": "Statusänderung oder Nachricht (an die antragstellende Person)",
        "vars": _APP_VARS | {"name": "Name der antragstellenden Person", "nachricht": "Nachricht der Verwaltung"},
        "subject": "{aktenzeichen}: {status} – {titel}",
        "body": ("Guten Tag {name},\n\nzu Ihrem Antrag „{titel}“ (Aktenzeichen {aktenzeichen}) gibt es Neuigkeiten.\n\n"
                 "    Stand: {status}\n\n{nachricht}\n\nAlle Einzelheiten und – bei Rückfragen – die Möglichkeit zu antworten:\n"
                 "{status_link}\n\n{fusszeile}"),
    },
    "app_reply": {
        "group": "Online-Anträge", "label": "Antwort oder Rückzug durch die antragstellende Person (an die Zuständigen)",
        "vars": _APP_VARS | {"von": "Antragsteller:in", "nachricht": "Text der Antwort"},
        "subject": "Antwort zu {aktenzeichen}: {titel}",
        "body": ("{von} hat zum Antrag {aktenzeichen} („{titel}“) geschrieben:\n\n{nachricht}\n\nStand: {status}\n"
                 "Bearbeiten: {link}\n\n{fusszeile}"),
    },
    "app_assigned": {
        "group": "Online-Anträge", "label": "Antrag zugewiesen (an die neu Zuständigen)",
        "vars": _APP_VARS | {"absender": "Wer zugewiesen hat"},
        "subject": "Ihnen zugewiesen: {aktenzeichen} – {titel}",
        "body": ("{absender} hat Ihnen den Antrag {aktenzeichen} („{titel}“) zugewiesen.\n\nStand: {status}\n"
                 "Frist: {frist}\n\nBearbeiten: {link}\n\n{fusszeile}"),
    },
    "app_overdue": {
        "group": "Online-Anträge", "label": "Frist überschritten (an die Zuständigen)",
        "vars": _APP_VARS,
        "subject": "Frist überschritten: {aktenzeichen} – {titel}",
        "body": ("Die Bearbeitungsfrist für den Antrag {aktenzeichen} („{titel}“) ist am {frist} abgelaufen.\n\n"
                 "Stand: {status}\nZuständig: {zustaendig}\n\nBearbeiten: {link}\n\n{fusszeile}"),
    },
}

SAMPLE = {
    "name": "Erika Mustermann", "email": "erika.mustermann@example.org", "link": "https://meet.example.org/teamrunde",
    "gueltig_stunden": "72", "titel": "Teamrunde Bauamt", "datum": "Donnerstag, 01.10.2026",
    "uhrzeit": "10:00–11:00 Uhr", "dauer": "60 Minuten",
    "beschreibung": "Tagesordnung:\n1. Bericht\n2. Termine", "organisator": "Max Muster",
    "organisator_email": "max.muster@example.org", "aufnahme": "Teamrunde Bauamt, 01.10.2026 10:00 Uhr",
    "fehler": "Beispiel einer Fehlermeldung",
    "antwort_link": "https://portal.example.org/rsvp/beispiel",
    "teilnehmer": "Erika Mustermann <erika.mustermann@example.org>", "antwort": "Zugesagt",
    "kommentar": "Ich komme etwas später.", "stand": "3 zugesagt, 1 abgesagt, 2 offen",
    "absender": "Max Muster", "frist": "Bitte bis Freitag, 09.10.2026, 12:00 Uhr ausfüllen.",
    "code": "482913", "minuten": "10", "nummer": "17", "zeitpunkt": "01.10.2026, 14:32 Uhr", "von": "Erika Mustermann <erika.mustermann@example.org>",
    "antworten": "Teilnahme: Ja\nEssen: Vegetarisch", "anzahl": "17", "ort": "Rathaus, Sitzungssaal",
    "vorschlaege": "6", "termin": "Dienstag, 13.10.2026, 14:00–15:30 Uhr", "aktion": "hat abgestimmt",
    "videolink": "Teilnahme per Videokonferenz:\nhttps://portal.example.org/join/beispiel",
    "verwalten": "https://portal.example.org/b/m/beispiel", "absagefrist": "24 Stunden",
    "hinweis": "Bitte bringen Sie Ihre Zeugnisse mit.", "anbieter": "Max Muster", "wer": "Sie haben",
    "grund": "", "ereignis": "Neue Buchung", "gast": "Erika Mustermann <erika@example.org>", "nachricht": "",
    "frei": "11", "zeitraum": "13.10.2026 bis 15.10.2026",
    "aktenzeichen": "GEW-2026-00042", "status": "In Bearbeitung", "status_link": "https://portal.example.org/a/beispiel",
    "zustaendig": "Max Muster, Gruppe Ordnungsamt", "hinweise": "Bitte halten Sie Ihren Personalausweis bereit.\nGebühr: 26 €",
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
