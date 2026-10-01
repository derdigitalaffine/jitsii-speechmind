# Admin-Handbuch

Für alle, die den Videokonferenzserver der Verbandsgemeinde Otterbach-Otterberg betreuen. Die Erstinstallation steht in der [README](../README.md). Alle Befehle werden im Projektordner (dort, wo `docker-compose.yml` liegt) auf dem Server eingegeben.

## Inhalt

1. [Die Oberfläche im Überblick](#die-oberfläche-im-überblick)
2. [Aufnahmen und Transkription](#aufnahmen-und-transkription)
3. [Benutzer verwalten und einladen](#benutzer-verwalten-und-einladen)
4. [Design & Branding](#design--branding)
5. [Konferenzen ohne Anmeldung](#konferenzen-ohne-anmeldung)
6. [E-Mail einrichten](#e-mail-einrichten)
7. [SpeechMind einrichten](#speechmind-einrichten)
8. [Admin-Passwort vergessen](#admin-passwort-vergessen)
9. [Alltag: Start, Stopp, Logs, Update](#alltag-start-stopp-logs-update)
10. [Sicherung und Wiederherstellung](#sicherung-und-wiederherstellung)
11. [Speicherplatz](#speicherplatz)
12. [Wenn etwas nicht geht](#wenn-etwas-nicht-geht)

## Die Oberfläche im Überblick

Nach der Anmeldung zeigt die obere Leiste für Admins:

| Menüpunkt | Wozu |
|---|---|
| **Meetings** | Eigene Räume anlegen und betreten |
| **Aufnahmen** | Alle Aufnahmen als MP3: herunterladen oder an SpeechMind übergeben. *Hier landen Admins nach dem Login.* |
| **Benutzer** | Konten anlegen, einladen, sperren, löschen |
| **Benachrichtigungen** | E-Mail-Versand (SMTP/IMAP), welche Hinweise verschickt werden, Versandprotokoll |
| **SpeechMind** | API-Key, Projekt, Sprache, Protokollart |
| **Design & Branding** | Name, Farben, Logo, Fußzeile, Impressum-Link |
| *Ihr Name* (oben rechts) | Profil, Passwort ändern, Abmelden |
| Halbmond-Symbol (oben rechts) | Hell, Dunkel oder automatisch umschalten (gilt nur für Sie) |

Auf dem Handy öffnet das Symbol mit den drei Strichen oben links das Menü.

**Tabellen bedienen:** Oben links ins Feld „Suchen …“ tippen filtert sofort alle Spalten. Ein Klick auf eine Spaltenüberschrift sortiert, ein zweiter dreht die Reihenfolge um. Unten rechts blättern Sie, oben rechts stellen Sie ein, wie viele Zeilen pro Seite erscheinen. Auf schmalen Bildschirmen blendet die Tabelle Spalten aus; ein Klick auf das Plus-Symbol in der Zeile zeigt sie.

## Aufnahmen und Transkription

**Der Ablauf:**

1. Jemand startet in der Konferenz die Aufnahme und beendet sie später.
2. Innerhalb von etwa 15 Sekunden findet das Portal die Aufnahme und erzeugt die MP3 (Status „MP3 wird erzeugt“, dann „MP3 bereit“).
3. Wenn eingestellt, bekommt die Besitzerin oder der Besitzer des Meetings eine E-Mail „Neue Aufnahme“.
4. Unter **Aufnahmen** gibt es pro Zeile zwei Möglichkeiten:
   - **MP3 herunterladen** – die Datei bleibt dann nur bei Ihnen.
   - **In SpeechMind bearbeiten** – die MP3 geht an SpeechMind, das Protokoll erscheint nach einiger Zeit im Portal (etwa die halbe Aufnahmedauer).

**Es wird nie automatisch transkribiert.** Das ist Absicht (Datenschutz, Kosten).

**Status-Bedeutungen**

| Status | Bedeutung | Was tun? |
|---|---|---|
| MP3 wird erzeugt | Portal wandelt gerade um | Warten, Seite aktualisiert sich |
| MP3 bereit | Fertig, nichts passiert von allein | Herunterladen oder an SpeechMind übergeben |
| Wartet / Wird hochgeladen / SpeechMind transkribiert | Läuft | Warten |
| Transkript fertig | Protokoll und Wortlaut stehen im Portal | Lesen, als TXT laden |
| Fehlgeschlagen | Meldung steht in der Zeile | Ursache beheben, dann **Erneut versuchen** |

Eine MP3 ist bei Fehlern fast immer schon vorhanden und weiter herunterladbar. „Erneut versuchen“ lädt nichts doppelt hoch, wenn der Upload schon gelungen war.

**Löschen:** In der Aufnahme unten „Aufnahme löschen“ entfernt Video, MP3 und Transkript vom Server. Das Protokoll in SpeechMind bleibt dort bestehen.

## Benutzer verwalten und einladen

**Neue Person einladen**

1. **Benutzer** öffnen.
2. Im Feld „E-Mail-Adressen“ eine oder **mehrere** Adressen eintippen oder aus einer Liste einfügen. Mit Enter, Komma oder Leerzeichen wird jede Adresse zum Etikett; ungültige Adressen werden nicht übernommen. Den Namen leitet das Portal aus der Adresse ab (`max.muster@…` → „Max Muster“); die Person kann ihn im Profil ändern. Bei nur einer Adresse können Sie den Namen im Feld darunter selbst vorgeben. „Administrator:in“ nur einschalten, wenn die Person Einstellungen und alle Aufnahmen verwalten soll.
3. **Einladen** klicken.
4. Die Person bekommt eine E-Mail mit einem Link (72 Stunden gültig, einmal benutzbar) und legt ihr Passwort selbst fest. Danach ist sie angemeldet.

**Ist kein E-Mail-Versand eingerichtet**, zeigt das Portal den Link **einmalig** oben auf der Seite. Kopieren Sie ihn und geben Sie ihn weiter (z. B. persönlich oder per Telefon vorlesen). Danach ist er weg; über „Einladung erneut senden“ gibt es einen neuen.

**Weitere Aktionen pro Person** (Symbole rechts in der Zeile; Maus darüber halten zeigt den Namen)

| Aktion | Wirkung |
|---|---|
| Einladung erneut senden | Neuer Link, alter wird ungültig (bei noch nicht angenommener Einladung) |
| Passwort-Link senden | Neuer Link zum Vergeben eines Passworts (bei bestehenden Konten) |
| Sperren / Entsperren | Anmeldung nicht mehr möglich / wieder möglich; Daten bleiben |
| Zum Admin machen / Admin-Recht entziehen | Rolle ändern |
| Löschen | Konto und dessen Meetings weg; Aufnahmen bleiben für Admins sichtbar |

Das eigene Konto lässt sich hier nicht sperren oder löschen (Schutz vor Aussperren).

**Passwort vergessen (Benutzer:innen):** Auf der Login-Seite „Passwort vergessen?“ klicken, E-Mail eingeben. Der Link ist 2 Stunden gültig. Aus Sicherheitsgründen antwortet das Portal immer gleich, auch wenn die Adresse unbekannt ist.

**Das Standard-Admin-Konto** wird beim allerersten Start angelegt. Legen Sie danach ein persönliches Admin-Konto für jede zuständige Person an und sperren Sie das Standardkonto oder behalten Sie es mit sicherem Passwort.

## Design & Branding

Menü **Design & Branding**. Links stellen Sie ein, rechts sehen Sie sofort eine **Vorschau**. Erst **Design speichern** übernimmt die Änderungen.

**Gilt immer (auch bei ausgeschaltetem Design):** Name der Organisation, Produktbezeichnung, Hinweistext auf der Anmeldeseite, Fußzeile, Links zu Impressum und Datenschutzerklärung. Der Name erscheint auch in E-Mails. Lassen Sie ein Feld leer, gilt die Voreinstellung (`BRAND_NAME`/`BRAND_PRODUCT` aus der `.env`).

**Eigenes Design** (Schalter im Kasten „Eigenes Design“). Ist er aus, sieht das Portal in der neutralen Standardfarbe aus; Ihre Einstellungen bleiben gespeichert und lassen sich jederzeit wieder einschalten.

| Einstellung | Wirkung |
|---|---|
| Hauptfarbe | Knöpfe, Links, Markierungen. Auf das Farbfeld klicken und eine Farbe wählen oder einen Hex-Wert wie `#0f766e` eintippen. Die Schriftfarbe darauf wird automatisch gut lesbar gewählt |
| Kopfleiste | Farbe der oberen Leiste: Primärfarbe, dunkel oder hell |
| Farbschema | Voreinstellung hell, dunkel oder automatisch nach Geräteeinstellung. Jeder kann es oben rechts selbst umstellen |
| Rundungen | Eckig, Standard oder stark gerundet |
| Logo | PNG, JPG, WebP oder SVG bis 1 MB, am besten mit transparentem Hintergrund. Höhe einstellbar. „Name zeigen“ blendet den Namen neben dem Logo ein oder aus |
| Favicon | Das kleine Symbol im Browser-Tab (PNG, ICO oder SVG bis 256 kB) |

**Auf Standard zurücksetzen** (unten) entfernt alle Design-Einstellungen samt Logo und Favicon.

> **Hinweis:** Das Design betrifft das Portal (Anmeldung, Verwaltung, E-Mails). Die Konferenzoberfläche von Jitsi selbst übernimmt nur den Namen (`BRAND_NAME` in der `.env`). Ein eigenes Logo in Jitsi ist über die Jitsi-Konfiguration möglich (siehe Jitsi-Dokumentation, „Customization“).

## Konferenzen ohne Anmeldung

Unter **Benutzer** gibt es den Kasten „Konferenzen ohne Anmeldung“ mit einem Schalter.

- **Freigegeben (Standard):** Auf der Anmeldeseite erscheint „Konferenz ohne Anmeldung starten“. Die Person gibt ihren Namen ein, bekommt sofort einen eigenen Raum (Name beginnt mit `offen-`) und kann den Link weitergeben. Angemeldete Benutzer finden im Dashboard den Knopf **Schnellkonferenz**.
- **Keine Aufnahmen:** In diesen Räumen fehlt das Aufnahme-Recht. Sollte jemand die Aufnahme trotzdem auslösen, **verwirft das Portal sie automatisch** (Eintrag im Log: „Aufnahme eines offenen Raums … verworfen“). Offene Räume tauchen nie unter „Aufnahmen“ auf.
- **Wer ist Gastgeber:in?** Nur die Person, die den Raum im Portal eröffnet hat (an ihren Browser gebunden, 12 Stunden). Wer den Link nur kennt, kommt als Gast hinein, sobald die Gastgeberin oder der Gastgeber da ist. Ruft jemand anderes den Raum zuerst als Moderator auf, sieht er den Hinweis „Bitte warten“.
- **Missbrauchsschutz:** Pro Adresse sind nur wenige Raumstarts in kurzer Zeit möglich. Wenn Sie keine offenen Konferenzen wünschen, schalten Sie den Schalter aus; dann sind sie sofort gesperrt.
- Normale Räume bleiben davon unberührt: Wer dort moderieren oder aufnehmen will, braucht ein Konto.

## E-Mail einrichten

Menü **Benachrichtigungen**. Ohne diese Einstellung funktioniert alles, nur gibt es keine Mails (Einladungslinks müssen dann von Hand weitergegeben werden).

### Postausgang (SMTP) – Pflicht

Diese Werte nennt Ihnen die IT oder der E-Mail-Anbieter.

| Feld | Was eintragen | Beispiel |
|---|---|---|
| Server | Name des Mailservers | `smtp.example.org` |
| Port + Verschlüsselung | **587 mit STARTTLS** (üblich) oder **465 mit SSL/TLS** | 587 / STARTTLS |
| Benutzername | Meist die E-Mail-Adresse des Postfachs | `videokonferenz@example.org` |
| Passwort | Das Passwort des Postfachs (wird verschlüsselt gespeichert) | |
| Absenderadresse | Muss der Mailserver für dieses Konto erlauben | `videokonferenz@example.org` |
| Absendername | So erscheint der Absender beim Empfänger | `Verbandsgemeinde Otterbach-Otterberg` |

**Dann: Speichern → „Testmail an …“ klicken.** Die Testmail geht an Ihre eigene Adresse. Kommt „Testnachricht an … verschickt“, passt es. Sonst steht der genaue Fehler in der roten Meldung.

**Häufige Fehler**

| Meldung enthält | Ursache |
|---|---|
| `Connection refused`, `timed out` | Falscher Server/Port, oder die Firewall des Servers blockt ausgehend (Port 587/465 freigeben) |
| `Authentication` / `535` | Benutzername oder Passwort falsch. Bei manchen Anbietern ist ein eigenes „App-Passwort“ nötig |
| `SSL` / `wrong version number` | Port und Verschlüsselung passen nicht zusammen (587 ↔ STARTTLS, 465 ↔ SSL/TLS) |
| `Sender address rejected` | Absenderadresse gehört nicht zum Konto, anderen Absender eintragen |

### Postfach (IMAP) – optional

Nur nötig, wenn **Kopien aller verschickten Mails im Ordner „Gesendet“** des Postfachs landen sollen (Nachvollziehbarkeit). Server, Port (meist 993/SSL), Benutzername und Passwort eintragen, „Kopie gesendeter Nachrichten ablegen“ ankreuzen und den Ordnernamen angeben (oft `Sent`, `Gesendet` oder `INBOX.Sent`). **Speichern → „IMAP testen“.** Das Portal prüft dabei auch, ob der Ordner existiert.

Scheitert nur die Ablage, geht die Mail trotzdem raus; der Fehler steht im Log (`docker compose logs portal`).

### Welche Hinweise werden verschickt

Einladungen und Passwort-Links gehen immer. Zusätzlich schaltbar:

- Neue Aufnahme liegt als MP3 bereit
- Transkript von SpeechMind ist fertig
- Verarbeitung ist fehlgeschlagen

Empfänger ist die Besitzerin bzw. der Besitzer des Meetings, bei Räumen ohne Meeting alle aktiven Admins.

### Versandprotokoll

Ganz unten auf der Seite stehen die letzten 50 Nachrichten. Das Portal versucht fehlgeschlagene Mails bis zu fünfmal (nach 1, 5, 15, 60, 240 Minuten). Danach steht „fehlgeschlagen“ mit Fehlertext, und Sie können **Erneut senden** klicken, sobald die Ursache behoben ist.

## SpeechMind einrichten

Menü **SpeechMind**:

1. API-Key eintragen (kommt von SpeechMind), **Speichern**.
2. **Verbindung testen.** Funktioniert der Key, erscheint die Projektliste.
3. Projekt wählen (oder „Neues Projekt anlegen“), **Speichern**.
4. Standard-Protokollart und -Sprache wählen.

Weitere Schalter:

- **Eigene SpeechMind-Keys erlauben** – Benutzer können im Profil einen eigenen Zugang hinterlegen (z. B. andere Abrechnungsstelle).
- **Video nach fertigem Transkript löschen** – spart Speicher. Die MP3 bleibt erhalten.
- **Teilnehmernamen als Sprecherliste übergeben** – standardmäßig aus (Datenschutz).

## Admin-Passwort vergessen

Wenn noch ein anderer Admin existiert: Dieser klickt unter **Benutzer** bei Ihnen auf „Passwort-Link senden“.

Wenn nicht: Auf dem Server (Notfallwerkzeug):

```bash
docker compose exec portal python -m app.cli users                       # Konten anzeigen
docker compose exec portal python -m app.cli set-password admin@example.org   # neues Passwort setzen
docker compose exec portal python -m app.cli make-admin kollege@example.org   # Konto zum aktiven Admin machen
```

Das Passwort wird nicht angezeigt, wenn Sie es eintippen. Das ist normal.

## Alltag: Start, Stopp, Logs, Update

```bash
docker compose ps                  # Was läuft?
docker compose logs -f portal      # Portal-Meldungen live (Strg+C beendet die Anzeige)
docker compose logs -f jibri       # Aufnahme-Meldungen
docker compose restart portal      # Nur das Portal neu starten
docker compose down                # Alles anhalten (Daten bleiben)
docker compose up -d               # Alles starten
```

**Einstellungen in `.env` geändert?** Dann: `docker compose up -d --force-recreate`.

**Portal aktualisieren:**

```bash
git pull
docker compose up -d --build
```

Die Datenbank wird beim Start automatisch auf das neue Format gebracht. Vorher bitte [sichern](#sicherung-und-wiederherstellung).

**Jitsi aktualisieren:** In `.env` bei `JITSI_IMAGE_VERSION` die neue Version eintragen (Liste: <https://github.com/jitsi/docker-jitsi-meet/releases>), dann `docker compose pull && docker compose up -d`.

## Sicherung und Wiederherstellung

**Was sichern?** Den Ordner `data/portal/` (Datenbank, MP3-Dateien) und die Datei `.env`. Bei Bedarf zusätzlich `data/recordings/` (Videos).

**Sauber sichern (Datenbank im laufenden Betrieb):**

```bash
docker compose exec portal python -c "import sqlite3; s=sqlite3.connect('/data/portal.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
```

Danach `data/portal/backup.db` und `data/portal/audio/` wegkopieren, z. B. mit `rsync -a data/portal/ /pfad/zur/sicherung/`.

**Wiederherstellen:** `docker compose down`, gesicherten Ordner `data/portal/` zurückkopieren (`backup.db` als `portal.db`), dieselbe `.env` verwenden, `docker compose up -d`.

> Die `.env` muss **dieselbe** sein wie zum Zeitpunkt der Sicherung (besonders `PORTAL_SECRET_KEY`). Sonst sind gespeicherte Passwörter (SMTP, IMAP) und der SpeechMind-Key unlesbar; sie müssen dann neu eingegeben werden.

## Speicherplatz

Videos sind groß (grob 0,5–1 GB pro Stunde), MP3s klein (ca. 30 MB pro Stunde).

```bash
df -h .                            # Freier Platz
du -sh data/recordings data/portal # Was braucht wie viel?
```

Platz sparen: Aufnahmen nach Gebrauch in der Oberfläche löschen oder unter **SpeechMind** „Video nach fertigem Transkript löschen“ einschalten. Läuft der Platz voll, werden keine Aufnahmen mehr gespeichert.

## Wenn etwas nicht geht

| Problem | Lösung |
|---|---|
| Portal-Seite lädt nicht | `docker compose ps`, `docker compose logs caddy portal`. Zeigt der Browser einen Zertifikatsfehler: DNS prüfen und ein paar Minuten warten |
| Konferenz öffnet, aber kein Bild/Ton | UDP 10000 nicht offen oder `JVB_ADVERTISE_IPS` ist nicht die öffentliche IP |
| Beitritt endet in einer Schleife auf der Login-Seite | `JWT_*`-Werte in `.env` geändert? Dann `docker compose up -d --force-recreate` |
| Aufnahme-Knopf fehlt | Nur angemeldete Benutzer dürfen aufnehmen; Jibri-Log prüfen (`docker compose logs jibri`) |
| Aufnahme erscheint nicht unter „Aufnahmen“ | In `data/recordings/<sitzung>/` muss eine Datei `.finalized` liegen. Fehlt sie: `chmod +x jibri/finalize.sh`, Jibri neu starten |
| Status „Fehlgeschlagen“ | Meldung in der Zeile lesen, Ursache beheben (z. B. SpeechMind-Key), **Erneut versuchen** |
| Einladungsmail kommt nicht an | Spam-Ordner prüfen; **Benachrichtigungen** → Versandprotokoll ansehen; Testmail senden |
| „Zu viele Versuche“ | Eingebaute Bremse gegen Passwort-Raten: ca. 10 Minuten warten |
| Link „ungültig oder abgelaufen“ | Neuen Link anfordern (Admin: „Einladung erneut senden“, Benutzer: „Passwort vergessen?“) |
| Anderes | `docker compose logs --tail 100 portal` und die Meldung an die Betreuung weitergeben |
