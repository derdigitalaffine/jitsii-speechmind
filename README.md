# Videokonferenzserver der Verbandsgemeinde Otterbach-Otterberg

**Selbst gehostetes Portal für Verwaltungen:** Videokonferenzen mit [Jitsi Meet](https://jitsi.org/), Aufnahme und Transkription über [SpeechMind](https://www.speechmind.com/), Besprechungsplanung mit Outlook-Einladungen, Terminumfragen wie Doodle, Terminbuchung wie Calendly, Kurzlinks mit QR-Codes, ein Formularserver und Rechtstexte (Ortsrecht online) – alles auf dem eigenen Server, ohne Daten an große Plattformen.

Herausgegeben von der Verbandsgemeinde Otterbach-Otterberg und als **freie Software (MIT-Lizenz)** ausdrücklich für alle anderen Verwaltungen gedacht: Verbandsgemeinden, Städte, Kreise, Zweckverbände. Nutzen Sie es, passen Sie es an Ihr Haus an, und teilen Sie Verbesserungen, damit alle davon profitieren. Name, Farben und Logo stellen Sie in der Oberfläche um (Design & Branding), voreingestellt über `BRAND_NAME` und `BRAND_PRODUCT` in `.env`.

```
                 ┌────────────┐
 Browser ──443──►│   Caddy    │── meet.example.com ──► Jitsi web ─┬─ prosody (JWT + Portal-Module)
                 │ (TLS, LE)  │                                   ├─ jicofo
                 └─────┬──────┘                                   └─ jvb ◄── UDP 10000
                       │
                       ├── portal.example.com ──► Portal: Meetings, Planung, Kurzlinks, Formulare, Recht
                       │                              ▲          │
                       └── kurz.example.com (opt.)    │          ▼
                                    Jibri ── Aufnahme ┘   ffmpeg → SpeechMind GraphQL API
```

## Funktionen

### Videokonferenzen

- **Portal-Räume** (im Portal angelegt) sind nur mit Anmeldung oder per **Gastlink / persönlichem Einladungslink** erreichbar. Gäste dürfen nicht aufnehmen und werden **nie automatisch Moderator**. Durchgesetzt von zwei kleinen Prosody-Modulen (`prosody/`).
- **Freie Räume:** Jede:r kann ohne Konto unter beliebigem Namen einen Raum eröffnen (abschaltbar) – dort gibt es keine Aufnahme.
- **Aufnahme** über Jibri. Das Portal erzeugt eine MP3 und erkennt stumme Aufnahmen.
- **Chatprotokoll und Umfragen:** Gruppenchat und Jitsi-Umfragen (Frage, Ergebnis, Abstimmende) während einer Aufnahme werden mit der Aufnahme gespeichert; ohne Aufnahme nach 48 Stunden gelöscht.
- **Transkription auf Knopfdruck** (nie automatisch) über SpeechMind: Protokoll mit Beschlüssen und Aufgaben, Wortlaut mit Zeitmarken, Download als TXT. Verarbeitungsstand sichtbar.
- **Aufnahmen löschen** einzeln oder gesammelt: nur Medien, alles außer dem Verweis auf SpeechMind, oder alles.

### Besprechungen planen

- Termin, Dauer, Tagesordnung, Teilnehmende (Kolleg:innen werden vorgeschlagen, Gäste per Adresse).
- Jede Person bekommt eine eigene **Outlook-Besprechungsanfrage** mit ICS und persönlichem Einwahllink. Änderungen, Ausladungen und Absagen aktualisieren die Kalender; beim Löschen eines Meetings werden Absagen vorgeschlagen.
- **Zu- und Absagen** per Kalender (IMAP-Auswertung inkl. Outlook/Exchange-Sonderformaten, mit Postfach-Diagnose) oder per Link in jedem Mailprogramm.

### Terminumfragen wie Doodle (abschaltbares Modul)

- Terminvorschläge (ganztägig oder mit Uhrzeit) mit Generator „Tage × Uhrzeiten“.
- Abstimmen mit **Ja / Wenn nötig / Nein** per öffentlichem Link (ohne Konto) oder persönlicher Einladung an Benutzer, Gruppen und Gäste; Antworten jederzeit änderbar, Erinnerungen, Frist.
- Optionen: nur ein Termin, **Plätze je Termin** (Terminbuchung, z. B. Sprechstunden), verdeckte Umfrage, E-Mail-Pflicht.
- Ergebnis-Raster mit besten Terminen, CSV-Export; **Termin festlegen** mit Mail und Kalenderdatei an alle oder **direkt als Besprechung mit Outlook-Einladungen**.
- **Im Portal teilen** mit Personen oder Gruppen in drei Stufen: Ergebnisse einsehen · zusätzlich einladen · zusätzlich bearbeiten und löschen.

### Terminbuchung wie Calendly (abschaltbares Modul)

- Zeitbereiche im **Wochenkalender aufziehen** (oder wöchentlich wiederholt per Formular); daraus entstehen Zeitfenster aus **Dauer + Pause** mit Plätzen je Fenster.
- Gäste buchen **selbst** freie Zeitfenster – öffentlich oder **nur mit persönlicher Einladung** (ideal für Vorstellungsgespräche; Bewerberliste einfach einfügen).
- Bestätigung mit Kalendereintrag, **Verschieben und Absagen** durch Gast oder Anbieter, automatische **Erinnerungen**, optional **eigene Videokonferenz je Termin**.
- **Terminliste mit Filter und Sortierung**, Export als **iCal, CSV, JSON und Markdown**, **Kalender-Abo** für Outlook & Co.
- **Im Portal teilen** in drei Stufen: Buchungen einsehen · zusätzlich einladen · zusätzlich Zeitbereiche, Termine und Einstellungen bearbeiten.

### Kurzlinks und QR-Codes (abschaltbares Modul)

- Wie [Shlink](https://shlink.io/), aber in der Oberfläche: eigenes oder zufälliges Kürzel, Titel, Schlagwörter, Gültigkeitszeitraum, Aufruf-Limit, Parameter-Weitergabe, Art der Weiterleitung.
- **Statistik ohne IP-Adressen** (Aufrufe pro Tag, Browser, System, Gerät, Herkunft), Bots und Link-Prüfer getrennt, CSV-Export.
- Optional **eigene Kurz-Domain** – das Portal trägt sie selbst in den Proxy ein.
- **QR-Generator** für Kurzlinks und beliebige Inhalte: Vorschau, Farben, Größe, Fehlerkorrektur, Download als **SVG, PNG und JPG**.

### Formulare (abschaltbares Modul)

- **Baukasten** mit den Feldtypen von Nextcloud Forms: kurze Antwort (Text, E-Mail, Telefon, Zahl, eigenes Muster), langer Text, Einfach-/Mehrfachauswahl (mit „Sonstiges“), Auswahlliste, Datum, Uhrzeit, Datum+Uhrzeit, lineare Skala, Farbe, Datei-Upload.
- **Gliederung** mit Überschriften, Zwischenüberschriften, Hinweistexten, Trennlinien und **mehrseitigen Formularen**. Ziehen und Ablegen, Duplizieren, Vorschau.
- **Verteilen:** öffentlicher Link (mit QR-Code und Kurzlink), persönliche Einladungen an Benutzer, **Gruppen** und Gäste per Mail, Erinnerungen, Frist, anonym, Mehrfachantworten, Eingangsbestätigung.
- **Auswerten:** Zusammenfassung mit Diagrammen, Einzelansicht, Export **CSV** (Excel) und **JSON**.
- **Benachrichtigung** bei neuen Antworten, wahlweise mit CSV- und/oder JSON-Anhang – nur die neue Antwort oder jeweils alle.
- **Im Portal teilen** mit Personen oder Gruppen in drei Stufen: Ergebnisse einsehen · zusätzlich einladen · zusätzlich bearbeiten und löschen.

### Rechtstexte – Ortsrecht online (abschaltbares Modul)

- Gesetze, **Satzungen** und Verordnungen als **Markdown** einfügen oder hochladen (auch viele Dateien auf einmal); aus Word oder Webseiten kopierter Text wird ebenfalls gegliedert.
- **Rechtsbaum** mit frei bearbeitbaren Ebenen: Europäische Union › Bund › Land › Landkreis › Verbandsgemeinde › Ortsgemeinden (beliebig verschachtelt, sortierbar).
- Öffentliche Ansicht unter `/recht` in **gesetzestypischer Formatierung** (zentrierte §-Überschriften, nummerierte Absätze): wahlweise **Volltext** oder **Paragraf für Paragraf**, mit **Baum-Inhaltsverzeichnis**, Permalinks je §, Druckansicht und Markdown-Download.
- **Volltextsuche** über alle Texte, einzelne Ebenen oder einen Text, mit Fundstellen und Hervorhebung; § direkt suchbar („§ 3 Hauptsatzung“).
- Entwürfe, Stand/Fassung, Ausfertigungs- und Inkrafttretensdaten, **frühere Fassungen** mit Wiederherstellen. Pflege mit eigenem Recht „Rechtstexte“.

### Verwaltung und Sicherheit

- **Benutzerverwaltung** mit Einladung per E-Mail, **Rechten je Bereich** (Videokonferenzen, Kurzlinks, Formulare, Terminumfragen, Terminbuchung, Rechtstexte, Benutzerverwaltung) und **Gruppen**. **CSV-Import** mit Vorlage und Vorschau: Konten mit oder ohne Startpasswort, Gruppen werden angelegt bzw. ergänzt, Konten ohne Passwort auf Wunsch per Mail eingeladen.
- **Zwei-Faktor-Anmeldung** per **Authenticator-App (TOTP)** oder **Code per E-Mail**, mit Notfallcodes; freiwillig oder Pflicht für Admins/alle. „Passwort vergessen“ per Mail-Link.
- **Module** Kurzlinks, Formulare, Terminumfragen, Terminbuchung und Rechtstexte komplett abschaltbar.
- **Sitzungen & Cookies:** technische Übersicht, wer angemeldet ist (Gerät, IP, letzte Aktivität), Inhalt und Eigenschaften der Session-Cookies; Sitzungen einzeln, je Person oder alle anderen beenden. Jede:r sieht unter Profil › Sicherheit die eigenen angemeldeten Geräte; ein neues Passwort meldet alle anderen Geräte ab.
- **E-Mail** über SMTP mit Warteschlange, Wiederholungen und Protokoll; optional Ablage in „Gesendet“ per IMAP. **Alle Mails als Vorlagen bearbeitbar**, mit Platzhaltern und Live-Vorschau.
- **HTTPS** mit Caddy: Start mit selbst signiertem Zertifikat, **Let's Encrypt** per Klick in der Oberfläche.
- **Design & Branding:** Name, Farben, Logo (auch große Dateien – der Server verkleinert), Favicon (sonst automatisch aus dem Logo), Fußzeile, Impressum/Datenschutz; auf Wunsch auch in der Konferenzoberfläche und damit in den Aufnahmen.
- **Moderne Oberfläche** mit Bootstrap 5 und Font Awesome 7, hell/dunkel, durchsuchbare Tabellen, Diagramme – alle Bibliotheken liegen lokal, **keine Verbindung zu Drittanbietern**.
- Seite **„Über dieses Portal“** mit allen verwendeten Komponenten und ihren Lizenzen.

## Dokumentation

| Für wen | Datei |
|---|---|
| Wer den Server **installiert und betreibt** | diese Seite, danach das [Admin-Handbuch](docs/ADMIN-HANDBUCH.md) |
| Wer das Portal **benutzt** (Konferenzen, Kurzlinks, Formulare) | das [Benutzerhandbuch](docs/BENUTZERHANDBUCH.md) |

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

**8. E-Mail einrichten:** Links im Menü auf **Benachrichtigungen** klicken, SMTP-Daten eintragen, **Speichern**, dann **Testmail senden**. Kommt die Mail an, ist alles in Ordnung. Wie die Felder auszufüllen sind, steht im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md#e-mail-einrichten).

**9. SpeechMind verbinden:** Links auf **SpeechMind**, API-Key eintragen, **Speichern**, **Verbindung testen**, ein Projekt auswählen, **Speichern**.

**10. Kolleginnen und Kollegen einladen:** Links auf **Benutzer & Gruppen**, E-Mail-Adressen eintragen, **Rechte** wählen (Videokonferenzen, Kurzlinks, Formulare, Terminumfragen, Terminbuchung, Benutzerverwaltung), **Einladen**. Die Person bekommt eine Mail mit einem Link und legt ihr Passwort selbst fest. Empfehlung: im selben Menü unter „Anmeldung & Zwei-Faktor“ die Zwei-Faktor-Anmeldung mindestens für Admins zur Pflicht machen.

**11. Öffentliches Zertifikat (Let's Encrypt) einschalten:** Sind DNS-Einträge und Ports 80/443 bereit, im Portal links auf **HTTPS & Zertifikat**, **Let's Encrypt** wählen, E-Mail prüfen, **Speichern und anwenden**. Nach etwa einer Minute steht oben „vertrauenswürdig“ und die Browser-Warnung ist weg. Zum gefahrlosen Üben vorher „Testumgebung“ einschalten. Details im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md#https-und-zertifikat).

**Probelauf (empfohlen):** Legen Sie ein Meeting an, treten Sie bei, starten Sie über „…“ › „Aufnahme starten“, sprechen Sie ein paar Sätze, beenden Sie die Aufnahme. Nach kurzer Zeit erscheint sie unter **Aufnahmen** mit MP3.

Fertig. Brauchen Sie Kurzlinks oder Formulare nicht, schalten Sie sie unter **Module** ab. Alles Weitere (Updates, Sicherung, Probleme) steht unten und im [Admin-Handbuch](docs/ADMIN-HANDBUCH.md).

### Update einer bestehenden Installation

```bash
git pull
docker compose up -d --build        # Portal neu bauen; die Datenbank wird automatisch angepasst
docker compose restart prosody      # nur nötig, wenn sich prosody/*.lua geändert hat (trennt laufende Konferenzen kurz)
```

Vorher sichern (siehe [Daten & Sicherung](#daten--sicherung)).

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

| | Eigene Meetings, Aufnahmen, Kurzlinks, Formulare | Fremde Inhalte | Benutzer & Gruppen | Systemeinstellungen |
|---|---|---|---|---|
| Benutzer:in (je nach Recht) | ✓ | nur für sie freigegebene Formulare | – | – |
| Recht „Benutzerverwaltung“ | ✓ | wie oben | ✓ (außer Admin-Konten) | – |
| Admin | ✓ | ✓ | ✓ | ✓ |

Räume, die direkt über die Konferenzadresse eröffnet werden (freie Räume), gehören nicht zum Portal: keine Aufnahme, kein Chatprotokoll.

## Konfiguration

Alle Werte stehen in `.env` (Vorlage: `.env.example`). Die wichtigsten:

| Variable | Bedeutung |
|---|---|
| `MEET_DOMAIN`, `PORTAL_DOMAIN` | Domains für Konferenz und Portal |
| `ACME_EMAIL` | Kontakt für Let's Encrypt |
| `JVB_ADVERTISE_IPS` | Öffentliche IP des Servers (wichtig hinter NAT) |
| `JITSI_IMAGE_VERSION` | Jitsi-Release, für Produktion pinnen |
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

- `data/portal/portal.db` – Benutzer, Gruppen, Meetings, Einstellungen, Transkripte, Kurzlinks mit Statistik, Formulare und Antworten (SQLite)
- `data/portal/audio/` – erzeugte MP3-Dateien
- `data/portal/branding/` – Logo und Favicon
- `data/portal/forms/` – Dateien, die über Formulare hochgeladen wurden
- `data/recordings/` – Jibri-Aufnahmen
- `data/portal-rooms/` – Liste der Portal-Räume für Prosody (wird automatisch erzeugt)
- `data/portal-chat/` – Chat- und Umfrage-Rohdaten aus Portal-Räumen (nach 48 Stunden gelöscht)
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
- Kurzlinks zählen Aufrufe **ohne IP-Adressen** und ohne Cookies.
- Formulare: nur abfragen, was nötig ist; Antworten und Uploads liegen auf dem eigenen Server und werden mit dem Formular gelöscht. CSV/JSON-Anhänge in Benachrichtigungen enthalten personenbezogene Daten – nur an berechtigte Postfächer.
- Zwei-Faktor-Anmeldung schützt Konten mit Zugriff auf Aufnahmen und Formulardaten; für Admins als Pflicht empfohlen.

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
├── main.py              Routen: Login, Zwei-Faktor, Meetings, Aufnahmen, Verwaltung
├── routes_shortlinks.py Kurzlinks, Weiterleitung, QR-Generator
├── routes_forms.py      Formulare: Baukasten, Teilen, Auswertung, Ausfüllen
├── shortlinks.py        Kurzlink-Logik, Statistik, QR-Codes (SVG/PNG/JPG)
├── forms.py             Formular-Logik: Prüfung, Export CSV/JSON, Auswertung, Mails, Freigaben
├── twofa.py             Zwei-Faktor: TOTP (RFC 6238), Mail-Code, Notfallcodes
├── worker.py            Aufnahmen finden, MP3 erzeugen, Upload, Statusabfrage
├── notify.py            Benachrichtigungs-Engine (SMTP/IMAP, Warteschlange, Anhänge)
├── mailtpl.py           Bearbeitbare E-Mail-Vorlagen
├── planning.py          Besprechungen planen, Einladungen versenden
├── ics.py               Kalendereinladungen (iCalendar, RFC 5545)
├── rsvp.py              Zu-/Absagen aus dem IMAP-Postfach auswerten, Postfach-Diagnose
├── access.py            Liste der Portal-Räume für Prosody
├── chat.py              Chatprotokolle und Umfragen aus Portal-Räumen
├── branding.py          Design & Branding (Farben, Logo verkleinern, Favicon, Theme-CSS)
├── proxy.py             Reverse Proxy: Caddyfile erzeugen (inkl. Kurz-Domain), Zertifikate prüfen
├── about.py             Angaben für „Über dieses Portal“ (Komponenten und Lizenzen)
├── user_import.py       Benutzer per CSV importieren (Vorlage, Prüfung, Übernahme)
├── polls.py             Terminumfragen: Vorschläge, Auswertung, Einladungen, Termin festlegen
├── routes_polls.py      Terminumfragen: Verwaltung und öffentliche Abstimmung
├── bookings.py          Terminbuchung: Zeitfenster, Buchen/Verschieben/Absagen, Erinnerungen, Export
├── routes_bookings.py   Terminbuchung: Kalender, Terminliste, öffentliche Buchung, Kalender-Abo
├── cli.py               Notfall-Werkzeug (Passwort setzen, Admin machen, Zwei-Faktor zurücksetzen)
├── speechmind.py        Client für die SpeechMind GraphQL API v2
├── security.py          Passwörter, Verschlüsselung, CSRF, Jitsi-JWT
├── db.py                Datenmodell (SQLAlchemy, SQLite) mit automatischer Migration
├── templates/           Jinja2-Vorlagen
└── static/              app.css, app.js, form-builder.js, form-fill.js, charts.js und vendor/
prosody/                 Prosody-Module: Zugang zu Portal-Räumen, Moderation, Chat und Umfragen
```

**Mitmachen:** Fehler melden, Verbesserungen vorschlagen oder als Pull Request einreichen – gerade Erfahrungen aus anderen Verwaltungen sind willkommen.

## Lizenz

Freie Software unter der **MIT-Lizenz**, siehe [LICENSE](LICENSE): verwenden, kopieren, verändern und weitergeben – auch in Ihrer Verwaltung –, solange der Urheberrechts- und Lizenzhinweis erhalten bleibt. Ohne Gewährleistung.

Verwendete Komponenten stehen unter eigenen freien Lizenzen (u. a. Jitsi Meet Apache-2.0, Prosody MIT, Caddy Apache-2.0, Bootstrap MIT, Font Awesome Free CC BY 4.0/OFL/MIT, Chart.js MIT, FullCalendar MIT); die vollständige Liste zeigt das Portal unter **Über dieses Portal**. SpeechMind ist ein kommerzieller Dienst der SpeechMind GmbH; dieses Projekt ist kein offizielles SpeechMind-Produkt.
