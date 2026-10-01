# Admin-Handbuch

Für alle, die den Videokonferenzserver der Verbandsgemeinde Otterbach-Otterberg betreuen. Die Erstinstallation steht in der [README](../README.md). Alle Befehle werden im Projektordner (dort, wo `docker-compose.yml` liegt) auf dem Server eingegeben.

## Inhalt

1. [Die Oberfläche im Überblick](#die-oberfläche-im-überblick)
2. [Aufnahmen und Transkription](#aufnahmen-und-transkription)
3. [Benutzer verwalten und einladen](#benutzer-verwalten-und-einladen)
4. [Besprechungen planen](#besprechungen-planen)
5. [E-Mail-Vorlagen](#e-mail-vorlagen)
6. [HTTPS und Zertifikat](#https-und-zertifikat)
7. [Design & Branding](#design--branding)
8. [Konferenzen ohne Anmeldung](#konferenzen-ohne-anmeldung)
9. [E-Mail einrichten](#e-mail-einrichten)
10. [SpeechMind einrichten](#speechmind-einrichten)
11. [Aufnahme ohne Ton](#aufnahme-ohne-ton)
12. [Admin-Passwort vergessen](#admin-passwort-vergessen)
13. [Alltag: Start, Stopp, Logs, Update](#alltag-start-stopp-logs-update)
14. [Sicherung und Wiederherstellung](#sicherung-und-wiederherstellung)
15. [Speicherplatz](#speicherplatz)
16. [Wenn etwas nicht geht](#wenn-etwas-nicht-geht)

## Die Oberfläche im Überblick

Nach der Anmeldung zeigt die obere Leiste für Admins:

| Menüpunkt | Wozu |
|---|---|
| **Meetings** | Eigene Räume anlegen und betreten |
| **Aufnahmen** | Alle Aufnahmen als MP3: herunterladen oder an SpeechMind übergeben. *Hier landen Admins nach dem Login.* |
| **Benutzer** | Konten anlegen, einladen, sperren, löschen |
| **Benachrichtigungen** | E-Mail-Versand (SMTP/IMAP), welche Hinweise verschickt werden, Versandprotokoll |
| **SpeechMind** | API-Key, Projekt, Sprache, Protokollart |
| **Besprechung planen** | Termin anlegen und Teilnehmende per Kalendereinladung einladen |
| **E-Mail-Vorlagen** | Texte aller Mails anpassen |
| **HTTPS & Zertifikat** | Selbst signiert oder Let's Encrypt, Zertifikatsstatus |
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
| MP3 bereit + Etikett „kein Ton“ | Die Aufnahme ist stumm | Siehe [Aufnahme ohne Ton](#aufnahme-ohne-ton). Nicht transkribieren, es käme nichts dabei heraus |

Eine MP3 ist bei Fehlern fast immer schon vorhanden und weiter herunterladbar. „Erneut versuchen“ lädt nichts doppelt hoch, wenn der Upload schon gelungen war.

### Aufnahmen löschen

Löschen geht an drei Stellen: über das Papierkorb-Symbol in jeder Tabellenzeile, über **Löschen** in der Aufnahme selbst und für viele Aufnahmen auf einmal (Kästchen links anhaken, das Kästchen in der Kopfzeile wählt alle gefilterten aus, dann **Ausgewählte löschen**).

Ein Dialog fragt, was gelöscht werden soll. Angeboten wird nur, was bei der Aufnahme sinnvoll ist:

| Auswahl | Was passiert | Danach |
|---|---|---|
| **Nur Video und MP3 löschen, Transkript behalten** | Mediendateien weg, Protokoll und Wortlaut bleiben im Portal | Etikett „Medien gelöscht“, Transkript weiter lesbar und als TXT ladbar |
| **Alles hier löschen, bei SpeechMind abrufbar** | Mediendateien und Transkript weg, der Verweis auf das Protokoll bei SpeechMind bleibt | Status „Bei SpeechMind abrufbar“, Knopf **Protokoll von SpeechMind abrufen** holt es jederzeit zurück |
| **Alles löschen** | Eintrag samt Video, MP3 und Transkript weg | Nicht wiederherstellbar. Das Protokoll in SpeechMind selbst bleibt dort bestehen |

Bei der Mehrfachauswahl gilt die gewählte Option für jede Aufnahme, soweit möglich. Was danach nichts mehr enthält (z. B. eine nie transkribierte Aufnahme bei „Nur Video und MP3 löschen“), wird ganz entfernt. Aufnahmen, die gerade verarbeitet werden, werden übersprungen.

**Neu von SpeechMind laden:** Bei transkribierten Aufnahmen holt dieser Knopf Protokoll und Wortlaut erneut ab, z. B. nachdem Sie das Protokoll in SpeechMind überarbeitet haben. Wurde das Protokoll in SpeechMind gelöscht, scheitert der Abruf mit einer Meldung.

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

## Besprechungen planen

Menü **Besprechung planen** (für alle angemeldeten Benutzer:innen).

1. **Titel**, **Beginn**, **Dauer** und optional eine **Tagesordnung** eintragen.
2. **Teilnehmende:** Namen oder Adresse eintippen. Portal-Benutzer werden vorgeschlagen; externe Gäste trägt man einfach mit E-Mail-Adresse ein (Enter, Komma oder Leerzeichen trennt). Externe brauchen kein Konto.
3. **Kopie an mich** (empfohlen): Sie erhalten den Termin selbst als Kalendereintrag.
4. **Planen und einladen**.

Das Portal legt einen Konferenzraum an und schickt **jeder Person eine eigene Mail**. Sie enthält den Einwahllink und den Termin als **Outlook-Besprechungsanfrage** (Annehmen/Ablehnen direkt in Outlook) plus Datei `einladung.ics` für alle anderen Kalender (Thunderbird, Apple, Google). Die Empfänger sehen die anderen Adressen nicht. Zu-/Absagen aus Outlook gehen an die planende Person.

**Auf der Seite des Meetings** (Bereich „Termin & Einladungen“):

| Aktion | Wirkung |
|---|---|
| **Termin ändern** | Neue Zeit, Dauer oder Tagesordnung. Ist „Eingeladene informieren“ an, bekommen alle einen aktualisierten Kalendereintrag, der den alten ersetzt |
| **Weitere Personen einladen** | Nur die neuen Personen bekommen eine Einladung |
| Symbol **Ausladen** | Die Person bekommt eine Absage, der Termin verschwindet aus ihrem Kalender |
| **Einladung erneut senden** | Schickt allen die aktuelle Einladung noch einmal (z. B. wenn jemand sie gelöscht hat) |
| **Absagen** | Alle bekommen eine Absage; der Raum bleibt bestehen |
| **ICS herunterladen** | Termin als Datei, z. B. zum Weiterleiten aus dem eigenen Mailprogramm |

### Zu- und Absagen verfolgen

Bei jeder Person steht in der Spalte **Antwort**, ob sie **zugesagt**, **abgesagt**, **mit Vorbehalt** geantwortet oder einen **neuen Zeitvorschlag** gemacht hat, mit Zeitpunkt und Kommentar. Darüber steht die Zusammenfassung („3 zugesagt, 1 abgesagt, 2 offen“), ebenso auf der Startseite. Die planende Person bekommt zu jeder Antwort eine Mail (abschaltbar).

Voraussetzung: Unter **Benachrichtigungen** ist IMAP eingerichtet und **„Antworten im Postfach auswerten“** eingeschaltet (siehe [E-Mail einrichten](#e-mail-einrichten)). So funktioniert es:

- In neuen Einladungen steht die **Absenderadresse des Portals** als Organisator (angezeigt mit dem Namen der planenden Person). Klickt jemand in Outlook auf „Annehmen“, geht die Antwort an dieses Postfach.
- Das Portal sieht alle zwei Minuten nach, liest nur neue Nachrichten und verbucht die Antworten. Erkannte Antworten werden als gelesen markiert und auf Wunsch in einen Ordner verschoben. Alle anderen Mails bleiben unberührt.
- Wird der Termin geändert, gelten frühere Antworten nicht mehr (wie in Outlook); die Spalte steht wieder auf „Offen“, bis neu geantwortet wird.
- Antwortet jemand, an den die Einladung weitergeleitet wurde, erscheint er mit seiner Antwort in der Liste.
- Wer in Outlook „Antwort nicht senden“ wählt, bleibt auf „Offen“.
- Einladungen, die **vor** dem Einschalten verschickt wurden, schicken ihre Antworten weiterhin direkt an die planende Person; dafür ggf. „Einladung erneut senden“.

Auch für einen bestehenden Raum lässt sich nachträglich ein Termin festlegen. Wird ein Meeting mit anstehendem Termin gelöscht, erhalten die Eingeladenen automatisch eine Absage. Anstehende Besprechungen stehen auf der Startseite unter **Meetings**.

**Ohne eingerichteten E-Mail-Versand** wird die Besprechung trotzdem angelegt, es gehen aber keine Mails raus. Laden Sie dann die ICS-Datei herunter und versenden Sie sie selbst.

## E-Mail-Vorlagen

Menü **E-Mail-Vorlagen** (nur Admins). Hier stehen alle Mails, die das Portal verschickt, gruppiert nach Konten, Besprechungen und Aufnahmen.

- **Betreff** und **Text** sind frei änderbar. Platzhalter in geschweiften Klammern, z. B. `{name}` oder `{link}`, werden beim Versand ersetzt. Ein Klick auf einen Platzhalter unter dem Textfeld fügt ihn an der Cursorposition ein; mit der Maus darüber sehen Sie, was er enthält.
- Rechts zeigt eine **Vorschau** das Ergebnis mit Beispieldaten, schon während Sie tippen.
- **Speichern & Testmail an mich** schickt die Vorlage mit Beispieldaten an Ihre eigene Adresse.
- **Standard** setzt die Vorlage auf den mitgelieferten Text zurück. Angepasste Vorlagen sind mit „angepasst“ markiert.
- `{fusszeile}` ist die Standard-Signatur (Produkt, Organisation, Portal-Adresse). Wer eine eigene Signatur möchte, ersetzt den Platzhalter durch eigenen Text.
- Ein falsch geschriebener Platzhalter bleibt einfach als Text stehen; es geht keine Mail verloren.
- Die Mails sind reiner Text. Links werden in allen gängigen Mailprogrammen anklickbar angezeigt.

## HTTPS und Zertifikat

Menü **HTTPS & Zertifikat**. Ein Reverse Proxy (Caddy) nimmt alle Zugriffe auf Konferenz und Portal entgegen und verschlüsselt sie. Oben sehen Sie für beide Adressen, welches Zertifikat gerade ausgeliefert wird (Aussteller, gültig bis, Fingerabdruck, vertrauenswürdig ja/nein).

### Die zwei Modi

| Modus | Wann sinnvoll | Browser |
|---|---|---|
| **Selbst signiert** (Standard) | Erster Start, Tests, interne Nutzung, wenn noch kein DNS vorhanden ist | Zeigt eine Warnung. Einmal „Erweitert › Trotzdem fortfahren“ wählen, oder das Root-Zertifikat auf den Geräten installieren (s. u.) |
| **Let's Encrypt** | Echtbetrieb im Internet | Keine Warnung. Zertifikate werden automatisch beantragt und rechtzeitig vor Ablauf (nach ca. 60 Tagen) erneuert |

### Let's Encrypt einschalten

**Vorher prüfen** (rechts auf der Seite sehen Sie eine Kontrolle):

1. Beide Domains (Konferenz und Portal) haben einen DNS-Eintrag auf die öffentliche IP des Servers. Die Seite zeigt je Domain „passt“, „andere IP“ oder „DNS fehlt“.
2. Die Ports **80 und 443** sind aus dem Internet erreichbar (Firewall, Router, Rechenzentrum). Let's Encrypt prüft über Port 80. Ob das von außen klappt, kann das Portal nicht testen.

**Dann:**

1. Auf **Let's Encrypt** klicken.
2. E-Mail-Adresse prüfen (für Warnungen, falls eine Erneuerung scheitert).
3. *Empfohlen beim ersten Mal:* **Testumgebung** einschalten. So üben Sie ohne Sperre durch Anfrage-Limits. Die Zertifikate sind dann noch nicht vertrauenswürdig; zum Echtbetrieb später ausschalten und erneut speichern.
4. **Speichern und anwenden**.
5. Die Seite aktualisiert sich alle 10 Sekunden. Nach ca. einer Minute steht „vertrauenswürdig“ und als Aussteller „Let's Encrypt“.

**Klappt es nicht?** Auf dem Server `docker compose logs caddy` ansehen. Häufige Ursachen: DNS zeigt woandershin, Port 80 ist zu, oder es gab zu viele Fehlversuche (Let's Encrypt sperrt kurz; mit der Testumgebung üben). Das Zurückschalten auf „Selbst signiert“ ist jederzeit möglich. Solange kein neues Zertifikat bereit ist, behält der Proxy sein Verhalten bei.

### Zurück zu selbst signiert

Auf **Selbst signiert** klicken und speichern. Nach wenigen Sekunden liefert der Proxy wieder selbst signierte Zertifikate aus.

### Warnung bei selbst signierten Zertifikaten vermeiden

Rechts auf der Seite gibt es **Root-Zertifikat herunterladen**. Dieses Zertifikat installieren Sie auf den Geräten als vertrauenswürdige Stammzertifizierungsstelle (Windows: Doppelklick › „Zertifikat installieren“ › „Vertrauenswürdige Stammzertifizierungsstellen“, in Organisationen per Gruppenrichtlinie). Danach gelten alle vom Proxy ausgestellten Zertifikate als vertrauenswürdig. Das Root-Zertifikat entsteht beim ersten Start des Proxys.

### Gut zu wissen

- **Aufnahmen** funktionieren in beiden Modi. Jibri ist so eingestellt, dass es auch selbst signierte Zertifikate akzeptiert (nur für den Aufruf der eigenen Konferenzseite). Wollen Sie das bei Let's Encrypt abstellen, setzen Sie in der `.env` `JIBRI_IGNORE_CERTIFICATE_ERRORS=false` und starten mit `docker compose up -d` neu. (Bitte nicht `CHROMIUM_FLAGS` setzen: das ersetzt alle Chrome-Einstellungen von Jibri, und die Aufnahmen werden stumm.)
- **HSTS** (Browser merkt sich „nur HTTPS“) wird nur bei Let's Encrypt gesendet. Bei selbst signierten Zertifikaten würde es die Warnung unüberwindbar machen.
- Die vom Portal erzeugte Konfiguration liegt in `data/caddy/conf/Caddyfile`. Bitte nicht von Hand ändern; das Portal überschreibt sie. Fehlerhafte Konfigurationen lädt der Proxy nicht, er bleibt dann bei der letzten funktionierenden.
- Die Domains selbst (`MEET_DOMAIN`, `PORTAL_DOMAIN`) ändern Sie weiterhin in der `.env`.
- Zertifikate und Schlüssel liegen unter `data/caddy/data/`. Sichern Sie den Ordner mit, dann muss nach einer Wiederherstellung nichts neu beantragt werden.

## Design & Branding

Menü **Design & Branding**. Links stellen Sie ein, rechts sehen Sie sofort eine **Vorschau**. Erst **Design speichern** übernimmt die Änderungen.

**Gilt immer (auch bei ausgeschaltetem Design):** Name der Organisation, Produktbezeichnung, Hinweistext auf der Anmeldeseite, Fußzeile, Links zu Impressum und Datenschutzerklärung. Der Name erscheint auch in E-Mails. Lassen Sie ein Feld leer, gilt die Voreinstellung (`BRAND_NAME`/`BRAND_PRODUCT` aus der `.env`).

**Eigenes Design** (großer Schalter ganz oben auf der Seite). Farben, Logo, Favicon, Farbschema und Rundungen wirken **nur, wenn er eingeschaltet ist**. Sobald Sie etwas daran ändern, schaltet er sich von selbst ein; speichern Sie mit **Design speichern**. Ist er aus, sieht das Portal in der neutralen Standardfarbe aus. Ihre Einstellungen bleiben gespeichert und lassen sich jederzeit wieder einschalten. Speichern Sie Änderungen bei ausgeschaltetem Schalter, weist das Portal darauf hin.

| Einstellung | Wirkung |
|---|---|
| Hauptfarbe | Knöpfe, Links, Markierungen. Auf das Farbfeld klicken und eine Farbe wählen oder einen Hex-Wert wie `#0f766e` eintippen. Die Schriftfarbe darauf wird automatisch gut lesbar gewählt |
| Kopfleiste | Farbe der oberen Leiste: Primärfarbe, dunkel oder hell |
| Farbschema | Voreinstellung hell, dunkel oder automatisch nach Geräteeinstellung. Jeder kann es oben rechts selbst umstellen |
| Rundungen | Eckig, Standard oder stark gerundet |
| Logo | PNG, JPG, WebP oder SVG bis 1 MB, am besten mit transparentem Hintergrund. Höhe einstellbar. „Name zeigen“ blendet den Namen neben dem Logo ein oder aus |
| Favicon | Das kleine Symbol im Browser-Tab (PNG, ICO oder SVG bis 256 kB) |

**Auf Standard zurücksetzen** (unten) entfernt alle Design-Einstellungen samt Logo und Favicon.

**Auch in der Konferenz anwenden** (Schalter bei „Farben, Logo & Darstellung“, standardmäßig an): Die Konferenzoberfläche übernimmt das Logo (als Wasserzeichen oben links) und einen Hintergrund in der Hauptfarbe. Weil Jibri die Konferenzoberfläche aufzeichnet, erscheint das Logo auch in den Videoaufnahmen. Änderungen gelten beim nächsten Betreten einer Konferenz (Seite neu laden). Ohne hochgeladenes Logo zeigt die Konferenz kein Wasserzeichen.

**Farbschema:** Steht es auf „Immer hell“ oder „Immer dunkel“, gilt das für alle, und der Umschalter oben rechts wird ausgeblendet. Bei „Automatisch“ kann jede Person selbst umschalten.

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

### Zu- und Absagen auswerten (IMAP)

Im Kasten **„Zu- und Absagen auf Besprechungseinladungen“**:

1. **„Antworten im Postfach auswerten“** einschalten. Das IMAP-Konto muss **das Postfach der Absenderadresse** sein (dorthin schicken Outlook & Co. die Antworten).
2. **Ordner mit den Antworten:** normalerweise `INBOX`.
3. Optional **„Verarbeitete Antworten verschieben nach“**, z. B. `Termin-Antworten` (Ordner vorher im Postfach anlegen). Leer lassen = nur als gelesen markieren.
4. **Speichern**, dann unten **„Antworten jetzt abrufen“** zum Testen.

Unter dem Kasten steht, wann zuletzt abgerufen wurde und ob dabei ein Fehler auftrat. Beim ersten Abruf werden die Nachrichten der letzten 14 Tage geprüft, danach nur noch neue.

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

## Aufnahme ohne Ton

**Erkennen:** Das Portal misst jede neue MP3. Enthält sie keinen hörbaren Ton, steht in der Aufnahmenliste das gelbe Etikett **„kein Ton“** mit einer Erklärung; auf Wunsch kommt zusätzlich eine E-Mail („Aufnahme ohne Ton“, gehört zu den Hinweisen „Verarbeitung fehlgeschlagen“). Fehlt die Tonspur im Video ganz, steht „Fehlgeschlagen: Das Video enthält keine Tonspur“.

**Zuerst die einfache Frage:** Jibri nimmt das auf, was in der Konferenz zu hören ist. War beim Test niemand zu hören (Mikrofon stumm, allein im Raum, nichts abgespielt), ist die Aufnahme zu Recht stumm. **Test richtig machen:** mit zwei Geräten in denselben Raum, auf einem Gerät sprechen oder Musik abspielen (Mikrofon an), Aufnahme starten, 20 Sekunden warten, beenden.

**Diagnose auf dem Server** (im Projektordner, nur lesend):

```bash
./scripts/diagnose-recording.sh
```

Das Skript prüft die neueste Aufnahme (hat das Video eine Tonspur, wie laut ist sie), das Tonsystem im Jibri-Container (PulseAudio) und das Aufnahme-Protokoll von Jibri. Am Ende steht eine Auswertung:

| Ergebnis | Bedeutung | Was tun |
|---|---|---|
| „Enthält hörbaren Ton“ | Video ist in Ordnung | In der Aufnahme auf **„MP3 neu erzeugen“** klicken |
| „Tonspur vorhanden, aber STUMM“ | Es war nichts zu hören, oder Jibri erfasst den Ton nicht | Test wie oben mit zwei Geräten wiederholen. Bleibt es stumm: Ausgabe des Skripts weitergeben |
| „Video hat KEINE Tonspur“ | Jibri hat den Ton nicht erfasst | Ausgabe (Abschnitte 4 und 5) weitergeben: dort steht, ob das Tonsystem im Container läuft |

**Bekannte Ursache (bis Oktober 2026 in diesem Projekt):** Die `docker-compose.yml` setzte für Jibri `CHROMIUM_FLAGS`. Das ersetzt alle Chrome-Einstellungen von Jibri, auch die Freigabe, Ton ohne Mausklick abzuspielen (`--autoplay-policy=no-user-gesture-required`). Chrome spielte den Ton der Teilnehmenden dann gar nicht ab, und Jibri nahm Stille auf. Behoben durch `IGNORE_CERTIFICATE_ERRORS=true`. Prüfen:

```bash
docker compose exec jibri sh -c 'cat /etc/jitsi/jibri/jibri.conf' | grep -A12 "chrome {"
```

In der Ausgabe muss `--autoplay-policy=no-user-gesture-required` stehen. Das Diagnoseskript prüft das ebenfalls.

**Wichtig zu wissen:** Aktuelle Jibri-Versionen nehmen den Ton über PulseAudio im Container auf. Das Kernelmodul `snd-aloop` auf dem Server wird dafür **nicht** gebraucht. Nur ältere Jibri-Versionen (ALSA) brauchen es.

**Alte stumme Aufnahmen:** Der Ton wurde nie aufgezeichnet und lässt sich nicht nachträglich herstellen. „MP3 neu erzeugen“ bringt nur dann etwas, wenn das Video doch Ton enthält. Stumme Aufnahmen können Sie löschen, bevor sie Speicher belegen.

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

**Was sichern?** Den Ordner `data/portal/` (Datenbank, MP3-Dateien), `data/caddy/` (Zertifikate) und die Datei `.env`. Bei Bedarf zusätzlich `data/recordings/` (Videos).

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
| Browser zeigt eine Zertifikatswarnung | Normal im Modus „Selbst signiert“. Dauerhaft beheben: Let's Encrypt einschalten (Menü HTTPS & Zertifikat) oder das Root-Zertifikat installieren |
| Let's Encrypt bleibt auf „wird beantragt“ | DNS und Port 80/443 prüfen, `docker compose logs caddy` lesen, zum Üben die Testumgebung nutzen |
| Portal-Seite lädt nicht | `docker compose ps`, `docker compose logs caddy portal`. Zeigt der Browser einen Zertifikatsfehler: DNS prüfen und ein paar Minuten warten |
| Konferenz öffnet, aber kein Bild/Ton | UDP 10000 nicht offen oder `JVB_ADVERTISE_IPS` ist nicht die öffentliche IP |
| Beitritt endet in einer Schleife auf der Login-Seite | `JWT_*`-Werte in `.env` geändert? Dann `docker compose up -d --force-recreate` |
| MP3 ist stumm, Etikett „kein Ton“ | Siehe [Aufnahme ohne Ton](#aufnahme-ohne-ton): `./scripts/diagnose-recording.sh` |
| Im Video ist ein Fensterrahmen (IceWM) zu sehen, Konferenz füllt nicht das Bild | Chrome in Jibri läuft ohne Vollbild (`--kiosk`). Ursache war dieselbe falsche Einstellung wie bei stummen Aufnahmen; mit aktueller `docker-compose.yml` behoben. Prüfen: `./scripts/diagnose-recording.sh` |
| Zu-/Absagen erscheinen nicht | Unter **Benachrichtigungen** „Antworten im Postfach auswerten“ an? IMAP-Konto = Postfach der Absenderadresse? Fehlermeldung unter dem Kasten lesen, „Antworten jetzt abrufen“ testen. Alte Einladungen ggf. erneut senden |
| Designänderungen sind nicht zu sehen | Schalter „Eigenes Design“ oben auf der Seite einschalten und speichern. Für die Konferenz zusätzlich „Auch in der Konferenz anwenden“ |
| Aufnahme-Knopf fehlt | Nur angemeldete Benutzer dürfen aufnehmen; Jibri-Log prüfen (`docker compose logs jibri`) |
| Aufnahme erscheint nicht unter „Aufnahmen“ | In `data/recordings/<sitzung>/` muss eine Datei `.finalized` liegen. Fehlt sie: `chmod +x jibri/finalize.sh`, Jibri neu starten |
| Status „Fehlgeschlagen“ | Meldung in der Zeile lesen, Ursache beheben (z. B. SpeechMind-Key), **Erneut versuchen** |
| Einladungsmail kommt nicht an | Spam-Ordner prüfen; **Benachrichtigungen** → Versandprotokoll ansehen; Testmail senden |
| „Zu viele Versuche“ | Eingebaute Bremse gegen Passwort-Raten: ca. 10 Minuten warten |
| Link „ungültig oder abgelaufen“ | Neuen Link anfordern (Admin: „Einladung erneut senden“, Benutzer: „Passwort vergessen?“) |
| Anderes | `docker compose logs --tail 100 portal` und die Meldung an die Betreuung weitergeben |
