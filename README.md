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
- **Besprechungen planen:** Termin, Dauer, Tagesordnung und Teilnehmende (Portal-Benutzer werden vorgeschlagen, externe Gäste per Adresse). Jede Person bekommt eine eigene Einladung als Outlook-Besprechungsanfrage mit ICS-Anhang und Einwahllink; Änderungen, Ausladungen und Absagen aktualisieren die Kalender automatisch.
- **Bearbeitbare E-Mail-Vorlagen** für alle Mails (Einladungen, Passwort-Links, Besprechungen, Aufnahmen) mit Platzhaltern, Live-Vorschau und Testmail.
- **Aufnahmen löschen** einzeln oder per Mehrfachauswahl: nur Video und MP3 (Transkript bleibt), alles außer dem Verweis auf SpeechMind (Protokoll später wieder abrufbar) oder alles.
- **Benutzerverwaltung** für Admins mit **Einladung per E-Mail**: Die eingeladene Person legt ihr Passwort über einen Einmal-Link selbst fest. „Passwort vergessen“ nutzt denselben Weg. Optional eigene SpeechMind-Keys pro Benutzer:in.
- **Benachrichtigungen per E-Mail** (SMTP, optional IMAP-Ablage): Einladungen, Passwort-Links und Hinweise zu neuen Aufnahmen, fertigen Transkripten und Fehlern. Nachrichten laufen über eine Warteschlange mit automatischen Wiederholungen und sichtbarem Protokoll.
- **HTTPS mit Reverse Proxy (Caddy):** Start mit selbst signiertem Zertifikat, sofort lauffähig. **Let's Encrypt** (automatische Beantragung und Erneuerung) schaltet man bei Bedarf in der Admin-Oberfläche unter „HTTPS & Zertifikat“ ein – ohne Dateien zu bearbeiten, mit DNS-Prüfung, Testumgebung und Statusanzeige.
- **Konferenzen ohne Anmeldung:** Wer kein Konto hat, kann über die Anmeldeseite sofort einen eigenen Raum eröffnen und Gäste einladen. **Aufnahmen sind dort ausgeschlossen** (Aufnahme-Recht fehlt im Token; Aufnahmen solcher Räume werden zusätzlich serverseitig verworfen). Im Admin-Bereich abschaltbar.
- **Moderne Admin-Oberfläche** (Bootstrap 5, Font Awesome 7): Seitenleiste, hell/dunkel, durchsuchbare und sortierbare Tabellen (DataTables), Mehrfach-Einladung per E-Mail-Tags (Tagify), Bestätigungsdialoge (SweetAlert2). Alle Bibliotheken liegen lokal im Repository – keine Verbindung zu Drittanbietern.
- **Design & Branding** im Admin-Bereich: Name, Hauptfarbe, Kopfleiste, Farbschema, Rundungen, Logo, Favicon, Anmelde-Hinweis, Fußzeile, Impressum-/Datenschutz-Links, mit Live-Vorschau; Farben und Logo lassen sich ein- und ausschalten und auf Standard zurücksetzen. Auf Wunsch übernimmt auch die Konferenzoberfläche (und damit die Videoaufnahme) Logo und Farbe.
- **Standard-Admin** beim ersten Start, der beim ersten Login ein eigenes Passwort vergeben muss.
- **Datensparsam:** keine externen Schriften oder Skripte im Portal; Videos können nach fertigem Transkript automatisch gelöscht werden.

## Dokumentation

| Für wen | Datei |
|---|---|
| Wer den Server **installiert und betreibt** | diese Seite, danach [docs/ADMIN-HANDBUCH.md](docs/ADMIN-HANDBUCH.md) |
| Wer **Konferenzen hält** (Mitarbeitende) | [docs/BENUTZERANLEITUNG.md](docs/BENUTZERANLEITUNG.md) |

## Installation in 11 Schritten

Sie brauchen: einen Linux-Server (Ubuntu/Debian), Zugriff per SSH mit `sudo`, und jemanden, der DNS-Einträge anlegen kann. **Rechnen Sie mit 30–60 Minuten.**

### Vorher klären (Checkliste)

- [ ] **Server:** mindestens 4 Kerne und 12 GB RAM, 100 GB Platz (Aufnahmen brauchen Speicher). Jitsi allein käme mit 2 Kernen / 4 GB aus, **Jibri** (die Aufnahme) braucht zusätzlich etwa 4 Kerne / 8 GB und nimmt **eine** Konferenz gleichzeitig auf.
- [ ] **Öffentliche IP-Adresse** des Servers (`curl https://api.ipify.org` auf dem Server zeigt sie).
- [ ] **Zwei Domainnamen**, die beide auf diese IP zeigen (DNS-Eintrag „A“), z. B. `meet.vg-otterbach-otterberg.example` und `portal.vg-otterbach-otterberg.example`. Den DNS-Eintrag legt Ihre IT oder der Domain-Anbieter an; es dauert bis zu einigen Stunden, bis er überall gilt.
- [ ] **Firewall** (auch die des Rechenzentrums/Routers): **TCP 80, TCP 443 und UDP 10000** müssen von außen offen sein. UDP 10000 vergessen Leute am häufigsten, dann gibt es kein Bild und keinen Ton.
- [ ] **E-Mail-Zugang für den Versand** (SMTP-Server, Benutzername, Passwort, Absenderadresse) – bekommen Sie von Ihrer IT. Ohne das geht alles außer E-Mails.
- [ ] **SpeechMind-API-Key** (kommt vom Anbieter) – nur für die Transkription nötig, kann nachgereicht werden.

### Schritt für Schritt

> Für den allerersten Start brauchen Sie **keine** öffentliche Domain: Mit selbst signiertem Zertifikat läuft alles. Let's Encrypt kommt erst in Schritt 11 dazu.

**1. Docker installieren** (einmalig, falls noch nicht vorhanden):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # danach einmal ab- und wieder anmelden
docker compose version             # muss eine Versionsnummer zeigen
```

**2. Projekt herunterladen:**

```bash
git clone https://github.com/derdigitalaffine/jitsii-speechmind.git
cd jitsii-speechmind
```

**3. Einrichtungsassistent starten** – er stellt Fragen und schreibt die Datei `.env` mit allen Passwörtern:

```bash
./scripts/setup.sh
```

Beantworten Sie die Fragen (Domains, E-Mail für Zertifikate, öffentliche IP, Admin-E-Mail). **Am Ende zeigt er das Startpasswort des Admins. Notieren Sie es jetzt**, es wird nicht wieder angezeigt.

**4. Starten:**

```bash
docker compose up -d --build
```

Das erste Mal dauert einige Minuten (Bilder werden geladen und gebaut).

**5. Prüfen, ob alles läuft:**

```bash
docker compose ps
```

Alle Zeilen sollten „running“ oder „Up“ zeigen. Der Proxy startet mit **selbst signierten Zertifikaten**: Das Portal läuft sofort, der Browser zeigt aber eine Zertifikatswarnung (einmal „Trotzdem fortfahren“ wählen). Das richten Sie in Schritt 11 sauber ein.

**6. Portal öffnen:** `https://<Ihre Portal-Domain>` im Browser. Anmelden mit der Admin-E-Mail und dem Startpasswort aus Schritt 3.

**7. Eigenes Passwort vergeben.** Das Portal verlangt das sofort (alte Passwort = Startpasswort, neues mindestens 10 Zeichen). Erst danach sind die anderen Seiten erreichbar.

**8. E-Mail einrichten:** Oben auf **Benachrichtigungen** klicken, SMTP-Daten eintragen, **Speichern**, dann **Testmail senden**. Kommt die Mail an, ist alles in Ordnung. Wie die Felder auszufüllen sind, steht im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md#e-mail-einrichten).

**9. SpeechMind verbinden:** Oben auf **SpeechMind**, API-Key eintragen, **Speichern**, **Verbindung testen**, ein Projekt auswählen, **Speichern**.

**10. Kolleginnen und Kollegen einladen:** Oben auf **Benutzer**, Name und E-Mail eintragen, **Einladen**. Die Person bekommt eine Mail mit einem Link und legt ihr Passwort selbst fest.

**11. Öffentliches Zertifikat (Let's Encrypt) einschalten:** Sind DNS-Einträge und Ports 80/443 bereit, im Portal links auf **HTTPS & Zertifikat**, **Let's Encrypt** wählen, E-Mail prüfen, **Speichern und anwenden**. Nach etwa einer Minute steht oben „vertrauenswürdig“ und die Browser-Warnung ist weg. Zum gefahrlosen Üben vorher „Testumgebung“ einschalten. Details im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md#https-und-zertifikat).

**Probelauf (empfohlen):** Legen Sie ein Meeting an, treten Sie bei, starten Sie über „…“ › „Aufnahme starten“, sprechen Sie ein paar Sätze, beenden Sie die Aufnahme. Nach kurzer Zeit erscheint sie unter **Aufnahmen** mit MP3.

Fertig. Alles Weitere (Updates, Sicherung, Probleme) steht unten und im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md).

> **Wichtig:** Die Datei `.env` enthält alle Geheimnisse. Niemals weitergeben, nicht in Git einchecken (ist ausgeschlossen) und **`PORTAL_SECRET_KEY` nie nachträglich ändern**, sonst sind gespeicherte Passwörter und Keys unlesbar.

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
- `data/portal/branding/` – hochgeladenes Logo und Favicon
- `data/recordings/` – Jibri-Aufnahmen
- `data/caddy/` – Zertifikate und die vom Portal verwaltete Proxy-Konfiguration (`conf/Caddyfile`)
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

**Aufnahme-Button fehlt oder Aufnahme startet nicht** – `docker compose logs jibri` prüfen. Häufige Ursachen: zu wenig Arbeitsspeicher, Jibri ist noch mit einer anderen Aufnahme beschäftigt, oder Jibri erreicht `https://MEET_DOMAIN` nicht. Aktuelle Jibri-Versionen nehmen den Ton über PulseAudio im Container auf; ältere benötigen zusätzlich das Kernelmodul `snd-aloop` auf dem Host.

**Aufnahme ist stumm / MP3 ohne Ton** – Das Portal markiert solche Aufnahmen mit „kein Ton“. Auf dem Server `./scripts/diagnose-recording.sh` ausführen: Es prüft die neueste Aufnahme und das Tonsystem in Jibri und sagt, ob beim Test nur niemand zu hören war oder Jibri den Ton wirklich nicht erfasst (Details im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md#aufnahme-ohne-ton)).

**Aufnahme erscheint nicht im Portal** – Prüfen, ob in `data/recordings/<sitzung>/` eine `.finalized`-Datei liegt. Fehlt sie, wurde `finalize.sh` nicht ausgeführt: Ausführungsrecht prüfen (`chmod +x jibri/finalize.sh`) und `docker compose logs jibri` ansehen.

**E-Mails kommen nicht an** – Unter „Benachrichtigungen“ ganz unten steht zu jeder Nachricht der Fehler. Häufig: falscher Port/Verschlüsselung (587 = STARTTLS, 465 = SSL/TLS), falsches Passwort, oder der Mailserver erlaubt die Absenderadresse nicht. Mehr im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md#e-mail-einrichten).

**Admin-Passwort vergessen** – siehe [Admin-Handbuch](docs/ADMIN-HANDBUCH.md#admin-passwort-vergessen).

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
├── notify.py        Benachrichtigungs-Engine (SMTP/IMAP, Warteschlange, Anhänge)
├── mailtpl.py       Bearbeitbare E-Mail-Vorlagen
├── planning.py      Besprechungen planen, Einladungen versenden
├── ics.py           Kalendereinladungen (iCalendar, RFC 5545)
├── branding.py      Design & Branding (Farben, Logo, Theme-CSS)
├── proxy.py         Reverse Proxy: Caddyfile erzeugen, Zertifikate prüfen
├── cli.py           Notfall-Werkzeug (Passwort setzen, Admin machen)
├── speechmind.py    Client für die SpeechMind GraphQL API v2
├── security.py      Passwörter, Verschlüsselung, CSRF, Jitsi-JWT
├── db.py            Datenmodell (SQLAlchemy, SQLite)
├── templates/       Jinja2-Vorlagen
└── static/          app.css, app.js und vendor/ (Bootstrap, Font Awesome, DataTables, …)
```

## Lizenz

MIT, siehe [LICENSE](LICENSE). Jitsi Meet steht unter der Apache-2.0-Lizenz. SpeechMind ist ein kommerzieller Dienst der SpeechMind GmbH; dieses Projekt ist kein offizielles SpeechMind-Produkt.
