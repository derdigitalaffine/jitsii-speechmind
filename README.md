# Videokonferenzserver der Verbandsgemeinde Otterbach-Otterberg

Selbst gehostete Videokonferenz mit [Jitsi Meet](https://jitsi.org/), Anmeldung über ein eigenes Web-Portal und Transkription der Aufnahmen über [SpeechMind](https://www.speechmind.com/).

Angemeldete Benutzer:innen eröffnen Meetings, laden Gäste per Link ein und starten in der Konferenz die Aufnahme. Nach dem Ende erzeugt das Portal eine MP3. Die **Transkription startet nie automatisch**: Im Admin-Bereich unter „Aufnahmen“ lässt sich die MP3 herunterladen oder mit „In SpeechMind bearbeiten“ an SpeechMind übergeben. Protokoll, Aufgaben und Wortlaut erscheinen danach im Portal.

Name und Produktbezeichnung lassen sich über `BRAND_NAME` und `BRAND_PRODUCT` in `.env` ändern.

```
                 ┌────────────┐
 Browser ──443──►│   Caddy    │── meet.example.com ──► Jitsi web ─┬─ prosody (JWT-Auth)
                 │ (TLS, LE)  │                                   ├─ jicofo
                 └─────┬──────┘                                   └─ jvb ◄── UDP 10000
                       │
                       └── portal.example.com ──► Portal (Login, Meetings, Einstellungen)
                                                     ▲          │
                         Jibri ── Aufnahme (.mp4) ───┘          ▼
                                                     ffmpeg → SpeechMind GraphQL API
```

## Funktionen

- **Anmeldung:** Jitsi läuft mit JWT-Authentifizierung. Nur Portal-Benutzer:innen können Räume eröffnen und moderieren. Wer `meet.example.com/raum` direkt aufruft, wird zum Portal-Login umgeleitet.
- **Gäste** brauchen kein Konto. Sie treten über den Einladungslink bei, sobald eine Moderatorin oder ein Moderator im Raum ist.
- **Aufnahme** über Jibri (Server-Aufzeichnung). Recht zum Aufzeichnen haben nur angemeldete Benutzer:innen.
- **SpeechMind-Anbindung per Web-GUI:** API-Key hinterlegen (verschlüsselt gespeichert), Verbindung testen, Projekt auswählen oder anlegen, Protokollart und Sprache festlegen.
- **Transkription auf Knopfdruck** (nie automatisch), mit sichtbarem Verarbeitungsstand (Aufgezeichnet → Audiospur → Upload → SpeechMind → Transkript).
- **Ergebnis im Portal:** Protokoll, Aufgaben und Wortlaut mit Zeitmarken; Download als TXT.
- **MP3-Übersicht** im Admin-Bereich: alle Aufnahmen mit Dauer, Größe und Status, MP3-Download, Übergabe an SpeechMind.
- **Benutzerverwaltung** für Admins mit **Einladung per E-Mail**: Die eingeladene Person legt ihr Passwort über einen Einmal-Link selbst fest. „Passwort vergessen“ nutzt denselben Weg. Optional eigene SpeechMind-Keys pro Benutzer:in.
- **Benachrichtigungen per E-Mail** (SMTP, optional IMAP-Ablage): Einladungen, Passwort-Links und Hinweise zu neuen Aufnahmen, fertigen Transkripten und Fehlern. Nachrichten laufen über eine Warteschlange mit automatischen Wiederholungen und sichtbarem Protokoll.
- **Standard-Admin** beim ersten Start, der beim ersten Login ein eigenes Passwort vergeben muss.
- **Datensparsam:** keine externen Schriften oder Skripte im Portal; Videos können nach fertigem Transkript automatisch gelöscht werden.

## Voraussetzungen

- Linux-Server mit Docker und Docker Compose v2
- Zwei DNS-Einträge auf den Server, z. B. `meet.example.com` und `portal.example.com`
- Offene Ports: **TCP 80, TCP 443, UDP 10000**
- Ressourcen: Jitsi allein läuft mit 2 Kernen / 4 GB. **Jibri** braucht zusätzlich etwa 4 Kerne / 8 GB und nimmt **eine** Konferenz gleichzeitig auf.
- Ein SpeechMind-Konto mit API-Zugang (API-Key über SpeechMind bzw. die Organisationsverwaltung)

## Installation

```bash
git clone https://github.com/<ihr-konto>/jitsi-speechmind.git
cd jitsi-speechmind
./scripts/setup.sh          # fragt Domains ab, erzeugt .env mit Zufalls-Secrets
docker compose up -d --build
```

`setup.sh` gibt am Ende E-Mail und Startpasswort des Standard-Admins aus (ohne `PORTAL_ADMIN_PASSWORD` erzeugt das Portal eines und schreibt es einmalig ins Log: `docker compose logs portal`). Beim ersten Login muss ein eigenes Passwort vergeben werden. Danach:

1. `https://portal.example.com` öffnen und anmelden.
2. **Benachrichtigungen:** SMTP (und optional IMAP) eintragen, Testmail senden.
3. **SpeechMind:** API-Key eintragen, speichern, „Verbindung testen“ klicken, Projekt auswählen, speichern.
4. **Benutzer:** Teammitglieder per E-Mail einladen. Ohne eingerichteten Mailversand zeigt das Portal den Einladungslink einmalig zum Weitergeben an.
5. **Meetings:** Meeting anlegen, „Konferenz betreten“, in Jitsi über das Menü die Aufnahme starten.
6. **Aufnahmen:** Nach dem Beenden erscheint die Aufnahme nach kurzer Zeit mit MP3 unter „Aufnahmen“. Dort herunterladen oder „In SpeechMind bearbeiten“ klicken. SpeechMind braucht erfahrungsgemäß rund die halbe Aufnahmedauer.

### Produktion: Jitsi-Version pinnen

`JITSI_IMAGE_VERSION=stable` folgt immer dem neuesten Release. Für einen ruhigen Betrieb in `.env` auf eine feste Version setzen, z. B. `stable-10314`, und Updates bewusst einspielen. Die aktuellen Versionen stehen unter <https://github.com/jitsi/docker-jitsi-meet/releases>.

## Wie die Transkription funktioniert

1. Jibri nimmt die Konferenz als MP4 in `data/recordings/<sitzung>/` auf und schreibt eine `metadata.json` mit der Meeting-URL.
2. Am Ende ruft Jibri `jibri/finalize.sh` auf. Das Skript legt nur die Markierung `.finalized` ab.
3. Das Portal findet die Aufnahme, ordnet sie über den Raumnamen dem Meeting zu und erzeugt per ffmpeg die MP3 (mono, 16 kHz, 64 kbit/s, unter `data/portal/audio/`). Dann wartet es. Erst ein Klick auf „In SpeechMind bearbeiten“ startet die Übergabe:
   - `getUploadUrl` liefert eine vorsignierte Upload-Adresse, die Datei wird hochgeladen,
   - `initProtocol` legt das Protokoll im gewählten Projekt an,
   - `getResults` wird abgefragt, bis SpeechMind fertig ist,
   - `getTextsegmentsByProtocolAndPage` liefert den Wortlaut.
4. Ergebnis und Wortlaut werden im Portal gespeichert. Das Protokoll bleibt zusätzlich in SpeechMind.

Grundlage ist die [SpeechMind API v2](https://www.speechmind.com/docs/introduction/) (GraphQL, Authentifizierung per `x-api-key`).

### Wer sieht was?

| | Eigene Meetings & Aufnahmen | Fremde Aufnahmen | Einstellungen & Benutzer |
|---|---|---|---|
| Benutzer:in | ✓ | – | eigenes Profil |
| Admin | ✓ | ✓ (auch Räume ohne Meeting) | ✓ |

Ein Raum, der direkt über die Meet-Domain eröffnet wird, wird automatisch als Meeting der anmeldenden Person angelegt.

## Konfiguration

Alle Werte stehen in `.env` (Vorlage: `.env.example`). Die wichtigsten:

| Variable | Bedeutung |
|---|---|
| `MEET_DOMAIN`, `PORTAL_DOMAIN` | Domains für Konferenz und Portal |
| `ACME_EMAIL` | Kontakt für Let's Encrypt |
| `JVB_ADVERTISE_IPS` | Öffentliche IP des Servers (wichtig hinter NAT) |
| `JITSI_IMAGE_VERSION` | Jitsi-Release, für Produktion pinnen |
| `ENABLE_GUESTS` | `1` = Gäste per Link erlaubt |
| `JWT_APP_SECRET` | Gemeinsames Secret von Portal und Prosody |
| `JWT_TOKEN_TTL_MINUTES` | Gültigkeit eines Konferenz-Tokens |
| `PORTAL_SECRET_KEY` | Sitzungen und Verschlüsselung der API-Keys. **Nicht nachträglich ändern**, sonst sind gespeicherte Keys unlesbar. |
| `PORTAL_ADMIN_EMAIL`, `PORTAL_ADMIN_PASSWORD` | Standard-Admin (nur beim allerersten Start; Passwortwechsel beim ersten Login erzwungen) |
| `BRAND_NAME`, `BRAND_PRODUCT` | Name und Produktbezeichnung in Portal, Mails und Jitsi-Oberfläche |
| `TZ` | Zeitzone für Anzeigen und Protokolldatum |

Zusätzliche Portal-Variablen (optional, in `docker-compose.yml` beim Dienst `portal` ergänzen):

| Variable | Standard | Bedeutung |
|---|---|---|
| `WATCH_INTERVAL_SECONDS` | 15 | Wie oft nach neuen Aufnahmen gesucht wird |
| `SPEECHMIND_POLL_SECONDS` | 45 | Abstand der Statusabfragen bei SpeechMind |
| `SPEECHMIND_POLL_TIMEOUT_HOURS` | 12 | Danach gilt ein Auftrag als fehlgeschlagen |
| `INVITE_TTL_HOURS` | 72 | Gültigkeit eines Einladungslinks |
| `RESET_TTL_HOURS` | 2 | Gültigkeit eines Passwort-Links |

SpeechMind- und Mail-Einstellungen (SMTP/IMAP) werden in der Web-GUI gepflegt, nicht in `.env`; Passwörter und Keys liegen verschlüsselt in der Datenbank.

## Daten & Sicherung

Alles Persistente liegt unter `data/` (konfigurierbar über `CONFIG`):

- `data/portal/portal.db` – Benutzer, Meetings, Einstellungen, Transkripte (SQLite)
- `data/portal/audio/` – erzeugte MP3-Dateien
- `data/recordings/` – Jibri-Aufnahmen
- `data/caddy/` – Zertifikate
- übrige Ordner – Jitsi-Konfiguration (wird beim Start neu erzeugt)

Sicherung: `data/portal/` und `.env` regelmäßig wegsichern. Für eine konsistente Kopie der Datenbank:

```bash
docker compose exec portal python -c "import sqlite3; s=sqlite3.connect('/data/portal.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
```

## Datenschutz

- Aufzeichnungen enthalten personenbezogene Daten. Holen Sie die Einwilligung der Teilnehmenden ein; Jitsi kündigt laufende Aufnahmen an, das ersetzt aber keine rechtliche Grundlage.
- Mit SpeechMind ist ein Vertrag zur Auftragsverarbeitung (AVV) nötig.
- Die Option „Video nach fertigem Transkript löschen“ reduziert die auf dem Server gespeicherten Daten.
- „Teilnehmernamen als Sprecherliste übergeben“ ist standardmäßig aus.
- Das Portal lädt keine Ressourcen von Drittanbietern.

## Fehlersuche

**Logs ansehen**
```bash
docker compose logs -f portal
docker compose logs -f jibri
```

**Konferenz verbindet, aber kein Bild/Ton** – UDP 10000 ist nicht offen oder `JVB_ADVERTISE_IPS` stimmt nicht mit der öffentlichen IP überein.

**„Authentifizierung erforderlich“ endet in einer Schleife** – `JWT_APP_SECRET`, `JWT_APP_ID`/`JWT_ACCEPTED_ISSUERS` und `JWT_ACCEPTED_AUDIENCES` müssen zueinander passen. Nach Änderungen an `.env`: `docker compose up -d --force-recreate`. Bei hartnäckigen Problemen `data/prosody` löschen; die Konfiguration wird neu erzeugt.

**Aufnahme-Button fehlt oder Aufnahme startet nicht** – `docker compose logs jibri` prüfen. Häufige Ursachen: zu wenig Arbeitsspeicher, Jibri ist noch mit einer anderen Aufnahme beschäftigt, oder Jibri erreicht `https://MEET_DOMAIN` nicht. Ältere Jitsi-Versionen benötigen zusätzlich das Kernelmodul `snd-aloop` auf dem Host (`sudo modprobe snd-aloop`).

**Aufnahme erscheint nicht im Portal** – Prüfen, ob in `data/recordings/<sitzung>/` eine `.finalized`-Datei liegt. Fehlt sie, wurde `finalize.sh` nicht ausgeführt: Ausführungsrecht prüfen (`chmod +x jibri/finalize.sh`) und `docker compose logs jibri` ansehen.

**Status „Fehlgeschlagen“** – Die Fehlermeldung steht direkt an der Aufnahme. Bei Problemen mit Key oder Projekt in der GUI unter „SpeechMind“ „Verbindung testen“. Danach an der Aufnahme „Erneut versuchen“. Ist der Upload bereits gelungen, fragt „Erneut versuchen“ nur das Ergebnis neu ab, ohne doppelt hochzuladen.

## Entwicklung

Das Portal lässt sich ohne Jitsi lokal starten:

```bash
cd portal
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export PORTAL_SECRET_KEY=dev JWT_APP_SECRET=dev \
       PORTAL_ADMIN_EMAIL=admin@example.com PORTAL_ADMIN_PASSWORD=adminadmin1 \
       DATA_DIR=./dev-data RECORDINGS_DIR=./dev-recordings
uvicorn app.main:app --reload
```

Eine Jibri-Aufnahme lässt sich simulieren, indem man in `dev-recordings/<name>/` eine MP4-Datei, eine `metadata.json` mit `{"meeting_url": "https://meet.example.com/<raum>"}` und eine leere Datei `.finalized` ablegt.

Projektstruktur:

```
portal/app/
├── main.py          Routen (Login, Meetings, Aufnahmen, Admin)
├── worker.py        Aufnahmen finden, MP3 erzeugen, Upload, Statusabfrage
├── notify.py        Benachrichtigungs-Engine (SMTP/IMAP, Warteschlange)
├── speechmind.py    Client für die SpeechMind GraphQL API v2
├── security.py      Passwörter, Verschlüsselung, CSRF, Jitsi-JWT
├── db.py            Datenmodell (SQLAlchemy, SQLite)
├── templates/       Jinja2-Vorlagen
└── static/style.css
```

## Lizenz

MIT, siehe [LICENSE](LICENSE). Jitsi Meet steht unter der Apache-2.0-Lizenz. SpeechMind ist ein kommerzieller Dienst der SpeechMind GmbH; dieses Projekt ist kein offizielles SpeechMind-Produkt.
