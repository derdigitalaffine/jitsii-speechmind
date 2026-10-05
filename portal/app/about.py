"""Angaben für die Seite „Über dieses Portal“: Programmierung, verwendete Software und Lizenzen."""

PUBLISHER = "Verbandsgemeinde Otterbach-Otterberg"
LICENSE = "MIT"

# (Name, Version, Lizenz, Zweck, Adresse)
COMPONENTS = {
    "Konferenz & Infrastruktur": [
        ("Jitsi Meet (docker-jitsi-meet)", "stable", "Apache-2.0", "Videokonferenz: Web, Jicofo, Videobridge", "https://jitsi.org"),
        ("Jibri", "stable", "Apache-2.0", "Server-Aufzeichnung der Konferenzen", "https://github.com/jitsi/jibri"),
        ("Prosody", "0.12", "MIT", "XMPP-Server der Konferenz (mit eigenen Portal-Modulen)", "https://prosody.im"),
        ("Caddy", "2", "Apache-2.0", "Reverse Proxy, HTTPS und Let's-Encrypt-Zertifikate", "https://caddyserver.com"),
        ("FFmpeg", "Debian-Paket", "LGPL-2.1+ / GPL-2+", "Audiospur (MP3) aus den Aufnahmen", "https://ffmpeg.org"),
        ("Python", "3.12", "PSF-2.0", "Laufzeitumgebung des Portals", "https://www.python.org"),
        ("SQLite", "3", "Public Domain", "Datenbank des Portals", "https://sqlite.org"),
    ],
    "Portal (Server)": [
        ("FastAPI", "0.142", "MIT", "Web-Framework", "https://fastapi.tiangolo.com"),
        ("Starlette", "1.7", "BSD-3-Clause", "ASGI-Grundlage, Sitzungen", "https://www.starlette.io"),
        ("Uvicorn", "0.54", "BSD-3-Clause", "Webserver", "https://www.uvicorn.org"),
        ("Pydantic", "2", "MIT", "Datenprüfung", "https://docs.pydantic.dev"),
        ("Jinja2", "3.1", "BSD-3-Clause", "Seitenvorlagen", "https://jinja.palletsprojects.com"),
        ("MarkupSafe", "3", "BSD-3-Clause", "Sichere HTML-Ausgabe", "https://palletsprojects.com"),
        ("SQLAlchemy", "2.0", "MIT", "Datenbankzugriff", "https://www.sqlalchemy.org"),
        ("python-multipart", "0.0.32", "Apache-2.0", "Formulare und Datei-Uploads", "https://github.com/Kludex/python-multipart"),
        ("itsdangerous", "2.2", "BSD-3-Clause", "Signierte Sitzungs-Cookies", "https://palletsprojects.com"),
        ("HTTPX", "0.28", "BSD-3-Clause", "Anbindung an SpeechMind", "https://www.python-httpx.org"),
        ("PyJWT", "2.15", "MIT", "Zugangstoken für Jitsi", "https://pyjwt.readthedocs.io"),
        ("argon2-cffi", "25.1", "MIT", "Passwort-Hashes (Argon2)", "https://argon2-cffi.readthedocs.io"),
        ("cryptography", "50", "Apache-2.0 / BSD-3-Clause", "Verschlüsselung gespeicherter Schlüssel, Zertifikatsprüfung", "https://cryptography.io"),
        ("icalendar", "7.3", "BSD-2-Clause", "Zu-/Absagen aus Kalenderantworten lesen", "https://icalendar.readthedocs.io"),
        ("tzdata", "2026.4", "Apache-2.0", "Zeitzonen", "https://github.com/python/tzdata"),
        ("Segno", "1.6", "BSD-3-Clause", "QR-Codes", "https://segno.readthedocs.io"),
        ("Pillow", "12.3", "MIT-CMU (HPND)", "Bilder verkleinern, JPG-Ausgabe, Favicon", "https://python-pillow.org"),
        ("markdown-it-py", "3.0", "MIT", "Rechtstexte aus Markdown setzen", "https://github.com/executablebooks/markdown-it-py"),
        ("ReportLab", "4.4", "BSD-3-Clause", "PDF der Online-Anträge und Bescheide", "https://www.reportlab.com/opensource/"),
        ("pypdf", "6.19", "BSD-3-Clause", "Anlagen (PDF und Bilder) in das Antrags-PDF einbinden", "https://github.com/py-pdf/pypdf"),
        ("mdurl", "0.1", "MIT", "Links in Markdown prüfen (von markdown-it-py)", "https://github.com/executablebooks/mdurl"),
    ],
    "Portal (Oberfläche)": [
        ("Bootstrap", "5.3.8", "MIT", "Layout und Komponenten", "https://getbootstrap.com"),
        ("Font Awesome Free", "7.3.1", "Icons CC BY 4.0, Schriften SIL OFL 1.1, Code MIT", "Symbole", "https://fontawesome.com"),
        ("DataTables", "2 / 3", "MIT", "Tabellen mit Suche und Sortierung", "https://datatables.net"),
        ("Tom Select", "2.6", "Apache-2.0", "Auswahlfelder", "https://tom-select.js.org"),
        ("Tagify", "4.39", "MIT", "E-Mail-Adressen als Tags", "https://github.com/yairEO/tagify"),
        ("SweetAlert2", "11.26", "MIT", "Bestätigungsdialoge", "https://sweetalert2.github.io"),
        ("Coloris", "0.25", "MIT", "Farbwähler", "https://coloris.js.org"),
        ("Chart.js", "4.5", "MIT", "Diagramme", "https://www.chartjs.org"),
        ("SortableJS", "1.15", "MIT", "Ziehen und Ablegen im Formular-Baukasten", "https://sortablejs.github.io/Sortable/"),
        ("FullCalendar", "6.1", "MIT", "Wochenkalender der Terminbuchung", "https://fullcalendar.io"),
        ("MapLibre GL JS", "5.24", "BSD-3-Clause", "Kartenbrowser, Zeichnen und Messen, Kartenfragen in Formularen", "https://maplibre.org"),
    ],
}

SERVICES = [
    ("basemap.de (BKG)", "Datenlizenz Deutschland – Namensnennung 2.0", "Amtliche Grundkarte – nur wenn als Kartenlayer eingeschaltet",
     "https://basemap.de"),
    ("OpenStreetMap", "ODbL (Daten), Tile Usage Policy (Kacheln)", "Freie Weltkarte – nur wenn als Kartenlayer eingeschaltet; Kacheln über das Portal zwischengespeichert",
     "https://www.openstreetmap.org/copyright"),
    ("Nominatim (OpenStreetMap)", "ODbL (Daten), Nominatim Usage Policy", "Adress- und Ortssuche in Formularen und im Kartenbrowser – über das Portal, zwischengespeichert, höchstens eine Anfrage je Sekunde; eigener Server einstellbar",
     "https://nominatim.org"),
    ("PayPal", "Externer Dienst (PayPal-Nutzungsbedingungen)", "Online-Bezahlung (Checkout, Erstattungen) – nur wenn eingerichtet; Weiterleitung zu PayPal, keine PayPal-Skripte im Portal",
     "https://developer.paypal.com"),
    ("SpeechMind", "Externer Dienst (eigene Nutzungsbedingungen)", "Transkription und Protokoll – nur wenn angebunden und gestartet",
     "https://speechmind.com"),
    ("Let's Encrypt", "Externer Dienst (Subscriber Agreement)", "Kostenlose TLS-Zertifikate – nur wenn eingeschaltet",
     "https://letsencrypt.org"),
    ("GitHub (raw.githubusercontent.com)", "Externer Dienst (GitHub-Nutzungsbedingungen)", "Update-Hinweis für Admins: einmal täglich wird nur die Versionsnummer der aktuellen Fassung gelesen – abschaltbar auf dieser Seite",
     "https://github.com/derdigitalaffine/jitsii-speechmind"),
]
