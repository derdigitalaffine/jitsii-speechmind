# Admin-Handbuch

Für alle, die das Portal der Verbandsgemeinde Otterbach-Otterberg betreuen: Videokonferenzen mit Aufnahme und Transkription, Besprechungsplanung, Kurzlinks mit QR-Codes und Formularserver. Die Erstinstallation steht in der [README](../README.md), die Bedienung für Mitarbeitende im [Benutzerhandbuch](BENUTZERHANDBUCH.md). Alle Befehle werden im Projektordner (dort, wo `docker-compose.yml` liegt) auf dem Server eingegeben.

## Inhalt

1. [Die Oberfläche im Überblick](#die-oberfläche-im-überblick)
2. [Benutzer, Rechte und Gruppen](#benutzer-rechte-und-gruppen)
2a. [Körperschaften und Einrichtungen](#körperschaften-und-einrichtungen)
3. [Anmeldung und Zwei-Faktor](#anmeldung-und-zwei-faktor)
4. [Module ein- und ausschalten](#module-ein--und-ausschalten)
5. [Aufnahmen und Transkription](#aufnahmen-und-transkription) (mit Chatprotokoll und Umfragen)
6. [Besprechungen planen](#besprechungen-planen)
7. [Kurzlinks und QR-Codes](#kurzlinks-und-qr-codes)
8. [Formulare](#formulare)
8e. [Online-Anträge](#online-anträge) (mit [Prozesse und Workflow](#prozesse-und-workflow))
8g. [Ablage (DMS)](#ablage-dms)
8f. [Kartenlayer und Kartenbrowser](#kartenlayer-und-kartenbrowser) (mit [Adresssuche (Nominatim)](#adresssuche-nominatim))
8a. [Terminumfragen](#terminumfragen) und [Abstimmungen](#abstimmungen-und-wahlen)
8b. [Terminbuchung](#terminbuchung)
8h. [Ressourcenbuchung](#ressourcenbuchung)
8j. [BlueOtter Krankmelder](#blueotter-krankmelder)
8i. [Zahlungen (PayPal, Überweisung, bar)](#zahlungen-paypal-überweisung-bar)
8c. [Rechtstexte (Ortsrecht online)](#rechtstexte-ortsrecht-online)
8d. [Sitzungen & Cookies](#sitzungen--cookies)
9. [E-Mail-Vorlagen](#e-mail-vorlagen)
10. [HTTPS und Zertifikat](#https-und-zertifikat) (mit [Eigene Domains je Modul](#eigene-domains-je-modul))
11. [Design & Branding](#design--branding)
12. [Räume und Zugang](#räume-und-zugang)
13. [E-Mail einrichten](#e-mail-einrichten)
14. [SpeechMind einrichten](#speechmind-einrichten)
15. [Aufnahme ohne Ton](#aufnahme-ohne-ton)
16. [Admin-Passwort vergessen](#admin-passwort-vergessen)
17. [Alltag: Start, Stopp, Logs, Update](#alltag-start-stopp-logs-update)
18. [Sicherung und Wiederherstellung](#sicherung-und-wiederherstellung) (Sicherheitsaudit: [SICHERHEITSAUDIT-2026-10.md](SICHERHEITSAUDIT-2026-10.md))
19. [Speicherplatz](#speicherplatz)
20. [Wenn etwas nicht geht](#wenn-etwas-nicht-geht)

## Die Oberfläche im Überblick

Das Menü links ist nach Bereichen gegliedert. Jede Person sieht nur, wofür sie freigeschaltet ist; Admins sehen alles. Nach der Anmeldung landen alle – auch Admins – auf der **Übersicht** (Startseite mit Kacheln, siehe [Benutzerhandbuch](BENUTZERHANDBUCH.md#2-die-oberfläche)); Meetings stehen jetzt unter `/meetings`.

| Bereich | Menüpunkt | Wozu |
|---|---|---|
| – | **Übersicht** | Startseite: Aufgaben und Fristen, Antragseingang, Termine, Umfragen, Buchungen, Zum Ausfüllen, neue Antworten, Ablage, Schnellzugriff – je Person sortier- und ausblendbar |
| Videokonferenzen | **Meetings** | Eigene Räume anlegen und betreten, anstehende Besprechungen |
| | **Besprechung planen** | Termin anlegen und Teilnehmende per Kalendereinladung einladen |
| Kurzlinks | **Kurzlinks** | Kurze Adressen mit Statistik, QR-Generator; für Admins die Einstellungen (Kurz-Domain) |
| Formulare | **Formulare** | Eigene und geteilte Formulare bauen, verteilen, auswerten |
| | **Zum Ausfüllen** | Formulare, zu denen man eingeladen ist |
| | **Datenblöcke** | Zentrale Bibliothek wiederkehrender Feldgruppen (Recht „Formularbausteine“ zum Ändern) |
| Ablage | **Recherche** / **Aktenplan** | Ablage (DMS) durchsuchen, Vorgänge ablegen; Aktenplan, Rechte und Löschfristen (Recht „Aktenplan verwalten“) |
| Verwaltung | **Aufnahmen** | Alle Aufnahmen: MP3, Chat, Umfragen, Übergabe an SpeechMind |
| | **Benutzer & Gruppen** | Konten, Rechte, Gruppen, Anmelde-Einstellungen (Zwei-Faktor), Konferenzen ohne Anmeldung. *Auch für Personen mit dem Recht „Benutzerverwaltung“* |
| | **Kartenlayer** | Kartenlayer, Startausschnitt, Adresssuche (Nominatim). *Auch für Personen mit dem Recht „Kartenlayer & Geocoding“* |
| | **Module** | Kurzlinks, Formulare, Online-Anträge, Ablage, Karten usw. komplett ein- oder ausschalten |
| | **Benachrichtigungen** | E-Mail-Versand (SMTP/IMAP), Zu-/Absagen, Postfach-Diagnose, Versandprotokoll |
| | **E-Mail-Vorlagen** | Texte aller Mails anpassen |
| | **SpeechMind** | API-Key, Projekt, Sprache, Protokollart |
| | **HTTPS & Zertifikat** | Selbst signiert oder Let's Encrypt, Zertifikatsstatus |
| | **Design & Branding** | Name, Farben, Logo, Favicon, Fußzeile, Impressum-Link |
| oben rechts | *Ihr Name* | Profil, Sicherheit (Zwei-Faktor), Über dieses Portal, Abmelden |
| oben rechts | Halbkreis-Symbol | Hell, Dunkel oder automatisch (gilt nur für Sie) |

Auf dem Handy öffnet das Symbol mit den drei Strichen oben links das Menü. Die Seite **Über dieses Portal** (Fußzeile) nennt die Herausgeberin, die Open-Source-Lizenz und alle verwendeten Komponenten mit ihren Lizenzen.

**Tabellen bedienen:** Oben links ins Feld „Suchen …“ tippen filtert sofort alle Spalten. Ein Klick auf eine Spaltenüberschrift sortiert, ein zweiter dreht die Reihenfolge um. Unten rechts blättern Sie, oben rechts stellen Sie ein, wie viele Zeilen pro Seite erscheinen. Auf schmalen Bildschirmen blendet die Tabelle Spalten aus; ein Klick auf das Plus-Symbol in der Zeile zeigt sie.

## Benutzer, Rechte und Gruppen

Menü **Benutzer & Gruppen**. Erreichbar für Admins und für Personen mit dem Recht **Benutzerverwaltung**.

### Rechte

Jede Person bekommt einzeln die Bereiche freigeschaltet, die sie braucht:

| Recht | Erlaubt |
|---|---|
| **Videokonferenzen** | Meetings anlegen, Besprechungen planen, moderieren, aufnehmen, eigene Aufnahmen transkribieren |
| **Kurzlinks** | Kurzlinks anlegen, auswerten, QR-Codes erzeugen |
| **Formulare** | Formulare erstellen, verteilen, auswerten (geteilte Formulare und „Zum Ausfüllen“ sehen alle, auch ohne dieses Recht). Datenblöcke aus der Bibliothek einfügen kann jede:r mit diesem Recht |
| **Formularbausteine** | Datenblöcke (z. B. Antragsteller:in, Hund) in der zentralen Bibliothek anlegen, ändern, kopieren und löschen. Änderungen wirken in allen Formularen, die den Block verwenden |
| **Online-Anträge einrichten** | Ein Formular zum Online-Antrag machen oder zurückstellen (Schalter im Reiter „Antrag“). Die übrigen Antragseinstellungen darf ändern, wer das Formular bearbeiten darf. *Bei der Aktualisierung bekommen alle, die bisher „Formulare“ hatten, dieses Recht einmalig dazu* |
| **Terminbuchung** | Buchungsseiten anlegen, in denen andere selbst freie Zeitfenster buchen (z. B. Vorstellungsgespräche). Online-Termine mit eigener Videokonferenz brauchen zusätzlich „Videokonferenzen“ |
| **Terminumfragen** | Terminumfragen wie Doodle anlegen, verteilen und auswerten. Aus dem festgelegten Termin eine Besprechung anlegen geht nur mit zusätzlichem Recht „Videokonferenzen“ |
| **Abstimmungen** | Abstimmungen und Wahlen anlegen (offen, geheim, anonym), Wahlberechtigte einladen, Zugangscodes drucken, Live-Modus, auswerten |
| **Ressourcen** | Ressourcen (Bürgerhäuser, Räume, Grillplätze, Geräte) anlegen, Feiertage pflegen. Verwalten dürfen außerdem die bei der Ressource eingetragenen Zuständigen und Freigaben ab Stufe „Verwalten“ |
| **Zahlungen** | Zahlungsübersicht und CSV-Export, Zahlungen als bezahlt markieren, erstatten, stornieren – für alle Vorgänge. Im eigenen Vorgang (Buchung, Antrag) dürfen das auch die Zuständigen. PayPal und Bankverbindung richten nur Admins ein |
| **Prozesse** | Bearbeitungsprozesse für Online-Anträge im Prozesseditor anlegen, ändern, veröffentlichen, exportieren und Vorlagen für Nachforderungen pflegen. Arbeitsschritte erledigen kann jede:r, dem ein Schritt zugewiesen ist – dafür braucht es kein Recht |
| **Aktenplan verwalten** | Ablagebereiche (DMS) anlegen, Lese-/Schreibrechte und Löschfristen festlegen, abgelaufene Vorgänge löschen. Wer was in der Ablage **sieht**, steuern die Rechte am Bereich, nicht dieses Recht |
| **Kartenlayer & Geocoding** | Verwaltung › Kartenlayer: Layer, Startausschnitt, Zwischenspeicher, Einbetten und die Adresssuche (Nominatim) einrichten – ohne Admin zu sein |
| **Karten** | Im Kartenbrowser eigene WMS/WFS/WMTS-Dienste hinzufügen, Karten speichern und per Link oder iframe teilen. Ansehen kann den Kartenbrowser jede:r, auch ohne Anmeldung |
| **Rechtstexte** | Gesetze, Satzungen und Verordnungen einstellen, ändern, veröffentlichen und den Rechtsbaum (Ebenen) pflegen. Lesen kann jede:r ohne Anmeldung unter `/recht` |
| **Krankmeldungen** | Krankmeldungen der Arbeitgeber bearbeiten, für die die Person oder ihre Gruppe zuständig ist (siehe [Krankmelder](#blueotter-krankmelder)) |
| **Krankmelder verwalten** | Alle Krankmeldungen; Arbeitgeber, Zuständige, Zugang, Texte, Löschfrist, Import, Zugriffsprotokoll |
| **Benutzerverwaltung** | Benutzer und Gruppen anlegen, bearbeiten, sperren, löschen – aber keine Admin-Konten ändern und niemanden zum Admin machen |
| **Administrator:in** | Alles, auch Systemeinstellungen (Mail, HTTPS, Design, SpeechMind, Module, Zwei-Faktor) und alle Aufnahmen, Kurzlinks und Formulare |

**Geteilte Inhalte:** Formulare, Terminumfragen und Buchungsseiten können ihre Besitzer:innen im Portal mit Personen oder Gruppen teilen – in drei Stufen (1 Ergebnisse einsehen, 2 zusätzlich einladen, 3 zusätzlich bearbeiten und löschen). Wer etwas geteilt bekommt, sieht es unter „Mit mir geteilt“ auch **ohne** das jeweilige Recht; Neues anlegen kann nur, wer das Recht hat. Freigaben verwalten nur Besitzer:in und Admins.

Ohne Recht „Videokonferenzen“ kommt eine angemeldete Person in Portal-Räume nur wie ein Gast (per Link) und kann nicht aufnehmen. Ist ein Modul abgeschaltet (siehe [Module](#module-ein--und-ausschalten)), verschwindet das Recht aus der Auswahl.

### Neue Personen einladen

1. Im Feld „E-Mail-Adressen“ eine oder **mehrere** Adressen eintippen oder aus einer Liste einfügen. Enter, Komma oder Leerzeichen macht aus jeder Adresse ein Etikett; ungültige werden nicht übernommen. Den Namen leitet das Portal aus der Adresse ab (`max.muster@…` → „Max Muster“). Bei nur einer Adresse können Sie ihn selbst vorgeben.
2. **Gruppen** wählen (optional).
3. **Rechte** setzen (voreingestellt: Videokonferenzen). „Administrator:in“ sehen nur Admins.
4. **Einladen**.

Die Person bekommt eine E-Mail mit einem Link (72 Stunden gültig, einmal benutzbar) und legt ihr Passwort selbst fest. **Ist kein E-Mail-Versand eingerichtet**, zeigt das Portal den Link **einmalig** oben auf der Seite; geben Sie ihn persönlich weiter.

### Viele Personen per CSV importieren

Kasten **Benutzer aus CSV importieren**:

1. **CSV-Vorlage herunterladen** und in Excel (oder LibreOffice) ausfüllen. Eine Zeile pro Person:

   | Spalte | Inhalt | Beispiel |
   |---|---|---|
   | `email` | **Pflicht**, wird der Benutzername | `erika.mustermann@example.org` |
   | `name` | Anzeigename; leer = aus der Adresse abgeleitet | `Erika Mustermann` |
   | `password` | Startpasswort (mind. 10 Zeichen); **leer = ohne Passwort**, Einladung per Mail möglich | `Startpasswort-2026` |
   | `groups` | Gruppen, mehrere mit `;` getrennt. Fehlende Gruppen werden angelegt | `Bauamt;Kita` |
   | `permissions` | `video`, `shortlinks`, `forms`, `polls`, `bookings`, `users`, mehrere mit `;`; leer = `video` | `video;forms` |
   | `admin` | `yes`/`no` – wird nur beachtet, wenn ein Admin importiert | `no` |

   Die Vorlage beginnt mit der Zeile `sep=,`, damit Excel die Spalten auch bei deutscher Einstellung richtig trennt; der Import überspringt sie. Speichert Excel die Datei mit Semikolon als Trennzeichen (Standard in Deutschland), trennen Sie mehrere Gruppen bzw. Rechte mit `|` statt `;`. Umlaute sind in UTF-8 und in der Excel-Kodierung (Windows-1252) möglich. Deutsche Spaltennamen (`E-Mail`, `Passwort`, `Gruppen`, `Rechte`) werden ebenfalls erkannt.
2. Datei wählen, **Prüfen**. Das Portal zeigt eine **Vorschau** und ändert noch nichts: neue Konten, bestehende Konten (bei denen nur Gruppen ergänzt werden), übersprungene und fehlerhafte Zeilen mit Grund (ungültige Adresse, doppelte Adresse, zu kurzes Passwort, unbekanntes Recht) und neu entstehende Gruppen.
3. Optionen wählen:
   - **Neue Konten ohne Passwort per E-Mail einladen** (voreingestellt): Die Personen bekommen den üblichen Einladungslink. Ohne Mailversand zeigt das Portal die Links danach einmalig an. Ohne Einladung können Sie später einzeln über das Papierflieger-Symbol einladen.
   - **Passwortwechsel bei der ersten Anmeldung verlangen** für Konten mit Startpasswort (empfohlen).
4. **Import ausführen**. Fehlerhafte Zeilen werden übersprungen; korrigieren Sie sie in der Datei und importieren Sie erneut – schon angelegte Konten werden dann nur noch um Gruppen ergänzt.

**Bestehende Konten** werden nicht überschrieben (Name, Passwort und Rechte bleiben); sie werden nur in die genannten Gruppen aufgenommen. Personen mit dem Recht „Benutzerverwaltung“ können importieren, aber keine Admins anlegen und keine Admin-Konten ändern. Die Vorschau samt Startpasswörtern liegt bis zum Ausführen kurz auf dem Server (`data/portal/imports/`, nur für das Portal lesbar) und wird spätestens nach einer Stunde gelöscht.

### Aktionen pro Person

Symbole rechts in der Zeile (Maus darüber zeigt den Namen):

| Aktion | Wirkung |
|---|---|
| Stift **Bearbeiten** | Name, Gruppen und Rechte ändern |
| Einladung erneut senden / Passwort-Link senden | Neuer Link, der alte wird ungültig |
| Schild **Zwei-Faktor zurücksetzen** | App, Mail-Code und Notfallcodes entfernen, z. B. bei verlorenem Telefon (erscheint nur, wenn etwas eingerichtet ist) |
| Zum Admin machen / Admin-Recht entziehen | nur für Admins |
| Sperren / Entsperren | Anmeldung nicht mehr möglich / wieder möglich; Daten bleiben |
| Löschen | Konto und dessen Meetings weg. Aufnahmen bleiben für Admins sichtbar; Kurzlinks und Formulare der Person bleiben erhalten und sind danach nur noch für Admins sichtbar |

Das eigene Konto lässt sich nicht sperren, löschen oder vom Admin-Recht befreien (Schutz vor Aussperren). In der Spalte Status zeigt ein grünes Schild, wer Zwei-Faktor eingerichtet hat.

### Gruppen

Kasten **Gruppen** unten: **Neue Gruppe**, Name, Beschreibung und Mitglieder wählen. Gruppen werden genutzt, um

- viele Personen auf einmal zu einem **Formular einzuladen** (alle aktuellen Mitglieder bekommen eine persönliche Einladung),
- **Formulare im Portal freizugeben** (gilt für alle, die gerade Mitglied sind).

Eine Person kann in mehreren Gruppen sein. Gruppen gibt es auch im Bearbeiten-Dialog der Person. Das Löschen einer Gruppe löscht keine Konten.

### Passwort vergessen

Benutzer:innen klicken auf der Anmeldeseite „Passwort vergessen?“. Der Link ist 2 Stunden gültig. Das Portal antwortet immer gleich, auch wenn die Adresse unbekannt ist (sonst ließe sich ausprobieren, wer ein Konto hat). Ist Zwei-Faktor aktiv, wird nach dem neuen Passwort trotzdem der zweite Faktor abgefragt.

**Das Standard-Admin-Konto** wird beim allerersten Start angelegt. Legen Sie danach ein persönliches Admin-Konto für jede zuständige Person an und sperren Sie das Standardkonto oder behalten Sie es mit sicherem Passwort und Zwei-Faktor.

## Körperschaften und Einrichtungen

Menü **Verwaltung › Körperschaften** (Admins und Recht „Körperschaften (Stammdaten)“). Hier werden die Gebietskörperschaften und Zweckverbände, die das Portal betreut, **einmal zentral** gepflegt – mit Art (Verbandsgemeinde, Ortsgemeinde, Stadt, Landkreis, Zweckverband), Kurzname, Gemeindeschlüssel, Farbe, **Wappen** (PNG/JPEG/WebP), Anschrift und Kontakt. Darunter hängen beliebig viele **Einrichtungen** (Abteilungen, Kitas, Schulen, Eigenbetriebe …); Ortsgemeinden und Städte stehen unter der Verbandsgemeinde.

Genutzt wird die Liste in allen Modulen:

| Modul | Verwendung |
|---|---|
| Ressourcen | **Anbieter** einer Ressource (Reiter Allgemein) – Wappen und Kontakt auf der öffentlichen Seite, Filter im Katalog |
| Krankmelder | Jeder **Arbeitgeber** ist einer Körperschaft oder Einrichtung zugeordnet; das Meldeformular gruppiert die Auswahl nach Körperschaft, Kitas und Abteilungen sind einzeln wählbar |
| Rechtstexte | Jede **Ebene** im Rechtsbaum kann auf ihre Körperschaft zeigen – das Wappen erscheint im Ortsrecht |
| Anträge | **Zuständige Stelle** je Online-Antrag – mit Wappen im Antragskatalog, dort auch als Filter |

Beim ersten Start nach dem Update legt das Portal die Verbandsgemeinde und die Ortsgemeinden aus dem Rechtsbaum an und übernimmt die bisherigen Arbeitgeber des Krankmelders als Einrichtungen (gleichnamige werden verknüpft). Danach bitte unter Verwaltung › Körperschaften die Einrichtungen ihrer Körperschaft zuordnen. Einträge, die noch verwendet werden, lassen sich nicht löschen – stattdessen auf **inaktiv** setzen.

## Anmeldung und Zwei-Faktor

Kasten **Anmeldung & Zwei-Faktor** unter **Benutzer & Gruppen** (nur Admins).

| Einstellung | Bedeutung |
|---|---|
| **Authenticator-App (TOTP)** | Erlaubt Apps wie Microsoft/Google Authenticator, FreeOTP oder Passwortverwaltungen (Standard RFC 6238, 6 Ziffern, 30 Sekunden) |
| **Code per E-Mail** | Erlaubt sechsstellige Codes per Mail (10 Minuten gültig). Braucht eingerichteten Mailversand |
| **Zwei-Faktor ist …** | **Freiwillig:** jede Person schaltet es unter Profil › Sicherheit selbst ein. **Pflicht für Administrator:innen** oder **Pflicht für alle** |

**So wirkt die Pflicht:** Hat eine Person keine App eingerichtet, verlangt das Portal automatisch einen Code per E-Mail. Ist der nicht erlaubt, muss sie die App direkt nach der Anmeldung einrichten; vorher sind keine anderen Seiten erreichbar.

**Wiederherstellungscodes:** Beim Einrichten bekommt jede Person zehn Notfallcodes. Hat jemand Telefon und Codes verloren: in der Benutzerliste **Zwei-Faktor zurücksetzen**. Bei Pflicht greift danach der Mail-Code bzw. die Neueinrichtung.

**Empfehlung:** Mindestens „Pflicht für Administrator:innen“ mit erlaubter App. Admin-Konten haben Zugriff auf alle Aufnahmen und Formulardaten.

Weitere Schutzmechanismen, die immer aktiv sind:

- Passwörter als Argon2-Hash; die Anmeldung antwortet für bekannte und unbekannte Adressen gleich schnell (verrät nicht, welche Konten existieren).
- Bremse gegen Passwort-Raten: je IP-Adresse 10 Versuche in 10 Minuten **und je Konto 20 Versuche in 30 Minuten** (auch wenn die Versuche von vielen Adressen kommen), danach „Zu viele Versuche“.
- Höchstens fünf falsche Codes je Anmeldung und zehn je Konto in 15 Minuten (auf dem Server gezählt, auch über neue Anmeldungen hinweg); danach verfällt auch ein per Mail geschickter Code. Jeder App-Code ist nur einmal gültig. Ein neues Gerät ersetzt das bisherige nur nach Eingabe des Passworts.
- Alle Formulare mit CSRF-Schutz; Weiterleitungen nach der Anmeldung nur auf Seiten dieses Servers.
- Die IP-Adresse für die Bremsen liefert Caddy; ein mitgeschickter `X-Forwarded-For`-Kopf wird nicht ausgewertet. IPv6-Anschlüsse zählen je /64-Netz.
- **Benutzer verwalten** (ohne Admin-Rolle) darf nur Rechte vergeben oder entziehen, die man selbst hat, und keine Konten ändern oder zurücksetzen, die mehr Rechte haben.
- In Konferenzen von Portal-Räumen **moderieren nur Gastgeber:in und Admins**; andere Angemeldete nehmen ohne Moderationsrechte (und ohne Aufnahme) teil.
- **Sicherheits-Header** auf allen Seiten: Content-Security-Policy (nur eigene Skripte – Inline-Skripte nur mit einer für jede Antwort neuen Nonce, eingeschleuste Skripte und Handler werden blockiert –, Bilder und Verbindungen; keine fremden Server, keine `<object>`/`<base>`-Tricks, Formulare nur an Portal und Konferenzserver), `X-Frame-Options: DENY` (Ausnahme: `/recht-embed`), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy` (kein Zugriff auf Kamera, Mikrofon oder Standort für das Portal – die Konferenz läuft auf der eigenen Konferenz-Domain), `Cross-Origin-Opener-Policy`. Seiten angemeldeter Personen sowie Verwaltungs- und Anmeldeseiten werden nicht im Browser-Cache abgelegt. Mit Let's-Encrypt-Zertifikat sendet Caddy auf allen Domains HSTS.
- CSV-Exporte entschärfen Zellen, die mit `=`, `+`, `-` oder `@` beginnen (keine Formeln aus Eingaben in Excel). Eingangsbestätigungen gehen höchstens fünfmal je Stunde an dieselbe Adresse. Eigene Prüfmuster in Formularen laufen mit Zeitlimit. Kartenebenen ohne Proxy-Server können keine internen Adressen abfragen (auch nicht über DNS-Tricks).
- Hochgeladene Dateien aus Formularen werden immer als Download ausgeliefert, nie als Webseite; unbekannte Dateitypen als `application/octet-stream`.

## Module ein- und ausschalten

Menü **Module** (nur Admins). **Kurzlinks & QR-Codes**, **Formulare**, **Online-Anträge** (nur zusammen mit Formularen), **Ablage (DMS)**, **Umfragen & Abstimmungen**, **Terminbuchung**, **Ressourcenbuchung**, **Kartenbrowser** und **Rechtstexte** lassen sich komplett abschalten. Videokonferenzen sind die Kernfunktion und immer aktiv.

Ein abgeschaltetes Modul

- verschwindet aus dem Menü, der Rechteauswahl und den Startseiten,
- ist **vollständig unerreichbar** – auch über bereits verteilte Links (Kurzlinks leiten nicht mehr weiter, öffentliche und persönliche Formular-Links zeigen „nicht verfügbar“),
- behält alle Daten. Nach dem Wiedereinschalten ist alles wieder da.

Die Umschaltung wirkt nach wenigen Sekunden, ohne Neustart.

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

### Chatprotokoll

Was während einer Aufnahme im Konferenz-Chat geschrieben wurde (Gruppenchat, keine privaten Nachrichten), hängt das Portal als **Chatprotokoll** an die Aufnahme: mit Uhrzeit und Namen, lesbar in der Aufnahme und als TXT herunterladbar. In der Aufnahmenliste zeigt ein Sprechblasen-Symbol mit Zahl, wie viele Nachrichten es sind.

- Mitgeschrieben wird nur in **Portal-Räumen**. Den Chat von freien Räumen speichert das Portal nie.
- Chatnachrichten ohne Aufnahme werden nach **48 Stunden** automatisch gelöscht. Dauerhaft bleibt nur, was zu einer Aufnahme gehört.
- Beim Löschen „Nur Video und MP3“ bleibt das Chatprotokoll erhalten. Die beiden anderen Löschoptionen entfernen es.
- Weisen Sie die Teilnehmenden darauf hin, dass der Chat zusammen mit der Aufnahme gespeichert wird.

### Umfragen

Umfragen, die während einer Aufnahme in der Konferenz gestellt oder beantwortet werden („…“ › Umfragen), hängt das Portal ebenfalls an die Aufnahme: **Frage, Antwortmöglichkeiten, Anzahl der Stimmen mit Prozent und die Namen der Abstimmenden**. Ändert jemand seine Stimme, zählt die letzte bis zum Ende der Aufnahme. Eine Umfrage, die vor der Aufnahme gestellt, aber währenddessen beantwortet wurde, gehört ebenfalls dazu. In der Aufnahmenliste zeigt ein Umfrage-Symbol mit Zahl, wie viele es sind; der TXT-Download „Chatprotokoll & Umfragen“ enthält beides.

Es gelten dieselben Regeln wie beim Chat: nur Portal-Räume, Rohdaten ohne Aufnahme nach 48 Stunden gelöscht, „Nur Video und MP3 löschen“ behält die Umfragen.

*Technisch:* Das Prosody-Modul `mod_portal_access_muc` schreibt neue Umfragen und Stimmen (Jitsi-Nachrichten `new-poll` und `answer-poll`) neben den Chat in `data/portal-chat/`. Nach dem Update auf diese Version einmal `docker compose restart prosody` ausführen, damit das Modul neu geladen wird.

### Aufnahmen löschen

Löschen geht an drei Stellen: über das Papierkorb-Symbol in jeder Tabellenzeile, über **Löschen** in der Aufnahme selbst und für viele Aufnahmen auf einmal (Kästchen links anhaken, das Kästchen in der Kopfzeile wählt alle gefilterten aus, dann **Ausgewählte löschen**).

Ein Dialog fragt, was gelöscht werden soll. Angeboten wird nur, was bei der Aufnahme sinnvoll ist:

| Auswahl | Was passiert | Danach |
|---|---|---|
| **Nur Video und MP3 löschen, Transkript und Chatprotokoll behalten** | Mediendateien weg, Protokoll, Wortlaut und Chatprotokoll bleiben im Portal | Etikett „Medien gelöscht“, Transkript weiter lesbar und als TXT ladbar |
| **Alles hier löschen, bei SpeechMind abrufbar** | Mediendateien und Transkript weg, der Verweis auf das Protokoll bei SpeechMind bleibt | Status „Bei SpeechMind abrufbar“, Knopf **Protokoll von SpeechMind abrufen** holt es jederzeit zurück |
| **Alles löschen** | Eintrag samt Video, MP3 und Transkript weg | Nicht wiederherstellbar. Das Protokoll in SpeechMind selbst bleibt dort bestehen |

Bei der Mehrfachauswahl gilt die gewählte Option für jede Aufnahme, soweit möglich. Was danach nichts mehr enthält (z. B. eine nie transkribierte Aufnahme bei „Nur Video und MP3 löschen“), wird ganz entfernt. Aufnahmen, die gerade verarbeitet werden, werden übersprungen.

**Neu von SpeechMind laden:** Bei transkribierten Aufnahmen holt dieser Knopf Protokoll und Wortlaut erneut ab, z. B. nachdem Sie das Protokoll in SpeechMind überarbeitet haben. Wurde das Protokoll in SpeechMind gelöscht, scheitert der Abruf mit einer Meldung.

## Besprechungen planen

Menü **Besprechung planen** (für alle angemeldeten Benutzer:innen).

1. **Titel**, **Beginn**, **Dauer** und optional eine **Tagesordnung** eintragen.
2. **Teilnehmende:** Namen oder Adresse eintippen. Portal-Benutzer werden vorgeschlagen; externe Gäste trägt man einfach mit E-Mail-Adresse ein (Enter, Komma oder Leerzeichen trennt). Externe brauchen kein Konto.
3. **Kopie an mich** (empfohlen): Sie erhalten den Termin selbst als Kalendereintrag.
4. **Planen und einladen**.

Das Portal legt einen Konferenzraum an und schickt **jeder Person eine eigene Mail**. Sie enthält einen **persönlichen Einwahllink** (Zutritt ohne Konto, aber ohne Aufnahmerecht; siehe [Räume und Zugang](#räume-und-zugang)) und den Termin als **Outlook-Besprechungsanfrage** (Annehmen/Ablehnen direkt in Outlook) plus Datei `einladung.ics` für alle anderen Kalender (Thunderbird, Apple, Google). Die Empfänger sehen die anderen Adressen nicht. Zu-/Absagen aus Outlook gehen an die planende Person.

**Auf der Seite des Meetings** (Bereich „Termin & Einladungen“):

| Aktion | Wirkung |
|---|---|
| **Termin ändern** | Neue Zeit, Dauer oder Tagesordnung. Ist „Eingeladene informieren“ an, bekommen alle einen aktualisierten Kalendereintrag, der den alten ersetzt |
| **Weitere Personen einladen** | Nur die neuen Personen bekommen eine Einladung |
| Symbol **Ausladen** | Die Person bekommt eine Absage, der Termin verschwindet aus ihrem Kalender |
| **Einladung erneut senden** | Schickt allen die aktuelle Einladung noch einmal (z. B. wenn jemand sie gelöscht hat) |
| **Absagen** | Alle bekommen eine Absage (optional mit einer Nachricht von Ihnen); der Raum bleibt bestehen |
| **Meeting löschen** (ganz unten) | Steht der Termin noch bevor, schlägt der Dialog vor, allen Eingeladenen (außer denen, die schon abgesagt haben) eine Absage zu schicken – voreingestellt, optional mit Nachricht. Der Termin verschwindet dann aus ihren Kalendern |
| **ICS herunterladen** | Termin als Datei, z. B. zum Weiterleiten aus dem eigenen Mailprogramm |

### Zu- und Absagen verfolgen

**Zwei Wege zu antworten:**

1. **Im Kalenderprogramm** (Outlook, Thunderbird, Apple, Google): Die Einladung erscheint als Besprechungsanfrage mit „Annehmen/Ablehnen“. Ausgewertet wird das per IMAP (siehe unten).
2. **Per Link in der Mail** („Zu- oder absagen: …“): Er öffnet eine Seite mit **Zusagen / Mit Vorbehalt / Absagen** und optionalem Kommentar. Das funktioniert in jedem Mailprogramm und auch ohne IMAP-Auswertung. Die Antwort wird erst mit dem Knopf gespeichert (automatische Link-Prüfungen von Mailservern lösen also nichts aus). Auf derselben Seite gibt es den Termin als `.ics` für den eigenen Kalender.

Haben Sie die Vorlagen „Einladung zur Besprechung“ oder „Geänderte Besprechung“ früher angepasst, fügen Sie dort den Platzhalter `{antwort_link}` ein; neue Standardtexte enthalten ihn bereits.

Bei jeder Person steht in der Spalte **Antwort**, ob sie **zugesagt**, **abgesagt**, **mit Vorbehalt** geantwortet oder einen **neuen Zeitvorschlag** gemacht hat, mit Zeitpunkt und Kommentar. Darüber steht die Zusammenfassung („3 zugesagt, 1 abgesagt, 2 offen“), ebenso auf der Startseite. Die planende Person bekommt zu jeder Antwort eine Mail (abschaltbar).

Voraussetzung: Unter **Benachrichtigungen** ist IMAP eingerichtet und **„Antworten im Postfach auswerten“** eingeschaltet (siehe [E-Mail einrichten](#e-mail-einrichten)). So funktioniert es:

- In neuen Einladungen steht die **Absenderadresse des Portals** als Organisator (angezeigt mit dem Namen der planenden Person). Klickt jemand in Outlook auf „Annehmen“, geht die Antwort an dieses Postfach.
- Das Portal sieht alle zwei Minuten nach, liest nur neue Nachrichten und verbucht die Antworten. Erkannte Antworten werden als gelesen markiert und auf Wunsch in einen Ordner verschoben. Alle anderen Mails bleiben unberührt.
- Wird der Termin geändert, gelten frühere Antworten nicht mehr (wie in Outlook); die Spalte steht wieder auf „Offen“, bis neu geantwortet wird.
- Antwortet jemand, an den die Einladung weitergeleitet wurde, erscheint er mit seiner Antwort in der Liste.
- Wer in Outlook „Antwort nicht senden“ wählt, bleibt auf „Offen“.
- Erkannt werden Antworten mit Kalenderdaten (Standard), Outlook-Antworten im Exchange-Format (`winmail.dat`) und notfalls Antworten, die nur am Betreff zu erkennen sind („Zugesagt: …“, „Abgelehnt: …“, „Mit Vorbehalt: …“, „Accepted: …“). Diese werden über die Absenderadresse und den Besprechungstitel im Betreff zugeordnet.
- Einladungen, die **vor** dem Einschalten verschickt wurden, schicken ihre Antworten weiterhin direkt an die planende Person; dafür ggf. „Einladung erneut senden“.

Auch für einen bestehenden Raum lässt sich nachträglich ein Termin festlegen. Wird ein Meeting mit anstehendem Termin gelöscht, erhalten die Eingeladenen automatisch eine Absage. Anstehende Besprechungen stehen auf der Startseite unter **Meetings**.

**Ohne eingerichteten E-Mail-Versand** wird die Besprechung trotzdem angelegt, es gehen aber keine Mails raus. Laden Sie dann die ICS-Datei herunter und versenden Sie sie selbst.

## Kurzlinks und QR-Codes

Menü **Kurzlinks** (Recht „Kurzlinks“). Funktionsumfang ähnlich wie Shlink: eigenes oder zufälliges Kürzel, Titel und Schlagwörter, Gültigkeitszeitraum, maximale Anzahl Aufrufe, Weitergabe von Parametern, Art der Weiterleitung (301/302/307/308), Aktivieren/Deaktivieren, Statistik und QR-Codes. Die Bedienung steht im [Benutzerhandbuch](BENUTZERHANDBUCH.md#7-kurzlinks-und-qr-codes).

**Wer sieht was:** Jede Person sieht ihre eigenen Kurzlinks, Admins über **Alle anzeigen** alle (mit Spalte „Von“). Kürzel sind portalweit eindeutig und unabhängig von Groß-/Kleinschreibung.

### Einstellungen (nur Admins)

Unten auf der Kurzlink-Seite, Kasten **Einstellungen**:

| Einstellung | Bedeutung |
|---|---|
| **Eigene Kurz-Domain** | Leer: Kurzlinks laufen über `https://<Portal-Domain>/s/<kürzel>`. Mit eigener Domain werden sie kürzer: `https://kurz.example.de/<kürzel>`. Das Portal trägt die Domain selbst in den Proxy ein; das Zertifikat kommt wie bei den anderen Domains (selbst signiert oder Let's Encrypt) |
| **Ziel für unbekannte oder abgelaufene Kurzlinks** | Statt der Hinweisseite dorthin weiterleiten, z. B. zur Homepage. Gilt auch für die Startseite der Kurz-Domain |
| **Länge zufälliger Kürzel** | 4–20 Zeichen (Standard 6). Zufällige Kürzel verwenden keine leicht verwechselbaren Zeichen (l, 1, o, 0, i) |

**Kurz-Domain einrichten:** DNS-Eintrag (A/AAAA) der neuen Domain auf den Server setzen, Domain eintragen, speichern. Bei Let's Encrypt muss Port 80/443 auch für diese Domain erreichbar sein. Die Domain darf nicht gleich der Konferenz- oder Portal-Domain sein.

### Statistik und Datenschutz

- Gespeichert wird je Aufruf: Zeitpunkt, Browser, Betriebssystem, Gerätetyp (Desktop/Mobil/Tablet) und **nur der Hostname** der verweisenden Seite. **Keine IP-Adressen**, keine Cookies.
- Aufrufe durch Bots, Vorschaudienste und Link-Prüfer von Mailservern (z. B. Microsoft Safe Links) werden erkannt und getrennt gezählt; sie zählen nicht gegen „Max. Aufrufe“.
- Die Aufrufliste gibt es je Link als CSV. „Statistik zurücksetzen“ löscht alle Aufrufe eines Links.

### QR-Generator

Für jeden Kurzlink und frei für beliebige Inhalte (**QR-Generator**). Ausgabe mit Vorschau und Download als **SVG, PNG oder JPG**; Größe, Rand, Farben und Fehlerkorrektur (L/M/Q/H) einstellbar. Erzeugt wird alles auf dem eigenen Server (Bibliotheken Segno und Pillow).

## Formulare

Menü **Formulare** (Recht „Formulare“). Ein Formularserver mit Baukasten, vergleichbar mit Nextcloud Forms. Die Bedienung steht ausführlich im [Benutzerhandbuch](BENUTZERHANDBUCH.md#8-formulare-erstellen); hier das, was für die Betreuung wichtig ist.

**Funktionsumfang**

- Fragetypen: kurze Antwort (Text, E-Mail, Telefon, Zahl, eigenes Muster), langer Text, Einfach- und Mehrfachauswahl (mit „Sonstiges“, Mindest-/Höchstzahl, zufälliger Reihenfolge), Auswahlliste, Datum, Uhrzeit, Datum mit Uhrzeit, lineare Skala, Farbe, Datei-Upload (Endungen, Größe bis 20 MB, bis 10 Dateien), **Ort in der Karte** (Karte mit den unter Kartenlayer für Formulare freigegebenen Grundkarten): je Frage einstellbar, ob **Punkte, Linien und/oder Flächen** eingezeichnet werden dürfen und wie viele Objekte höchstens; Punkte per Klick, GPS oder Breite/Länge, Linien/Flächen gezeichnet (Eckpunkte verschiebbar, GPS-Standort als Eckpunkt). Optional wird **zusätzlich der eigene Standort** der ausfüllenden Person erfasst (GPS mit Genauigkeit und Zeitpunkt, unabhängig vom Eingezeichneten, wahlweise Pflicht). Gespeichert als WGS84 bzw. GeoJSON-Geometrie mit Länge und Fläche, höchstens 1000 Punkte je Objekt).
- Gliederung: Überschrift, Zwischenüberschrift, Hinweistext, Trennlinie, **Neue Seite** (mehrseitige Formulare mit Schrittanzeige und Prüfung je Seite).
- **Adresse:** Straße, Hausnummer, PLZ, Ort, optional Ortsteil und Koordinaten. Je Feld einstellbar: vollständige Anschrift oder nur **PLZ + Ort** (Ort wird aus der PLZ ermittelt), **Adresssuche** (Vorschläge beim Tippen) und **Standort als Adresse übernehmen**. Suche und PLZ-Abfrage laufen über das Portal zu Nominatim (siehe [Adresssuche](#adresssuche-nominatim)); die Felder bleiben immer von Hand ausfüllbar.
- **Bedingungen:** Jedes Feld kann nur unter Bedingungen **angezeigt** und/oder nur unter Bedingungen **Pflicht** sein – mehrere Regeln, verknüpft mit „alle“ (UND) oder „eine“ (ODER). Ausgeblendete Felder werden nicht gespeichert; der Server prüft dieselben Regeln.
- **Datenblöcke:** Unter **Formulare › Datenblöcke** liegt die zentrale Bibliothek (Startvorlagen: Antragsteller:in, Firma, Adresse, Bankverbindung, Hund, Fahrzeug). Im Baukasten werden Blöcke **verknüpft** eingefügt: Eine Änderung am Block gilt sofort in allen Formularen; die Felder des Blocks lassen sich in Bedingungen verwenden. Gelöscht werden kann ein Block erst, wenn ihn kein Formular mehr verwendet; „Kopieren“ erzeugt einen unabhängigen Block. Antworten speichern die Feldwerte – bestehende Antworten bleiben auch bei späteren Blockänderungen lesbar.
- Darstellung: Feldbreite je Feld (ganz, zwei Drittel, halb, Drittel; auf dem Handy immer ganz), **Zusammenfassung vor dem Absenden** (Reiter Einstellungen, ab drei Fragen), automatischer **Entwurf** im Browser der ausfüllenden Person (nur lokal, Dateien ausgenommen). Datum wahlweise **mit Uhrzeit**.
- Verteilung: öffentlicher Link (mit QR-Code und Kurzlink), persönliche Einladungen an Benutzer, **Gruppen** und Gäste per E-Mail, Erinnerungen, Frist, anonyme Formulare, Mehrfachantworten.
- Auswertung: Zusammenfassung mit Diagrammen, Einzelansicht, Export **CSV** (Semikolon, UTF-8 mit BOM – öffnet sich in Excel korrekt) und **JSON**.
- Benachrichtigung bei neuen Antworten an die Besitzerin und weitere Adressen, wahlweise mit Antworten im Text und **CSV- und/oder JSON-Anhang** – nur die neue Antwort oder jeweils alle.
- Eingangsbestätigung mit Kopie der Antworten an die ausfüllende Person.
- **Freigabe im Portal** an Personen oder Gruppen in drei Stufen: 1 Ergebnisse einsehen, 2 zusätzlich einladen, 3 zusätzlich bearbeiten und löschen. Freigaben verwaltet die Besitzerin bzw. ein Admin.

**Wer sieht was:** Besitzer:innen ihre Formulare, Admins alle (**Alle Formulare**), Kolleg:innen mit Freigabe die freigegebenen. Gehört ein Formular einer gelöschten Person, sehen es nur noch Admins.

**Schutz vor Missbrauch öffentlicher Formulare:** unsichtbares Spam-Feld (Honigtopf), Begrenzung auf 30 Absendungen je Adresse in 10 Minuten, Prüfung aller Eingaben auf dem Server (Pflichtfelder, Formate, erlaubte Optionen, Dateityp und -größe).

**Speicherort:** Antworten in der Datenbank (`data/portal/portal.db`), hochgeladene Dateien unter `data/portal/forms/<formular>/<antwort>/`. Beim Löschen einer Antwort oder eines Formulars werden die Dateien mitgelöscht. Uploads sind durch den Proxy auf 60 MB je Absendung begrenzt.

**Mail-Vorlagen:** „Einladung zum Ausfüllen“, „Erinnerung zum Ausfüllen“, „Neue Antwort“ und „Eingangsbestätigung“ (Gruppe „Formulare“ unter E-Mail-Vorlagen).

## Online-Anträge

Modul **Online-Anträge** (Verwaltung › Module, setzt „Formulare“ voraus). Ein Online-Antrag ist ein Formular mit Vorgangsbearbeitung. Anlegen: unter **Formulare** beim Anlegen „Online-Antrag“ wählen oder bei einem bestehenden Formular den Reiter **Antrag** öffnen und „Als Online-Antrag verwenden“ einschalten (Recht „Online-Anträge einrichten“).

**Einstellungen im Reiter „Antrag“**

| Einstellung | Bedeutung |
|---|---|
| Kürzel | Präfix des Aktenzeichens, z. B. `GEW` → `GEW-2026-00001`. Der Zähler beginnt jedes Jahr neu. Ohne Kürzel: `A<Formularnummer>` |
| Bearbeitungsfrist | Tage ab Eingang; bei Überschreitung bekommen die Zuständigen einmal eine Erinnerung (Prüfung alle 5 Minuten) |
| PDF anhängen | Antrag als PDF (A4, mit Prüfsumme) an Eingangsbestätigung und Hinweis an die Zuständigen bzw. das Funktionspostfach. Hochgeladene **PDFs und Bilder** (JPG, PNG, GIF, WebP) werden angehängt – mit Anlagenverzeichnis, Seitenzahlen und Fußzeile „Anlage n zu …“. Verschlüsselte oder beschädigte PDFs und andere Dateitypen stehen nur im Verzeichnis. Wird das PDF größer als 15 MB, geht die Mail ohne Anhang raus (der Link zur Statusseite bleibt) |
| Ablagebereich | Bereich im Aktenplan, in dem die Anträge dieses Formulars abgelegt werden, wenn der Prozess keinen festlegt (siehe [Ablage](#ablage-dms)) |
| Zuständig | Vorgabe: Person, Gruppe (alle Mitglieder) und/oder Funktionspostfach (z. B. für die E-Akte) |
| Weiterleitung | Regeln: Antwort auf Frage X lautet Y → Person/Gruppe/Postfach. Die erste passende Regel gilt, sonst die Vorgabe |
| Antragskatalog | Eintrag im öffentlichen Katalog `/antraege` mit Kategorie, Gebühr, Bearbeitungsdauer und Hinweisen (Unterlagen, Rechtsgrundlage). Einschalten erzeugt automatisch den öffentlichen Link |

Ein Antrag braucht eine Frage vom Typ **E-Mail-Adresse** (Pflicht), sonst gibt es weder Eingangsbestätigung noch Statusmails – der Reiter weist darauf hin.

**Ablauf.** Beim Absenden: Aktenzeichen, Status „Eingegangen“, Zuständigkeit nach Regeln, Frist, geheimer Statuslink (`/a/<schlüssel>`), SHA-256-Prüfsumme über Aktenzeichen, Eingang und Angaben. Mails: „Eingangsbestätigung mit Aktenzeichen“ an die antragstellende Person, „Neuer Antrag“ an die Zuständigen (jeweils optional mit PDF). Die antragstellende Person sieht das Aktenzeichen sofort auf der Dankeseite.

**Bearbeitung** unter **Formulare › Antragseingang**. Sichtbar sind Anträge, die einer Person direkt oder über eine Gruppe zugewiesen sind, sowie alle Anträge eigener oder freigegebener Antragsformulare (Admins: alle). Bearbeiten (Status, Nachrichten, Notizen, Zuweisung, Frist) dürfen Zuständige, Besitzer:innen und Freigaben ab Stufe 2; Stufe 1 sieht nur. Zuständige brauchen **kein** Recht „Formulare“.

- **Status:** Eingegangen, In Bearbeitung, Rückfrage, Genehmigt, Abgelehnt, Erledigt, Zurückgezogen – mit optionaler Mitteilung und Mail an die antragstellende Person. Genehmigt/Abgelehnt/Erledigt/Zurückgezogen schließen den Vorgang.
- **Rückfrage:** Die antragstellende Person antwortet auf der Statusseite; der Antrag springt dann automatisch auf „In Bearbeitung“, die Zuständigen bekommen eine Mail.
- **Interne Notizen** sieht nur die Verwaltung; Nachrichten und Status erscheinen auch auf der Statusseite.
- **Prüfsumme:** Die Vorgangsansicht zeigt „unverändert seit Eingang“ – oder warnt, wenn die gespeicherten Angaben nachträglich verändert wurden.

**Antragskatalog einbinden:** Unten im Antragseingang (nur Admins) stehen Link, iframe-Code (`/antraege-embed`) und die erlaubten Webseiten. Aus dem eingebetteten Katalog öffnen sich Anträge in einem neuen Fenster.

**Mail-Vorlagen:** Gruppe „Online-Anträge“ unter E-Mail-Vorlagen: Eingangsbestätigung, Neuer Antrag, Statusänderung/Nachricht, Antwort der antragstellenden Person, Zugewiesen, Frist überschritten, Neuer Arbeitsschritt, Arbeitsschritt überfällig/Eskalation, Nachforderung, Erinnerung an eine Nachforderung, Nachforderung beantwortet.

**Datenschutz:** Verfahren ins Verzeichnis der Verarbeitungstätigkeiten aufnehmen, Löschfristen festlegen (Anträge löschen Sie im Reiter „Antworten“ des Formulars), Hinweistext zum Datenschutz ins Formular aufnehmen. Der Statuslink ist geheim und steht nicht im PDF.

### Prozesse und Workflow

Menü **Formulare › Prozesse** (Recht „Prozesse“). Ein Prozess beschreibt, wie Anträge bearbeitet werden – als Folge von Arbeitsschritten. Er ist **wiederverwendbar**: Im Reiter **Antrag** eines Antragsformulars wählen Sie unter „Bearbeitungsprozess“, welcher Prozess für neue Anträge gilt. Ohne Prozess wird wie bisher frei über den Status gearbeitet.

**Schritttypen**

| Typ | Was passiert | Einstellungen |
|---|---|---|
| **Aufgabe** | Die Sachbearbeitung hakt Prüfpunkte ab und erfasst interne Felder (Text, Zahl, Betrag, Datum, Auswahl, Ja/Nein). Erst wenn alle Prüfpunkte abgehakt und Pflichtfelder gefüllt sind, lässt sich der Schritt erledigen | Checkliste (eine Zeile je Punkt), interne Felder, Anleitung, „danach weiter mit …“ |
| **Freigabe** | Genehmigen oder ablehnen (Ablehnung nur mit Begründung) | **Vier-Augen-Prinzip** (wer den vorigen Schritt erledigt hat, darf nicht freigeben), bei Ablehnung: Vorgang beenden (Status wählbar) oder **zurück** zu einem früheren Schritt |
| **Nachforderung** | Die antragstellende Person bekommt eine Mail mit Link und reicht Angaben/Dateien über ihre Statusseite nach; der Prozess wartet so lange (Status „Rückfrage“) | **Wer legt fest, was nachgefordert wird:** „Fest im Prozess“ (wird automatisch verschickt) oder „**Sachbearbeitung wählt**“ – dann hält der Prozess an, die zuständige Person (mit Frist zum Zusammenstellen) bekommt die vorgeschlagenen Felder, kann sie ändern, eine **Vorlage** wählen und das Ergebnis als neue Vorlage speichern. Nachricht, Felder (wie im Formular-Baukasten, auch Datei-Upload, Adresse und Kartenfragen), Antragsfragen zur Korrektur, Frist (danach einmal Erinnerung) |
| **E-Mail bestätigen** (Double-Opt-in) | Die antragstellende Person bekommt eine Mail mit Bestätigungslink; der Prozess hält an, bis sie klickt (Status „Rückfrage“ bleibt unberührt) | Zusätzlicher Hinweis, Frist (Tage), einmal erinnern nach der Hälfte der Frist, bei Ablauf: Zuständige informieren oder Vorgang beenden („Zurückgezogen“). Im Vorgang: Link erneut senden oder ohne Bestätigung fortfahren. Mail-Vorlage „E-Mail-Adresse bestätigen (Double-Opt-in)“ |
| **Zahlung anfordern** | Die antragstellende Person bekommt eine Zahlungsaufforderung mit Link; der Prozess wartet, bis bezahlt ist | Bezeichnung, fester Betrag oder internes Feld (z. B. `gebuehr`), Frist, Zahlarten, bei Ablauf: Zuständige informieren oder Vorgang beenden. Siehe [Zahlungen](#zahlungen-paypal-überweisung-bar) |
| **Automatik** | Läuft sofort ohne Zutun | Aktionen: E-Mail (an Antragsteller:in, Zuständige oder feste Adresse; optional mit Antrag oder Dokumenten als Anhang), Status setzen, **Dokument als PDF** erzeugen (z. B. Bescheid; Briefkopf, Anschrift, Datum und Aktenzeichen setzt das Portal), Zuständigkeit ändern |

**Für jeden Schritt:** interner Name und – optional – **Name für Antragsteller:in** (erscheint als Fortschrittsleiste auf der Statusseite; leer = Schritt bleibt unsichtbar), Status beim Start, **Bedingung** (Schritt nur ausführen, wenn eine Antwort, ein internes Feld oder das Ergebnis eines früheren Schritts passt – sonst wird er übersprungen). Aufgaben und Freigaben haben eine **Zuständigkeit** (Zuständige des Vorgangs, bestimmte Person, Gruppe, wer den vorigen Schritt erledigt hat), eine **Frist** in Tagen und optional eine **Eskalation** (nach X Tagen Überschreitung Vertretung bzw. Leitung informieren oder die Aufgabe übertragen). Am **Ende** setzt der Prozess den Abschluss-Status (z. B. Genehmigt) und informiert auf Wunsch die antragstellende Person.

**Platzhalter** in Mails, Mitteilungen und Dokumenten: `{aktenzeichen}`, `{titel}`, `{name}`, `{eingang}`, `{datum}`, `{status}`, `{bearbeiter}`, `{statuslink}`, `{gebuehr}`, `{feld:schluessel}` (internes Feld; den Schlüssel legen Sie im Editor selbst fest – vorgeschlagen wird die nächste freie Nummer, z. B. `{feld:3}`; erlaubt sind Kleinbuchstaben, Ziffern und `_`, eindeutig im ganzen Prozess) und `{frage:Titel der Frage}` (Antwort aus dem Antrag).

**Bedienung des Editors:** links die Schritte (Ziehen am Griff ändert die Reihenfolge, „Schritt hinzufügen“ fügt nach dem ausgewählten Schritt ein), rechts die Einstellungen des gewählten Schritts. **Entwurf speichern** (Strg+S) prüft den Prozess und zeigt Hinweise (fehlende Person, leere Nachforderung, Rücksprünge). **Veröffentlichen** macht aus dem Entwurf eine neue **Version**: Neue Anträge laufen nach ihr, **laufende Vorgänge bleiben auf ihrer Version**. Frühere Versionen lassen sich in den Entwurf laden. Vorlagen beim Anlegen: „Einfache Prüfung“ und „Prüfung, Freigabe und Bescheid“. **Export/Import** als JSON (Zuständigkeiten werden beim Import zurückgesetzt). Löschen geht erst, wenn keine laufenden Vorgänge mehr den Prozess nutzen.

**Vorlagen für Nachforderungen** (unten auf der Seite Prozesse): häufige Nachforderungen einmal anlegen, im Vorgang mit einem Klick auswählen. Vorlagen lassen sich auch direkt aus dem Prozesseditor („Als Vorlage speichern“) und von jeder Sachbearbeitung beim Nachfordern speichern.

**Im Alltag:**

- **Meine Aufgaben** (Navigation, mit Zähler) listet offene Schritte, die mir oder meinen Gruppen zugewiesen sind, nach Frist; Gruppenaufgaben mit „Übernehmen“. Darunter: Nachforderungen, auf deren Antwort gewartet wird.
- Im **Vorgang** zeigt die Schrittleiste den Stand; der aktuelle Schritt lässt sich dort erledigen, umverteilen, mit neuer Frist versehen oder überspringen. Wer einen Schritt zugewiesen bekommt, sieht den Vorgang und darf ihn bearbeiten – auch ohne Freigabe des Formulars.
- **Nachfordern** geht jederzeit auch ohne Prozess (Knopf im Vorgang): eigene Felder zusammenklicken, Vorlage wählen oder Antragsfragen zur Korrektur öffnen. Die ursprünglichen Angaben bleiben unverändert (Prüfsumme bleibt gültig); Korrekturen stehen markiert daneben, nachgereichte Dateien liegen unter `data/portal/forms/<formular>/<antrag>/req<nr>/`, erzeugte Dokumente unter `…/docs/`.
- Wird ein Vorgang über den Status abgeschlossen oder zurückgezogen, enden offene Schritte und Nachforderungen.
- Fristen, Erinnerungen und Eskalationen prüft der Hintergrunddienst alle 5 Minuten.

## Ablage (DMS)

Modul **Ablage (DMS)** (Verwaltung › Module). Menü **Ablage › Recherche** und – mit dem Recht „Aktenplan verwalten“ – **Aktenplan** und **Löschfristen**.

**Einrichten in drei Schritten**

1. **Aktenplan** anlegen: Bereiche mit Aktenplankennzeichen und Namen, beliebig verschachtelt (z. B. `1 Ordnung` › `1.2 Hundesteuer`). Unterbereiche erben Rechte und Löschfrist, solange sie keine eigene haben.
2. **Rechte** je Bereich: Personen oder Gruppen mit **Lesen** (recherchieren, öffnen, herunterladen) oder **Schreiben** (zusätzlich ablegen, Dateien hochladen und löschen, Angaben ändern). Rechte gelten für den Bereich und alle Unterbereiche. Jede:r sieht nur Vorgänge aus den eigenen Bereichen; **Admins sehen alles**.
3. Festlegen, wohin Vorgänge kommen: im **Prozesseditor** oben unter „Ablage der Vorgänge“ (gilt sofort für neue, laufende und abgeschlossene Vorgänge des Prozesses), sonst im Reiter **Antrag** des Formulars. Ist nirgends etwas eingestellt, landen Vorgänge im fest eingerichteten Bereich **„Nicht einsortiert“** – wer den Aktenplan verwaltet, darf dort ablegen und einsortieren.

**Was abgelegt wird:** Jeder Online-Antrag erscheint sofort nach dem Eingang in der Ablage und wird bei jeder Statusänderung aktualisiert (Antragsteller:in, Anschrift, Status, Volltext der Angaben). Beim **Abschluss** legt das Portal den Abschlussstand ab: das Antrags-PDF mit allen Anlagen und Kopien der erzeugten Dokumente (Bescheide). **Nachforderungen:** Sobald die antragstellende Person etwas nachreicht, legt das Portal die nachgereichten Angaben sofort als eigenes PDF („… Nachreichung …“) in der Ablage ab; das Antrags-PDF enthält zudem einen Abschnitt „Nachgereichte Angaben“ (je Nachforderung mit Datum, Anforderungstext, Antworten, korrigierten Feldern samt bisherigem Wert), nachgereichte Dateien werden als Anlagen eingebunden. Zusätzlich lassen sich Vorgänge **manuell ablegen** (Titel, Aktenzeichen, Antragsteller:in, Anschrift mit Adresssuche, Datum, Dateien bis 50 MB je Datei). Ein Abgleich im Hintergrund (alle 5 Minuten) holt Anträge nach, falls einmal etwas nicht übertragen wurde.

Außerdem landen **Ressourcenbuchungen** (bestätigt, mit Buchungsbestätigung als PDF; im Bereich der Ressource) und auf Wunsch **Ergebnisprotokolle von Abstimmungen** in der Ablage.

**Verschieben:** Im Eintrag „Im Aktenplan verschieben“ oder in der Recherche Einträge ankreuzen und gesammelt verschieben (Schreibrecht in Quelle und Ziel nötig). Von Hand verschobene Einträge bleiben, wo sie sind, auch wenn der Prozess später anders ablegt; die Löschfrist richtet sich nach dem neuen Bereich. Bereiche selbst verschieben Sie im Aktenplan über „Einordnen unter“. Jede Verschiebung steht im Protokoll.

**Personen (Bürger:innen):** Jeder Eintrag wird einer Person zugeordnet – automatisch über die E-Mail-Adresse, sonst über Name und PLZ; fehlende Kontaktdaten werden ergänzt, vorhandene nie überschrieben. Menü **Ablage › Personen**: Suche, Personenseite mit allen Vorgängen (nur aus Bereichen mit Leserecht), Kontaktdaten bearbeiten (wer in einem der Bereiche schreiben darf) und **Doppelungen zusammenführen** (Aktenplan-Verwaltung). Im Eintrag lässt sich die Person ändern oder neu anlegen.

**Recherche:** Volltext (Angaben, Notizen, Dateinamen), Antragsteller:in, Person, Aktenzeichen, Ort/PLZ/Straße, Bereich mit Unterbereichen, Antragsart, Status, Art (Online-Antrag/Buchung/manuell), Eingangsdatum. Suchen lassen sich unter einem Namen **speichern** (je Person). Export der Treffer als CSV.

**Löschfristen:** je Bereich in Jahren (vererbbar). Die Frist läuft am Ende des Jahres ab, in dem der Vorgang abgeschlossen wurde, plus N Jahre (laufende Vorgänge haben keine Frist). Unter **Löschfristen** stehen abgelaufene Vorgänge; Löschen geht nur mit Begründung, löscht bei Online-Anträgen auch den Antrag mit allen Uploads und wird protokolliert (Protokoll auf derselben Seite). Automatisch gelöscht wird nichts.

**Speicherort:** Dateien der Ablage unter `data/portal/dms/<nr>/`, Angaben in der Datenbank. Beide gehören in die Sicherung.

## BlueOtter Krankmelder

Modul „BlueOtter Krankmelder“ (Verwaltung › Module). **Standardmäßig aus**, weil Gesundheitsdaten verarbeitet werden – vor dem Einschalten bitte Datenschutzbeauftragte und Personalrat einbinden.

**Rechte** (Benutzer & Gruppen):

| Recht | Darf |
|---|---|
| **Krankmeldungen** | Meldungen der Arbeitgeber sehen und bearbeiten, für die die Person oder eine ihrer Gruppen als *zuständig* eingetragen ist. Ohne Zuständigkeit: nichts |
| **Krankmelder verwalten** | Alle Meldungen sehen; Arbeitgeber, Zuständige, Empfänger, Zugang, Texte, Löschfrist, Import, Protokoll |

Krank melden darf jede angemeldete Person (Menü „Krankmelder › Krank melden“) – dafür ist kein Recht nötig.

**Einrichten** (Krankmeldungen › Verwaltung):

1. **Arbeitgeber** anlegen (Reihenfolge mit Pfeilen). Je Arbeitgeber: *Zuständige* (Personen, Gruppen), weitere Empfängeradressen (z. B. Funktionspostfach), Betreff-Präfix, globale Kopie an die Personalverwaltung, Bemerkungsfeld, **Angaben und PDF in die Mail** (aus = nur Hinweis mit Link, empfohlen), Ablage im DMS mit Bereich. Inaktive Arbeitgeber erscheinen ausgegraut („noch nicht freigeschaltet“).
2. **Allgemein:** Titel, Einleitung, angebotene Meldewege, Adresse der Personalverwaltung (Standardempfänger), Löschfrist, Erinnerung bei fehlendem Nachweis, Bewertung, Einbetten.
3. **Zugang ohne Konto:** Passwort setzen und/oder **Zugangslink** erzeugen – daraus QR-Code für den Aushang (SVG/PNG/JPG), Kurzlink, iframe-Code. Neu erzeugen macht alte Links und QR-Codes ungültig.
4. **Anleitungen** für Beschäftigte und Personalverwaltung (Markdown). Mail-Texte: Verwaltung › E-Mail-Vorlagen, Gruppe „Krankmelder“.

**Meldewege und Status:**

| Meldeweg | Start-Status | Besonderheiten |
|---|---|---|
| Ohne AU | Neu | nur heute, Montag bis Freitag |
| Mit AU | Neu bzw. *Nachweis fehlt* | Upload PDF/JPG/PNG bis 5 MB (Inhalt geprüft); Folgebescheinigung ohne Startdatum übernimmt den Beginn aus der Vorgängermeldung, Datenlücken werden als Hinweis markiert |
| eAU | *Abruf offen* | keine Datei. Daten exakt wie auf dem Ausdruck: arbeitsunfähig seit, voraussichtlich bis, festgestellt am, Erst-/Folgebescheinigung, optional Personalnummer. Hinweise bei mehr als 3 Tagen Rückdatierung und wenn bei einer Folgebescheinigung „arbeitsunfähig seit“ vom Erstbeginn abweicht. Danach *eAU abgerufen* oder *Abruf erfolglos* (dann Nachricht an die Person) |
| Kind krank | Neu bzw. *Nachweis fehlt* | Name und Geburtsdatum des Kindes, Hinweis ab dem 12. Geburtstag |

Reicht die Person über ihre Statusseite einen Nachweis nach, springt die Meldung von *Nachweis fehlt* auf *Neu* und die Zuständigen erhalten eine Mail.

**Datenschutz:** Alle Angaben, Notizen, Nachrichten und Dateien liegen **verschlüsselt** (Schlüssel aus `PORTAL_SECRET_KEY` – geht er verloren, sind die Meldungen unlesbar). Das **Protokoll** (Krankmeldungen › Protokoll) zeigt jedes Ansehen, PDF, Datei, Export, Statuswechsel und Löschen und bleibt nach dem Löschen erhalten (ohne Inhalte). Mail-Texte und -Anhänge werden nach dem Versand aus der Warteschlange gelöscht. **Löschfrist:** bearbeitete Meldungen werden nach N Tagen automatisch gelöscht (0 = aus). Einträge in der Ablage (DMS) folgen den Fristen des Aktenplans und sind dort nicht zusätzlich verschlüsselt – Bereich mit passenden Leserechten wählen.

**Import aus dem eigenständigen Krankmelder:** Im alten System `data/krankmeldungen.db` und den Ordner `uploads/` in eine ZIP-Datei packen (`zip -r krankmelder.zip data/krankmeldungen.db uploads/`) und unter Verwaltung › Import hochladen (bis 60 MB). Größere Bestände: Datei nach `data/` des Portals kopieren und `docker compose exec portal python -m app.cli krank-import /data/krankmelder.zip`. Übernommen werden Arbeitgeber mit Empfängern, Bemerkungsfeld und Betreff, Personal-Mail, öffentliches Passwort und Zugangstoken (bestehende Werte im Portal bleiben), Anleitung, alle Meldungen (Bearbeitet → *Bearbeitet*, sonst *Neu* bzw. *Abruf offen*) mit Dateien und Bewertungen. Ein zweiter Import legt nichts doppelt an.

**Eigene Domain:** z. B. `krank.example.de` unter Verwaltung › Domains (siehe [Eigene Domains je Modul](#eigene-domains-je-modul)).

## Kartenlayer und Kartenbrowser

**Kartenlayer** (Verwaltung › Kartenlayer, Admins und Recht „Kartenlayer & Geocoding“) sind die systemweite Grundlage für den Kartenbrowser und für Kartenfragen in Formularen – auch wenn das Modul Kartenbrowser abgeschaltet ist.

**Voreingestellt:** basemap.de farbig und grau (WMTS-Kacheln, über das Portal), basemap.de Vektor (ausgeschaltet; wird direkt beim BKG geladen) und OpenStreetMap (über das Portal, eine Woche zwischengespeichert, wie es die Nutzungsrichtlinie der OSM Foundation verlangt). Startausschnitt: Verbandsgemeinde Otterbach-Otterberg – unter „Einstellungen“ per Kartenausschnitt änderbar.

**Neuer Layer:** Art wählen (Kacheln XYZ/WMTS, WMS/WMS-T, WFS, GeoJSON, Vektorkarte), Adresse eintragen, **Dienst abfragen** – die Layer des Dienstes erscheinen zur Auswahl; ein Klick übernimmt Layername, Version, Zeitwerte (WMS-T), Legende und Abfragbarkeit. Dann Name, Gruppe, Rolle (Grundkarte/Überlagerung), Deckkraft, Zoombereich, Quellenangabe. **Speichern und Vorschau** zeigt den Layer auf der Startgrundkarte.

**Schalter je Layer:** aktiv · öffentlich (auch ohne Anmeldung) · Formulare (Grundkarte für GPS-Fragen) · sichtbar (beim Öffnen eingeschaltet) · **Proxy**. Mit Proxy lädt der Browser alles vom Portal: Besucher:innen bleiben dem Anbieter unbekannt, Kacheln werden zwischengespeichert (je Layer einstellbar, Gesamtgröße unter Einstellungen), es gibt keine CORS-Probleme. Ohne Proxy lädt der Browser direkt beim Anbieter – dann gehört der Anbieter in die Datenschutzerklärung; das Portal erlaubt dessen Adresse automatisch in seiner Sicherheitsrichtlinie (weitere Hosts, etwa für Schriften von Vektorkarten, unter „Zusätzliche Hosts“).

**Weitere Funktionen:** Reihenfolge per Ziehen (= Reihenfolge im Kartenbrowser), **Erreichbarkeit prüfen** (Probeanfrage mit Antwortzeit; zeigt Dienstfehler wie „Layer not defined“), Duplizieren, **Export/Import** aller Layer als JSON (z. B. Austausch zwischen Verwaltungen), Zwischenspeicher je Layer oder ganz leeren, **Übernahme** von Diensten, die Benutzer:innen in gespeicherten Karten verwenden (als ausgeschalteter Systemlayer). Kaputte Kacheln und Dienstfehler erscheinen im Kartenbrowser unsichtbar statt als Fehlerbild.

**Schutz vor Überlastung:** Beim Herauszoomen fordert der Browser viele Kacheln auf einmal an, und große Ausschnitte berechnen WMS-Dienste langsam. Das Portal ruft deshalb höchstens 8 Kacheln gleichzeitig beim Anbieter ab; weitere warten, ohne Server oder Datenbank zu belegen, und wer länger als 6 Sekunden wartet (die Karte ist längst weitergezoomt), wird gar nicht mehr abgerufen. Gleiche Kacheln werden nur einmal geholt, ein Anbieter, der nicht antwortet, wird eine Minute lang nicht erneut gefragt, Kacheln außerhalb der eingestellten Zoomstufen (min./max. Zoom des Layers) gar nicht erst angefragt. WFS-Objekte werden nur bis zu einem Ausschnitt von 300 km geladen. Das Aufräumen des Zwischenspeichers läuft im Hintergrund. Das übrige Portal bleibt so auch bei hängenden Kartendiensten bedienbar; im Zweifel bleiben einzelne Kacheln kurz leer.

**Kartenbrowser** (Modul, `/karte`, einbettbar unter `/karte-embed`): öffentlich mit allen aktiven, öffentlichen Layern; angemeldet zusätzlich mit den internen. Das Suchfeld findet **Orte und Adressen** (Nominatim, siehe unten) und Koordinaten. **Zeichnen & messen** (Punkt, Linie, Fläche; benennen, einfärben, Eckpunkte verschieben, GeoJSON laden/herunterladen) steht allen offen. Mit dem Recht „Karten“ können Personen eigene Dienste hinzufügen und Karten samt Zeichnungen speichern/teilen (höchstens 500 Zeichnungen je Karte, Geometrien werden auf dem Server geprüft). Eigene Dienste laufen immer über den Proxy – aber nur mit vom Server signierter Beschreibung und nur zu öffentlichen Adressen (kein Zugriff auf `localhost`, interne Netze oder Docker-Dienste). Admins dürfen in der Layerverwaltung auch Dienste im eigenen Netz eintragen.

**Einbetten:** Unter Einstellungen „Einbetten erlaubt“ und optional die erlaubten Webseiten. Gespeicherte Karten mit öffentlichem Link liefern ihren iframe-Code unter „Meine Karten“.

### Adresssuche (Nominatim)

Adressfelder in Formularen, die manuelle Ablage und die Ortssuche im Kartenbrowser fragen **Nominatim** (OpenStreetMap) – immer **über den Server**, nie direkt aus dem Browser. Einstellungen unter **Kartenlayer › Einstellungen**:

| Einstellung | Bedeutung |
|---|---|
| Adresse des Dienstes | Standard: der öffentliche Dienst `https://nominatim.openstreetmap.org`. Für viele Anfragen besser ein eigener Nominatim-Server oder ein kommerzieller Anbieter mit Nominatim-Schnittstelle. Leer = Adresssuche aus |
| Länder | Suche auf Länder beschränken, z. B. `de` |
| Kontakt-E-Mail | Wird im User-Agent mitgeschickt; die Nutzungsrichtlinie des öffentlichen Dienstes verlangt eine Kontaktmöglichkeit |

Das Portal hält die **Nutzungsrichtlinie** des öffentlichen Dienstes ein: höchstens eine Anfrage pro Sekunde (weitere warten kurz), Ergebnisse 30 Tage zwischengespeichert, Suche erst nach einer Tipp-Pause, je Adresse höchstens 60 Anfragen pro Minute. Für Massenabfragen ist der öffentliche Dienst nicht gedacht. In die Datenschutzerklärung gehört: Suchbegriffe bzw. Koordinaten (nicht die IP-Adresse der Besucher:innen) werden an den eingestellten Dienst übermittelt.

**Hinweis für die Installation:** Die Adressen von basemap.de und OpenStreetMap entsprechen den Dienstbeschreibungen der Anbieter. Prüfen Sie nach dem ersten Start mit „Erreichbarkeit prüfen“, ob Ihr Server sie erreicht (Firewall/Proxy).

## Terminumfragen

Menü **Terminumfragen** (Recht „Terminumfragen“). Ein Doodle-Pendant auf dem eigenen Server; die Bedienung steht im [Benutzerhandbuch](BENUTZERHANDBUCH.md#6a-terminumfragen-wie-doodle).

- Vorschläge als ganze Tage oder mit Uhrzeit, Generator „Tage × Uhrzeiten“, Notizen je Vorschlag.
- Antworten Ja / Wenn nötig (abschaltbar) / Nein, Kommentar; Optionen: nur ein Termin, Plätze je Termin (Terminbuchung), verdeckte Umfrage, E-Mail Pflicht, Frist.
- Teilnahme über einen öffentlichen Link (mit Name, ohne Konto, Spam-Schutz und Begrenzung je Adresse) oder per persönlicher Einladung an Benutzer, Gruppen und Gäste mit Erinnerungen. Jede Person kann ihre Antwort über ihren persönlichen Link ändern; ein Cookie merkt sich das im selben Browser 180 Tage.
- Termin festlegen: Mail mit Kalenderdatei an alle oder **direkt eine Besprechung anlegen** (Raum, Outlook-Einladungen, persönliche Einwahllinks – wie unter „Besprechung planen“).
- Export als CSV; Kopie anlegen; als Datei ex- und importieren (mit Prozess, Datenblöcken und auf Wunsch Einsendungen – siehe Benutzerhandbuch).
- Mail-Vorlagen in der Gruppe „Terminumfragen“: Einladung, Erinnerung, neue Antwort (an die planende Person), Termin steht fest.
- **Teilen im Portal** (Abschnitt „Im Portal freigeben“ unten auf der Umfrage, nur Besitzer:in/Admins): 1 Ergebnisse einsehen (Raster, Teilnehmende, Export) · 2 zusätzlich einladen, erinnern, Link verwalten · 3 zusätzlich Vorschläge/Einstellungen ändern, Termin festlegen, Teilnehmende entfernen, löschen.
- Jede Person sieht ihre eigenen und die mit ihr geteilten Umfragen, Admins über „Alle anzeigen“ alle. Gehört eine Umfrage einer gelöschten Person, sehen sie nur noch Admins.

## Abstimmungen und Wahlen

Menü **Abstimmungen** (Recht „Abstimmungen“; Teil des Moduls „Umfragen & Abstimmungen“). Bedienung im [Benutzerhandbuch](BENUTZERHANDBUCH.md#6f-abstimmungen-und-wahlen).

- **Fragearten:** eine Antwort, mehrere Antworten (mindestens/höchstens), Rangfolge (Borda: Platz 1 bekommt so viele Punkte wie es Antworten gibt, jeder weitere einen weniger) und Punkte verteilen – jeweils mit „Enthaltung“.
- **Geheimhaltung:** *offen* (Stimmen mit Namen), *geheim* (das Wählerverzeichnis zeigt, wer abgestimmt hat; die Stimmzettel sind getrennt gespeichert, mit zufälliger ID und ohne Uhrzeit, im Verzeichnis steht nur der Tag), *anonym* (auch die Beteiligung einzelner Personen ist nicht sichtbar). Die Geheimhaltung ist nach dem Start nicht mehr änderbar, die Fragen nach der ersten Stimme nicht mehr.
- **Zugang** (kombinierbar): persönliche Einladung per Mail (geht beim Start raus), öffentlicher Link mit E-Mail-Bestätigung (der persönliche Link aus der Mail ist zugleich die Bestätigung; eine Stimme je Adresse; Bremse gegen Massenanmeldungen) und Zugangscodes (8 Zeichen ohne verwechselbare Zeichen, Druckbogen mit QR-Code).
- **Ergebnis:** live, nach der eigenen Stimme, nach dem Ende oder nur intern. Beim Beenden (von Hand oder zur eingestellten Frist, Prüfung alle 5 Minuten) wird das Ergebnis mit einer **SHA-256-Prüfsumme** über alle Stimmzettel festgeschrieben. Jede abstimmende Person bekommt eine **Quittung**, mit der sich prüfen lässt, dass ihr Stimmzettel gezählt wurde (ohne den Inhalt zu zeigen).
- **Ergebnisprotokoll** als PDF (Einstellungen, Zeitraum, Beteiligung, Ergebnis je Frage, Prüfsumme), auf Knopfdruck auch in die **Ablage**; Stimmzettel als CSV nach dem Ende.
- **Live-Modus** (`/votes/<nr>/live`) für den Beamer: QR-Code zum öffentlichen Link, Stimmenzahl und Balken aktualisieren sich alle 3 Sekunden, Ergebnis verdecken, starten/anhalten/beenden.
- Mail-Vorlagen in der Gruppe „Abstimmungen“; Freigaben in drei Stufen wie bei Terminumfragen.

## Terminbuchung

Menü **Terminbuchung** (Recht „Terminbuchung“). Vergleichbar mit Microsoft Bookings oder Calendly; Bedienung im [Benutzerhandbuch](BENUTZERHANDBUCH.md#6b-terminbuchung-z-b-vorstellungsgespräche).

- Zeitbereiche im Wochenkalender aufziehen (FullCalendar) oder per Formular mit wöchentlicher Wiederholung; überlappende Bereiche werden zusammengefasst. Daraus entstehen Zeitfenster aus **Dauer + Pause**, mit einstellbaren **Plätzen** je Fenster.
- Regeln: Vorlauf für Buchungen, Frist für Absagen/Verschieben, Termine je Person, nur mit persönlicher Einladung, Telefonnummer Pflicht.
- Gäste bekommen eine Bestätigung mit **Kalendereintrag** (Outlook-Besprechungsanfrage) und einen Verwaltungslink; Verschieben aktualisiert, Absagen entfernt den Kalendereintrag. Doppelbuchungen sind ausgeschlossen (Prüfung beim Speichern).
- **Online-Termine:** Pro Buchung legt das Portal einen eigenen Portal-Raum an (sichtbar unter „Meetings“ der anbietenden Person); der Gast kommt per persönlichem Link ohne Konto und ohne Aufnahmerecht hinein. Verschieben passt den Raumtermin an, Absagen löscht den Raum.
- **Erinnerungen** verschickt der Hintergrunddienst automatisch (Prüfung alle 5 Minuten).
- **Terminliste** mit Filter (Status, Zeitraum, Suche) und Sortierung; Export der gefilterten Liste als **iCal, CSV, JSON und Markdown**; **Kalender-Abo** über einen geheimen Link (`/b/feed/<schlüssel>.ics`, aktualisiert sich selbst, enthält personenbezogene Daten – nur an die zuständige Person).
- Mail-Vorlagen in der Gruppe „Terminbuchung“: Bestätigung, Verschiebung, Absage, Erinnerung, Hinweis an die anbietende Person, Einladung und Erinnerung zur Buchung.
- **Teilen im Portal** (z. B. mit der Personalstelle oder dem Auswahlgremium): 1 Buchungen einsehen (Kalender nur lesend, Terminliste, Exporte) · 2 zusätzlich Personen einladen, Buchungslink verwalten · 3 zusätzlich Zeitbereiche, Einstellungen, Kalender-Abo, Termine verschieben/absagen, Seite löschen. Bestätigungen und Hinweise laufen weiter über die anbietende Person.
- Datenschutz: Gespeichert werden Name, E-Mail, optional Telefon und Nachricht. Löschen Sie Buchungsseiten nach Abschluss (z. B. des Auswahlverfahrens); damit werden alle Buchungen gelöscht.

## Ressourcenbuchung

Modul **Ressourcenbuchung**, Menü **Ressourcen** (Recht „Ressourcen“ zum Anlegen). Bürger:innen buchen über den öffentlichen Katalog `/r` (einbettbar mit `/r-embed`).

**Aufbau:** Alle Verwaltungsseiten haben oben dieselbe Leiste (Übersicht, Planer, Buchungen, Auswertung, Vereine, Kalender-Links, Feiertage), darunter den Pfad und den Seitenkopf mit den Aktionen rechts – beim Durchklicken bleibt alles an seinem Platz. Die **Übersicht** zeigt die Ressourcen wahlweise als **Karten** oder als **Tabelle** (sortier- und durchsuchbar, mit offenen Anfragen und nächster Buchung je Ressource); die Wahl merkt sich das Portal. Auch der öffentliche Katalog `/r` lässt sich zwischen Karten und Tabelle umschalten.

**Öffentliche Darstellung:** Jede Ressource hat eine eigene Seite mit Fotogalerie (Vollbild), Eckdaten als Kacheln, Ausstattung als Symbole (aus dem Feld „Ausstattung“, eine Zeile je Merkmal – Stichwörter wie Küche, barrierefrei, Beamer, Parkplatz bekommen passende Symbole), Räumen, Preisübersicht (Miete, Tarife, Zusatzleistungen, Kaution, Storno), Belegungskalender, Karte mit Routenlink und dem **Anbieter** mit Wappen und Kontakt (Reiter Allgemein, aus Verwaltung › Körperschaften). Im Katalog `/r` haben die Kartenpunkte die **Farbe ihrer Art** (Ressourcen › Darstellung, sonst automatisch) mit Legende; ein Klick öffnet ein Info-Fenster mit Foto, Anbieter, Eckdaten und „Ansehen & buchen“. Der Katalog lässt sich nach Anbieter filtern.

**Buchen für Bürger:innen:** Ein Monatskalender zeigt je Tag frei / teilweise frei / belegt / nicht buchbar. Bei ganzen Tagen wird der erste und dann der letzte Tag angetippt; bei Zeitblöcken und stundenweiser Buchung der Tag und darunter die Zeit – stundenweise auf einer Zeitleiste (Beginn antippen, dann Ende; belegte Zeiten sind gesperrt). Die Preisvorschau trennt **Gebühren** und **Kaution** („wird erstattet“) und nennt den Betrag „zu zahlen“.

**Preise einstellen** (Reiter „Räume & Preise“): eine Tabelle mit nur den eingeschalteten Buchungsarten, Wochenend-/Feiertagspreise per Schalter, Teilräume darunter, die Kaution getrennt daneben und eine Vorschau „So sehen es Bürger:innen“. Der Einrichtungsassistent zeigt alle Werte der Vorlage offen (Preise je Buchungsart, Kaution, Zusatzleistungen zum Abwählen) – nichts wird verdeckt übernommen.

**Ressource einrichten** (Reiter im Bearbeiten-Dialog):

| Reiter | Inhalt |
|---|---|
| Allgemein | Name, Art, Beschreibung, Ausstattung, Anschrift mit Koordinaten (für die Karte, per Klick aus der Anschrift), Personenzahl, **aktiv** und **im öffentlichen Katalog** |
| Zeiten & Regeln | Buchungsarten (ganze Tage mit Höchstzahl am Stück, Zeitblöcke, stundenweise mit Raster und Mindest-/Höchstdauer), Buchungszeiten je Wochentag (ganztags, von–bis, geschlossen), Vorlauf, höchstens im Voraus, Rüstzeit davor und Reinigung danach, **Anfrage mit Freigabe** oder **Sofortbuchung** |
| Räume & Preise | Preise je Tag/Block/Stunde, jeweils mit eigenem Wochenend-/Feiertagspreis; **Teilräume** mit eigenen Preisen und Personenzahl (die ganze Ressource belegt alle Teilräume) |
| Tarife & Zusatzleistungen | Tarifgruppen in Prozent der Miete, optional mit Nachweis-Upload; Zusatzleistungen und Preisbestandteile pauschal, je Tag, je Stunde, je Stück, **je Person**, **je angefangene N Personen** (z. B. Wasser/Kanal/Strom 10 € je angefangene 25 Personen) oder als **Staffel nach Personenzahl** (`bis 50: 20; bis 100: 35; darüber: 50`), jeweils mit optionalem **Mindest-/Höchstbetrag**, Höchstanzahl, **Bestand** (gleichzeitig verfügbar über alle Buchungen) und **Pflicht**. Je Bestandteil eine **Regel bei Absage**: wie die Storno-Regel der Ressource, immer erstattet, **bleibt fällig** bei Absage weniger als N Tage vorher, oder **nur bei Absage** (z. B. Nachvermietungskosten – nicht in der Rechnung, nur bei später Absage). Hängt ein Bestandteil von der Personenzahl ab, fragt das Buchungsformular sie im ersten Schritt verpflichtend ab |
| Angaben | zusätzliche Felder (Feld-Editor wie bei Nachforderungen) |
| Zahlung & Storno | Kaution, Zahlfrist, Zahlarten, Kostenstelle; Selbststornierung, kostenlos bis X Tage vorher, danach Gebühr in % (Kaution immer voll zurück); abweichende Regeln je Preisbestandteil (Reiter Tarife & Zusatzleistungen) gehen vor und stehen im Stornotext |
| Zuständig & Ablage | zuständige Person, Gruppe, Funktionspostfach (Mails bei Anfragen), **Ablagebereich** |
| Erinnerungen & Warteliste | Erinnerung an Buchende X Tage vorher (mit eigenem Hinweistext, z. B. Schlüsselabholung) und an Zuständige Y Tage vorher (0 = aus); **Warteliste** an/aus |
| Sperrzeiten | gesperrte Tage (ganz oder je Teilraum) |
| Fotos & Nutzungsordnung | Fotos (JPG/PNG/WebP bis 25 MB, bis 40 Stück): mehrere auf einmal hineinziehen oder auswählen – die Seite wird dabei nicht verlassen, ungespeicherte Änderungen bleiben erhalten. Fotos werden automatisch auf 1600 px verkleinert, richtig gedreht und ohne Kamera- und Standortdaten (EXIF/GPS) gespeichert; dazu ein Vorschaubild für Katalog, Listen und Karte. Reihenfolge per Ziehen oder Pfeilen, das erste Foto ist das **Titelbild**, je Foto eine **Bildunterschrift** (Vollbildansicht, Alternativtext). Nutzungsbedingungen als Text (müssen bestätigt werden) und/oder PDF. Zusätzlich lassen sich **Rechtstexte verknüpfen** (Modul Rechtstexte): Benutzungsordnung, Gebühren-/Entgeltordnung, Satzung oder sonstige Rechtsgrundlage, optional mit Paragraf, mehrere je Ressource. Verlinkt wird immer die gerade gültige, veröffentlichte Fassung (Ressourcenseite, Buchungsbestätigung als PDF); mit „beim Buchen bestätigen“ muss der Text vor dem Absenden akzeptiert werden. Die Seite des Rechtstexts zeigt umgekehrt „Gilt für Räume & Plätze“. Export/Import findet die Texte über ihre Adresse wieder |

**Feiertage** (Menü „Feiertage“): gesetzliche Feiertage des eingestellten Bundeslands werden berechnet (Bundesland stellen Admins ein, Vorgabe Rheinland-Pfalz), eigene Tage wie die Kerwe lassen sich ergänzen. Samstag, Sonntag und diese Tage gelten als „Wochenende/Feiertag“.

**Ablauf einer Buchung:** Formular mit Live-Preis → E-Mail-Bestätigung innerhalb von 24 Stunden (sonst verfällt die Vormerkung) → bei Sofortbuchung sofort fest, sonst **Anfrage** (Zeitraum vorgemerkt, Zuständige bekommen eine Mail) → Bestätigung mit PDF und **Zahlungsaufforderung** (Frist laut Einstellung, höchstens bis einen Tag vor Beginn) → ohne Zahlung verfällt die Reservierung automatisch. Stornieren durch Buchende nach den Regeln (Erstattung bei PayPal automatisch, sonst als Erstattung vermerkt), durch die Verwaltung immer voll.

**Verwaltung:** **Buchungen** (Filter, offene Anfragen zuerst), Buchung mit Bestätigen/Ablehnen samt Mitteilung, Zahlung (als bezahlt markieren, erstatten), **Übergabe** (Schlüssel, Zustand) und **Abnahme** (Schäden, einbehaltener Teil der Kaution; der Rest wird erstattet), Notizen, Stornieren. **Intern eintragen** ohne Vorlauf und Bestätigung, auf Wunsch kostenlos und als **Serie** (wöchentlich, alle 2 oder 4 Wochen bis zu einem Datum; belegte Termine werden übersprungen und genannt). Die Übersicht und die Startseiten-Kachel zeigen offene Anfragen, Übergaben und Rücknahmen des Tages und Unbezahltes.

**Neue Ressource:** Assistent mit Vorlagen (Bürgerhaus, Gruppenraum, Grillplatz, Gerät, Dienstwagen, leer), danach Checkliste bis zum Freischalten. Ressourcen lassen sich **kopieren** und als **JSON-Datei ex-/importieren** (mit Räumen, Tarifen, Zusatzleistungen, Fotos und Nutzungsordnung; ohne Buchungen, Zuständige und Ablage).

**Planer** (`/resources/planner`): Wochenübersicht aller Ressourcen; Buchungen per Drag & Drop verschieben (gleiche Uhrzeit, anderer Tag und/oder andere Ressource; Tarif und Zusatzleistungen werden über den Namen übertragen, der Preis neu berechnet oder beibehalten).

**Buchung ändern:** Zeit, Ressource, Räume, Tarif, Zusatzleistungen, Kontakt und Preis. Zahlungsausgleich automatisch: offene Zahlung storniert und neu angefordert; bezahlt und günstiger → Differenz erstattet; teurer → Nachzahlung angefordert. Mail „Buchung geändert“ mit neuer PDF-Bestätigung (abschaltbar). Der frei gewordene Zeitraum geht an die Warteliste.

**Warteliste:** Eintrag mit Double-Opt-in (Vereine ohne). Wird ein Zeitraum frei (Storno, Ablehnung, Verfall, Verschieben, abgelaufene Bestätigung), bekommt der oder die Erste ein **exklusives Angebot für 24 Stunden** (der Zeitraum ist solange für andere gesperrt), danach der oder die Nächste. Gebucht wird über den Link ohne erneute Bestätigungsmail. Die Warteliste steht auf der Belegungsseite der Ressource.

**Mehrere Ressourcen in einer Buchung (Merkliste):** Buchende merken Teile vor („Weitere Ressource dazubuchen“, 24 Stunden vorgemerkt) und schicken alles mit einer Bestätigungsmail ab. Die Teile tragen eine gemeinsame Kennung (Sammelbuchung); Bestätigung und **eine gemeinsame Zahlung** gehen raus, sobald über alle Teile entschieden ist. Wird ein Teil storniert, wird bei offener Zahlung der Rest neu angefordert, bei bezahlter der Anteil erstattet.

**Vereine & Dauernutzer** (`/resources/clubs`): Name, E-Mail-Adresse (= Zugang), Kontakt, **Tarif** (greift an allen Ressourcen mit einem Tarif dieses Namens), **Zahlweise** – *sofort* (wie alle), *Rechnung je Buchung* (nur Überweisung, kein Verfall bei Verzug), *Sammelrechnung je Monat* (keine Zahlung bei der Buchung; „Abrechnen“ erzeugt eine Zahlungsaufforderung über alle bestätigten Buchungen des Monats). Anmeldung unter `/r/login` per Link (30 Minuten gültig, danach 30 Tage angemeldet über ein eigenes, signiertes Cookie). **Selbstregistrierung** unter `/r/verein` lässt sich einschalten; neue Registrierungen warten auf Freigabe, ein Hinweis geht an das eingetragene Postfach.

**Erinnerungen:** Der Hintergrunddienst schickt sie alle 5 Minuten fällig; wer weniger als 12 Stunden vor dem Fenster gebucht hat, bekommt keine.

**Auswertung und Export:** `/resources/stats` (Buchungen, Belegungstage, Auslastung, Einnahmen je Monat, CSV) und CSV-Export der gefilterten Buchungsliste (Semikolon, für Excel).

**Belegung teilen:** im Portal auf der Belegungsseite (Freigabe: *Belegung einsehen* – Anlass und Veranstalter; *Mit Kontaktdaten*; *Verwalten*) und als geheimer Link unter **Kalender teilen** (iCal-Abo für Outlook/Google/Handy, Web-Ansicht, optional per iframe) in den Stufen *nur frei/belegt*, *mit Anlass/Veranstalter*, *vollständig* (nur mit Freigabe „Mit Kontaktdaten“), mit oder ohne vorgemerkte Anfragen, für eine oder mehrere Ressourcen (Sammelkalender). Links lassen sich widerrufen; Abrufe werden gezählt.

**Mail-Vorlagen:** Gruppe „Ressourcen“ (Bestätigungslink, Anfrage eingegangen, bestätigt mit PDF, abgelehnt, storniert, verfallen, geändert, Erinnerung, Warteliste bestätigen/frei geworden, Vereins-Anmeldelink, Sammelrechnung, Hinweis an Zuständige). **Speicherort:** Fotos, Nutzungsordnungen und Uploads der Buchenden unter `data/portal/resources/`.

## Zahlungen (PayPal, Überweisung, bar)

**Einrichten** (Verwaltung › PayPal & Bankverbindung, nur Admins):

1. Bei developer.paypal.com eine App anlegen, **Client-ID** und **Secret** eintragen (Secret wird verschlüsselt gespeichert), Modus **Sandbox**, aktivieren, „PayPal-Verbindung testen“.
2. In der PayPal-App einen **Webhook** auf `https://<portal>/paypal/webhook` anlegen (Ereignisse *Payment capture completed/denied/refunded/reversed*, *Checkout order approved*) und die Webhook-ID eintragen. Die Signatur jedes Webhooks lässt das Portal von PayPal prüfen.
3. Mit Sandbox-Konten testen, dann auf **Live** umstellen und die Live-Zugangsdaten eintragen.
4. Für Überweisungen Empfänger, IBAN, BIC und Bank eintragen; Kürzel der Zahlungsnummer (z. B. `Z-2026-00001`) und Vorgabe-Zahlfrist.

**So läuft eine Zahlung:** Die zahlende Person öffnet die Zahlseite (Link in der Mail bzw. nach dem Absenden), wählt PayPal (Weiterleitung zu PayPal, dort auch Lastschrift/Karte je nach PayPal-Konto, danach zurück; das Portal bucht serverseitig ab und prüft den Betrag) oder sieht die Bankverbindung mit Verwendungszweck. Überweisungen und Barzahlungen markiert die Verwaltung im Vorgang oder unter **Zahlungen** als bezahlt. Zwei Tage vor Fristende geht einmal eine Erinnerung raus; nach Fristablauf reagiert der Vorgang (Buchung verfällt, Antrag wird beendet bzw. Zuständige werden informiert).

**Zahlungen** (Recht „Zahlungen“): alle Zahlungen mit Filtern (Status, Art, Zahlart, Zeitraum), Summen, **CSV-Export** für die Kasse (mit Kostenstelle, Kaution, PayPal-Transaktion), Detailseite mit Verlauf, Erstatten (PayPal automatisch, sonst als ausgezahlt vermerkt), Stornieren, Aufforderung erneut senden.

**Wo wird bezahlt:**
- Ressourcenbuchungen (siehe oben).
- **Formulare und Online-Anträge** – Formular › Einstellungen › „Gebühr / Bezahlung“: Grundbetrag und Zuschläge nach Antworten (*ist gleich* „Ja“ → + Betrag, *je Anzahl* → Zahl × Betrag, z. B. je Hund). Bei Anträgen auf Wunsch „gilt erst nach Zahlung als eingegangen“: Status **Zahlung offen**, Zuständige und Prozess starten erst nach der Zahlung; ohne Zahlung wird der Antrag nach der Frist beendet.
- Prozessschritt **„Zahlung anfordern“**: Betrag fest oder aus einem internen Feld einer früheren Aufgabe (Art „Betrag“, z. B. `gebuehr`), Frist, Zahlarten, Verhalten bei Fristablauf. Der Prozess wartet, bis bezahlt ist (auch bei manueller Markierung); Betrag 0 = Schritt wird übersprungen.

**Datenschutz:** PayPal erfährt Betrag, Zweck und Zahlungsnummer; PayPal gehört als Empfänger in die Datenschutzerklärung. Mail-Vorlagen in der Gruppe „Zahlungen“.

## Rechtstexte (Ortsrecht online)

Menü **Rechtstexte › Rechtstexte pflegen** (Recht „Rechtstexte“). Die öffentliche Ansicht liegt unter **`/recht`** (z. B. `https://portal.example.de/recht`) und ist ohne Anmeldung erreichbar; im Kopf der Portalseiten erscheint dafür der Link „Rechtstexte“. Verlinken Sie diese Adresse auf Ihrer Homepage.

**Ebenen (Rechtsbaum).** Unter **Ebenen** pflegen Sie die Gliederung nach Gebietskörperschaften. Voreingestellt ist: Europäische Union › Bundesrepublik Deutschland › Rheinland-Pfalz › Landkreis Kaiserslautern › Verbandsgemeinde Otterbach-Otterberg › die elf Ortsgemeinden bzw. die Stadt Otterberg. Andere Verwaltungen benennen die Ebenen einfach um. Jede Ebene hat eine Art (EU, Bund, Land, Landkreis, Verbandsgemeinde, Ortsgemeinde/Stadt, Sonstige – bestimmt das Symbol), kann unter jede andere verschoben, nach oben/unten sortiert und gelöscht werden (nur wenn darin keine Texte mehr liegen). Öffentlich erscheinen nur Ebenen, in denen veröffentlichte Texte liegen.

**Texte anlegen.** **Neuer Rechtstext**: Titel, Abkürzung, Art (Gesetz, Rechtsverordnung, Satzung, Richtlinie, Geschäftsordnung, Vertrag, Bekanntmachung, Sonstiges), Ebene, Stand/Fassung, Ausfertigung, Inkrafttreten, außer Kraft ab, Adresse (`/recht/<adresse>`, sonst automatisch). Den Text fügen Sie als Markdown ein oder laden eine Datei: **Word (.docx)** – Überschriften-Formatvorlagen (auch „Überschrift 1–6“) werden Gliederungsebenen, Tabellen bleiben Tabellen –, **PDF mit Textebene** (Seitenzahlen und Silbentrennung werden bereinigt; eingescannte PDFs ohne Text lassen sich nicht übernehmen) oder `.md`/`.txt` (UTF-8 oder Windows-Kodierung). Dateien bis 25 MB, Text bis 2 MB. Der Editor zeigt in der **geteilten Ansicht** sofort die Vorschau und rechts die erkannte Gliederung mit Hinweisen (Lücken in der Zählung, doppelte Nummern, leere Paragrafen); die Werkzeugleiste fügt Abschnitte, fortlaufend nummerierte Paragrafen und Absätze ein. **Dateien hochladen** übernimmt viele Dateien auf einmal in eine Ebene (z. B. die komplette Satzungssammlung einer Ortsgemeinde) – Titel aus der ersten Überschrift oder dem Dateinamen, auf Wunsch zunächst als Entwurf.

**So wird gegliedert:**

| Im Text | Ergebnis |
|---|---|
| `# Titel` (erste Zeile) | Titel des Rechtstexts |
| Text vor der ersten Gliederung | Eingangsformel / Präambel (kursiv) |
| `## Erster Teil – Allgemeines`, `### Abschnitt 2` … | Gliederungsebenen, beliebig tief |
| `### § 3 Ortsbezirke`, `### Artikel 5 Inkrafttreten` | Norm (Paragraf/Artikel) mit Überschrift |
| `(1) …`, `(2) …` am Zeilenanfang | nummerierte Absätze mit hängendem Einzug |
| Listen, Tabellen, **fett**, Links | wie in Markdown üblich (HTML wird nicht übernommen) |

Ohne `#`-Überschriften (aus Word, PDF oder einer Webseite kopiert) erkennt das Portal allein stehende Zeilen wie „§ 3 Ortsbezirke“, „§ 3“ mit der Überschrift in der nächsten Zeile, „Artikel 2“ oder „Zweiter Abschnitt“ selbst. Sätze wie „§ 5 gilt entsprechend.“ bleiben Text.

**Veröffentlichen.** Nur Texte mit Schalter **Öffentlich sichtbar** erscheinen unter `/recht` und in der Suche; Entwürfe sehen ausschließlich Personen mit dem Recht „Rechtstexte“ (mit Hinweis „nicht veröffentlicht“). In der Liste schaltet ein Klick auf „öffentlich/Entwurf“ um.

**Fassungen.** Jede inhaltliche Änderung sichert den bisherigen Text mit Datum und Bearbeiter:in – als **interne Sicherung** (Korrektur, bis zu 50 je Text) oder mit Haken **„Als neue Fassung speichern“** als **öffentliche frühere Fassung** mit Geltungszeitraum (von „In Kraft seit“ der alten bis „In Kraft seit“ der neuen Fassung). Öffentliche Fassungen sind unter `/recht/<adresse>/fassung/<nr>` abrufbar, `/recht/<adresse>?am=JJJJ-MM-TT` führt zur an diesem Tag geltenden Fassung, `/recht/<adresse>/vergleich` vergleicht zwei Fassungen absatzweise (Wortänderungen markiert). Unter **Frühere Fassungen** lassen sich alle ansehen, vergleichen und wiederherstellen.

**Zeitgesteuert.** **Neue Fassung vorbereiten** (Text oder Datei, Stand, Datum des Inkrafttretens): Der Hintergrunddienst übernimmt sie am Stichtag automatisch; die bisherige wird öffentliche frühere Fassung. Bis dahin sehen nur Bearbeiter:innen einen Hinweis. Texte mit erreichtem Datum **„außer Kraft ab“** werden automatisch gekennzeichnet, in der Übersicht unter „Außer Kraft getretene Texte“ gesammelt und in der Suche nur auf Wunsch gezeigt.

**Anlagen.** PDF-Anlagen (bis 20 MB) je Text, öffentlich unter `/recht/<adresse>/anlage/<nr>`.

**Querverweise.** Verlinkt wird nur, was im Text ausdrücklich als Verweis gesetzt ist (Knopf **Verweis** im Editor): `[[§ 4]]` bzw. `[[§ 4 Abs. 2]]` zeigt auf den Paragrafen im selben Text, `[[GemO § 24]]` oder `[[GemO]]` auf einen anderen veröffentlichten Text (Abkürzung oder Adresse), `[[GemO § 24|Gemeindeordnung]]` mit eigenem Linktext. Ein bloßes „§ 4“ im Fließtext wird nie automatisch verlinkt – so entstehen keine falschen Ziele. Verweise, die ins Leere zeigen (Kürzel unbekannt, Paragraf fehlt), meldet die Vorschau im Editor und zeigt sie öffentlich als normalen Text. Beim Zeigen eines Links erscheint eine Vorschau des Paragrafen.

**Anträge und Formulare.** `[[ABK § N]]` in Formularbeschreibungen und Hinweisen wird zum Link mit Vorschau. Online-Anträge haben im Reiter **Antrag** das Feld **Rechtsgrundlage** (Texte und Paragrafen); es erscheint im Antragskatalog und im Formular, und der Rechtstext zeigt „Zugehörige Online-Anträge“.

**Ex- und Import.** **Ex-/Import › exportieren** speichert alle Texte bzw. die einer Ebene als JSON – mit Ebenenpfad, früheren Fassungen und Anlagen. Beim **Import** werden Ebenen über ihren Namen zugeordnet und bei Bedarf angelegt; vorhandene Texte (gleiche Adresse) werden auf Wunsch als neue Fassung aktualisiert, sonst neu angelegt. So lässt sich Ortsrecht zwischen Portalen austauschen.

**Öffentliche Ansicht.** Volltext oder einzelne Abschnitte (Blättern mit Vor/Zurück), Baum-Inhaltsverzeichnis mit Filter und Scroll-Markierung, Sprung zu einem Paragrafen, Schriftgröße, Permalinks je Paragraf (z. B. `/recht/hauptsatzung/p3`), Druckansicht ohne Menüs, Markdown-Download. Die Suche findet Wörter in Titeln, Überschriften und Text (alle Wörter müssen vorkommen), eingeschränkt auf Ebene, Art oder einen Text; ohne Treffer wird automatisch nach dem ähnlichsten Wort gesucht, beim Tippen erscheinen Vorschläge (`/recht/suche.json`). Fundstellen werden markiert.

**Öffentlicher Link und Einbinden in die Homepage.** Unter **Rechtstexte pflegen › Link & Einbinden**:

- **Öffentlicher Link** (`/recht`, eine Ebene `/recht/ebene/<nr>` oder ein Text `/recht/<adresse>`) – zum Verlinken, für das Amtsblatt oder einen QR-Code.
- **Einbinden per iframe** über `/recht-embed/…`: dieselben Seiten ohne Menü, Kopf und Fuß des Portals, nur mit einer schmalen Leiste „In neuem Fenster öffnen“. Wählen Sie den Umfang (alle Texte, eine Ebene – z. B. nur eine Ortsgemeinde – oder ein einzelner Text), das Farbschema (hell, dunkel, wie Gerät) und die Höhe. Bei **automatischer Höhe** enthält der Code ein kleines Skript, das den Rahmen der Länge des Inhalts anpasst und beim Blättern an den Rahmenanfang springt. Den Code fügen Sie im CMS der Homepage als HTML-Baustein ein; rechts sehen Sie eine Vorschau.
- **Wer darf einbinden?** Einbinden lässt sich ganz abschalten oder auf bestimmte Webseiten beschränken (z. B. `https://www.otterbach-otterberg.de`, auch `https://*.otterbach-otterberg.de`). Leer = jede Seite. Technisch: Nur `/recht-embed` sendet `Content-Security-Policy: frame-ancestors …`; alle anderen Portalseiten (Anmeldung, Verwaltung …) senden `X-Frame-Options: DENY` und lassen sich nie in fremde Seiten einbetten.
- **Keine Cookies:** Wer die Rechtstexte ohne Anmeldung aufruft – direkt oder eingebettet –, bekommt kein Cookie. Für die Homepage ist dafür also kein Cookie-Hinweis nötig. Eingebettet wird immer nur Veröffentlichtes gezeigt, auch wenn jemand im Portal angemeldet ist.

**Rechtsverbindlichkeit.** Die Onlinefassung ist ein Service; maßgeblich bleibt die öffentliche Bekanntmachung nach Ihrer Hauptsatzung. Ein entsprechender Hinweis gehört z. B. in die Beschreibung der obersten Ebene oder in die Eingangsformel.

## Sitzungen & Cookies

Menü **Verwaltung › Sitzungen & Cookies** (nur Admins). Technische Übersicht über alle Anmeldungen:

- **Angemeldete Benutzer** mit Anzahl Sitzungen und letzter Aktivität; grüner Punkt = in den letzten 5 Minuten aktiv. **Alle abmelden** beendet alle Sitzungen einer Person sofort (z. B. bei verlorenem Laptop oder Ausscheiden).
- **Sitzungen** einzeln: Gerät/Browser, Anmeldezeit, letzte Aktivität, IP-Adresse, zuletzt aufgerufene Seite, Anmeldeart (Passwort oder Passwort + 2FA). **Beenden** wirkt beim nächsten Klick der Person.
- **Alle anderen abmelden** (oben rechts) beendet alle Sitzungen außer der eigenen – etwa nach einem Sicherheitsvorfall.
- **Session-Cookie:** Name `jsm_session`, 12 Stunden ab letzter Aktivität, HttpOnly, SameSite=Lax, Secure (sobald `PORTAL_BASE_URL` mit https beginnt), signiert mit `PORTAL_SECRET_KEY`. Der Inhalt des eigenen Cookies wird lesbar angezeigt (Geheimnisse gekürzt), ebenso alle Cookies, die Ihr Browser an den Server schickt, mit ihrem Zweck.

Technisch trägt das Cookie eine zufällige Sitzungskennung; in der Datenbank liegt nur deren Hash. Fehlt der Eintrag (beendet, abgelaufen), gilt das Cookie nicht mehr. Nach einem Passwortwechsel oder „Passwort vergessen“ werden alle anderen Sitzungen der Person automatisch beendet. Jede Person sieht und beendet ihre eigenen Anmeldungen unter **Profil › Sicherheit › Angemeldete Geräte**. Abgelaufene Einträge räumt das Portal selbst auf.

## E-Mail-Vorlagen

Menü **E-Mail-Vorlagen** (nur Admins). Hier stehen alle Mails, die das Portal verschickt, gruppiert nach Konten (Einladung, Passwort, Anmeldecode), Besprechungen, Aufnahmen, Formularen, Terminumfragen und Terminbuchung.

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
| Logo | PNG, JPG, WebP oder SVG, am besten mit transparentem Hintergrund. **Große Dateien sind kein Problem** (bis 40 MB, z. B. Druckvorlagen): Der Server verkleinert Rastergrafiken automatisch auf Anzeigegröße (höchstens 1600 × 320 Pixel) und meldet das. SVG bleibt unverändert (bis 2 MB). Höhe einstellbar, „Name zeigen“ blendet den Namen neben dem Logo ein oder aus |
| Favicon | Das kleine Symbol im Browser-Tab (PNG, JPG, WebP, ICO oder SVG; wird auf 256 px verkleinert). **Ohne eigenes Favicon erzeugt das Portal es automatisch aus dem Logo** (Ränder abgeschnitten, quadratisch, 64 px); die Seite zeigt dann „automatisch aus dem Logo erzeugt“. Ein hochgeladenes Favicon hat Vorrang |

**Auf Standard zurücksetzen** (unten) entfernt alle Design-Einstellungen samt Logo und Favicon.

**Auch in der Konferenz anwenden** (Schalter bei „Farben, Logo & Darstellung“, standardmäßig an): Die Konferenzoberfläche übernimmt das Logo (als Wasserzeichen oben links) und einen Hintergrund in der Hauptfarbe. Weil Jibri die Konferenzoberfläche aufzeichnet, erscheint das Logo auch in den Videoaufnahmen. Änderungen gelten beim nächsten Betreten einer Konferenz (Seite neu laden). Ohne hochgeladenes Logo zeigt die Konferenz kein Wasserzeichen.

**Farbschema:** Steht es auf „Immer hell“ oder „Immer dunkel“, gilt das für alle, und der Umschalter oben rechts wird ausgeblendet. Bei „Automatisch“ kann jede Person selbst umschalten.

## Räume und Zugang

Es gibt zwei Arten von Konferenzräumen:

| | **Freie Räume** | **Portal-Räume** |
|---|---|---|
| Wie entstehen sie? | Jede:r ruft die Konferenzadresse mit einem beliebigen Namen auf, z. B. `https://meet.…/elternabend`, oder nutzt „Konferenz ohne Anmeldung starten“ auf der Anmeldeseite | Im Portal: **Meeting anlegen** oder **Besprechung planen** |
| Wer kommt hinein? | Jede:r mit der Adresse, ohne Konto | Nur **angemeldete Benutzer:innen** und **Gäste mit Link** (Gastlink oder persönlicher Link aus der Einladung) |
| Wer moderiert? | Die erste Person im Raum | Angemeldete Benutzer:innen, sobald sie den Raum betreten. **Gäste nie automatisch**, auch nicht, wenn sie allein im Raum sind; ein Moderator kann einen Gast aber bewusst zum Moderator machen |
| **Aufnahme** | **nie** | ja, durch angemeldete Benutzer:innen (nicht durch Gäste) |
| Chatprotokoll | nie | ja, zusammen mit einer Aufnahme |

**Wer ohne Link oder Anmeldung einen Portal-Raum aufruft**, sieht in Jitsi „Warten auf den Gastgeber“. Dort führt „Ich bin der Gastgeber“ zur Portal-Anmeldung. Ohne Konto kommt man nicht hinein, auch nicht, wenn die Gastgeberin schon im Raum ist.

**Gastzugänge zu Portal-Räumen**

- **Gastlink** (auf der Seite des Meetings, „Einladungslink für Gäste“): Wer ihn öffnet, gibt seinen Namen ein und ist als Gast im Raum. Ist ein Link in falsche Hände geraten: **Neuen Gastlink erzeugen**, der alte funktioniert dann nicht mehr.
- **Persönlicher Link**: Jede Person, die per **Besprechung planen** eingeladen wird, bekommt einen eigenen Link (in der Mail und im Kalendereintrag). Er funktioniert, bis die Person ausgeladen oder die Besprechung abgesagt wird.
- Gäste dürfen **nicht aufnehmen** und werden **nie automatisch Moderator:innen**. Sind nur Gäste im Raum, hat die Konferenz bis zum Eintreffen einer angemeldeten Person keine Moderation. Ein Moderator kann einen Gast im Teilnehmermenü bewusst zum Moderator machen.
- **Nach der Umstellung (Oktober 2026):** Einladungen, die vorher verschickt wurden, enthalten noch die direkte Konferenzadresse. Externe Gäste kommen damit nicht mehr in Portal-Räume. Für anstehende Besprechungen deshalb einmal **„Einladung erneut senden“** klicken, dann haben alle ihren persönlichen Link.

**Schalter „Konferenzen ohne Anmeldung“** (unter **Benutzer & Gruppen**, nur Admins):

- **Freigegeben** (Standard): freie Räume wie oben beschrieben.
- **Gesperrt**: Auch jeder freie Raum verlangt eine Anmeldung oder einen Gastlink. Die Einstellung wirkt sofort, ohne Neustart.

**Technischer Hintergrund (für die Betreuung):** Jitsi lässt Verbindungen ohne Token zu (`JWT_ALLOW_EMPTY=1`, keine Gast-Domain). Zwei kleine Prosody-Module aus dem Ordner `prosody/` setzen die Regeln durch: `mod_portal_access` beantwortet Raumanfragen ohne Token für Portal-Räume mit „Anmeldung erforderlich“ und lässt Aufnahmen nur in Portal-Räumen und nur mit Token mit Aufnahmerecht zu. `mod_portal_access_muc` weist direkte Beitritte ohne Token ab, macht Portal-Benutzer beim Betreten zu Moderatoren, lehnt die automatische Beförderung von Gästen durch Jicofo (Auto-Owner) ab und schreibt das Chatprotokoll. Die Liste der Portal-Räume schreibt das Portal nach `data/portal-rooms/rooms.json`. Fehlt die Datei, verlangt Prosody für alle Räume eine Anmeldung (sicherer Zustand). Aufnahmen, die trotzdem aus einem freien Raum stammen, verwirft das Portal.

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

**Postfach-Diagnose:** Unten auf der Seite „Postfach-Diagnose (Zu-/Absagen)“ zeigt die neuesten 25 Nachrichten im Antwort-Ordner. Je Nachricht steht dort, ob sie als Antwort erkannt wird und zu welcher Besprechung, oder warum nicht. Die Diagnose liest nur und verändert nichts. Mit „Nachrichten der letzten 14 Tage erneut auswerten“ werden auch bereits geprüfte Nachrichten noch einmal verbucht, etwa nach einer Korrektur der Einstellungen.

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

Wenn noch ein anderer Admin existiert: Dieser klickt unter **Benutzer & Gruppen** bei Ihnen auf „Passwort-Link senden“ (und bei Bedarf „Zwei-Faktor zurücksetzen“).

Wenn nicht: Auf dem Server (Notfallwerkzeug):

```bash
docker compose exec portal python -m app.cli users                       # Konten anzeigen
docker compose exec portal python -m app.cli set-password admin@example.org   # neues Passwort setzen
docker compose exec portal python -m app.cli make-admin kollege@example.org   # Konto zum aktiven Admin machen
docker compose exec portal python -m app.cli reset-2fa admin@example.org      # Zwei-Faktor zurücksetzen (Telefon verloren)
```

Das Passwort wird nicht angezeigt, wenn Sie es eintippen. Das ist normal.

## Eigene Domains je Modul

Unter **Verwaltung › Domains** (nur Admins) bekommt jedes Modul mit öffentlichen Seiten auf Wunsch eine eigene Domain – Formulare, Online-Anträge, Terminumfragen & Abstimmungen, Terminbuchung, Ressourcenbuchung, Rechtstexte, Kartenbrowser, Krankmelder. Kurzlinks behalten ihre Einstellung unter Kurzlinks › Einstellungen.

1. DNS-Eintrag (A/AAAA oder CNAME auf die Portal-Domain) für die neue Domain anlegen.
2. Domain eintragen und speichern. Das Portal schreibt die Proxy-Konfiguration, Caddy lädt sie selbst neu.
3. **Zertifikat:** Ist unter HTTPS & Zertifikat Let's Encrypt eingeschaltet, holt Caddy für die neue Domain automatisch ein Zertifikat und **erneuert es selbstständig** (Ports 80 und 443 müssen erreichbar sein). Im selbst signierten Modus gilt Caddys eigene CA. „Zertifikate prüfen“ zeigt den Stand je Domain.

Unter der Modul-Domain liefert das Portal nur die öffentlichen Seiten des Moduls und gemeinsame Hilfspfade (Stile, Kartenkacheln, Adresssuche, Bezahlseite). „/“ führt zur Einstiegsseite (z. B. `/krank`), alles andere – Anmeldung, Verwaltung, andere Module – wird auf die gleiche Adresse unter der Portal-Domain umgeleitet. Das Modul bleibt zusätzlich unter der Portal-Domain erreichbar; schon verteilte Links funktionieren weiter. Neue Links in Mails, QR-Codes und Einbettungscodes verwenden die Modul-Domain. Leeres Feld = nur noch Portal-Domain.

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

**Update-Hinweis:** Einmal täglich vergleicht das Portal seine Version (`portal/app/VERSION`) mit der im Repository (nur die Versionsnummer wird gelesen). Gibt es eine neuere, sehen Admins auf der Startseite und unter „Über dieses Portal“ einen Hinweis. Dort lässt sich die Prüfung abschalten oder sofort ausführen. Das Update selbst bleibt bewusst ein Handgriff (oben); Zertifikate erneuert Caddy dagegen automatisch.

**Hat sich etwas an den Prosody-Modulen geändert** (Ordner `prosody/`, z. B. beim Update auf die Version mit Umfragen), zusätzlich `docker compose restart prosody`. Laufende Konferenzen werden dabei kurz getrennt – am besten außerhalb der Arbeitszeit. **Hat sich die Proxy-Vorlage geändert** (`caddy/Caddyfile`), übernimmt das Portal die Änderung beim Start automatisch in die verwaltete Konfiguration.

**Jitsi aktualisieren:** In `.env` bei `JITSI_IMAGE_VERSION` die neue Version eintragen (Liste: <https://github.com/jitsi/docker-jitsi-meet/releases>), dann `docker compose pull && docker compose up -d`. Die Images sind fest versioniert (Jitsi `stable-11031`, Caddy `2.11.7`, Python `3.12.15-slim`), damit ein Neustart nie unbemerkt eine andere Version zieht. Steht in einer älteren `.env` noch `JITSI_IMAGE_VERSION=stable`, bitte auf eine feste Version ändern. Caddy lässt sich über `CADDY_IMAGE_VERSION` in `.env` anheben.

**Sicherheitsupdates prüfen:** Python-Pakete stehen fest in `portal/requirements.txt`, Browser-Bibliotheken in `portal/app/static/vendor/` (Versionen in `vendor/README.md`). Prüfen z. B. mit `pip-audit -r portal/requirements.txt`; für die Bibliotheken die Sicherheitshinweise der Projekte (GitHub Advisories) ansehen.

**Härtung der Container (ab Version 2026.10.1):** Die Jitsi-Container bekommen das Portal-Geheimnis und das Admin-Passwort nicht mehr; das Portal läuft mit minimalen Linux-Rechten und bindet den Datenordner von Caddy (private Schlüssel) nicht mehr ein – das öffentliche Root-Zertifikat kopiert Caddy alle 5 Minuten nach `data/caddy/conf/root.crt`. Bei bestehenden Installationen nach dem Update einmal `docker compose up -d --force-recreate` und die Dateirechte nachziehen:

```bash
chmod 750 data && chmod 700 data/portal data/caddy/data
```

## Sicherung und Wiederherstellung

**Was sichern?** Den Ordner `data/portal/` (Datenbank mit Benutzern, Meetings, Kurzlinks, Formularen und Antworten; MP3-Dateien; Logo; Formular-Uploads; Ablage/DMS), `data/caddy/` (Zertifikate) und die Datei `.env`. Bei Bedarf zusätzlich `data/recordings/` (Videos).

**Sauber sichern (Datenbank im laufenden Betrieb):**

```bash
docker compose exec portal python -c "import sqlite3; s=sqlite3.connect('/data/portal.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
```

Danach `data/portal/backup.db` sowie die Ordner `data/portal/audio/`, `data/portal/forms/`, `data/portal/dms/`, `data/portal/resources/` und `data/portal/branding/` wegkopieren, am einfachsten alles mit `rsync -a data/portal/ /pfad/zur/sicherung/`.

**Wiederherstellen:** `docker compose down`, gesicherten Ordner `data/portal/` zurückkopieren (`backup.db` als `portal.db`), dieselbe `.env` verwenden, `docker compose up -d`.

> Die `.env` muss **dieselbe** sein wie zum Zeitpunkt der Sicherung (besonders `PORTAL_SECRET_KEY`). Sonst sind gespeicherte Passwörter (SMTP, IMAP), der SpeechMind-Key und die Authenticator-Schlüssel der Zwei-Faktor-Anmeldung unlesbar. Mail-Zugänge und Key müssen dann neu eingegeben, die Zwei-Faktor-Anmeldung aller Personen zurückgesetzt werden.

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
| Einladungen kommen in Outlook nicht an bzw. nicht als Besprechungsanfrage | Unter **Benachrichtigungen** „Testeinladung (Kalender) an mich“ an ein Outlook-Postfach schicken. Steht im Versandprotokoll „gesendet“, aber im Posteingang ist nichts: **Junk-E-Mail-Ordner** und bei Microsoft 365 die **Quarantäne** prüfen (Kalendereinladungen von schlecht authentifizierten Absendern werden dort gern abgefangen). Abhilfe: Für die Absenderdomain **SPF und DKIM** beim Mailanbieter einrichten bzw. den Absender in Exchange als vertrauenswürdig eintragen. Bis Oktober 2026 hatte der Kalenderteil zudem falsche Zeilenenden, die Outlook verwirft: aktuelle Version einspielen |
| Zu-/Absagen (z. B. aus Outlook) erscheinen nicht | 1. Unter **Benachrichtigungen** muss „Antworten im Postfach auswerten“ **vor dem Versand** eingeschaltet sein. Sonst ist die planende Person Organisator, und Outlook schickt die Antwort an sie. Abhilfe: einschalten und auf der Besprechungsseite „Einladung erneut senden“. 2. Das IMAP-Konto muss das Postfach der **Absenderadresse** sein. 3. „Postfach-Diagnose (Zu-/Absagen)“ öffnen. Taucht die Antwort dort nicht auf, ging sie an eine andere Adresse oder liegt im Junk-Ordner (dann Ordner eintragen bzw. Absender als sicher markieren). Steht dort „nein“, nennt die Zeile den Grund. 4. In Outlook beim Annehmen „Antwort jetzt senden“ wählen, nicht „Antwort nicht senden“ |
| Designänderungen sind nicht zu sehen | Schalter „Eigenes Design“ oben auf der Seite einschalten und speichern. Für die Konferenz zusätzlich „Auch in der Konferenz anwenden“ |
| Aufnahme-Knopf fehlt | Nur angemeldete Benutzer dürfen aufnehmen; Jibri-Log prüfen (`docker compose logs jibri`) |
| Aufnahme erscheint nicht unter „Aufnahmen“ | In `data/recordings/<sitzung>/` muss eine Datei `.finalized` liegen. Fehlt sie: `chmod +x jibri/finalize.sh`, Jibri neu starten |
| Status „Fehlgeschlagen“ | Meldung in der Zeile lesen, Ursache beheben (z. B. SpeechMind-Key), **Erneut versuchen** |
| Einladungsmail kommt nicht an | Spam-Ordner prüfen; **Benachrichtigungen** → Versandprotokoll ansehen; Testmail senden |
| „Zu viele Versuche“ | Eingebaute Bremse gegen Passwort-Raten: ca. 10 Minuten warten |
| Link „ungültig oder abgelaufen“ | Neuen Link anfordern (Admin: „Einladung erneut senden“, Benutzer: „Passwort vergessen?“) |
| Menüpunkt fehlt bei einer Person | Recht in **Benutzer & Gruppen** setzen; ist das Modul unter **Module** abgeschaltet? |
| Kurzlink zeigt „nicht verfügbar“ | Link deaktiviert, abgelaufen oder Aufruf-Limit erreicht (Detailseite des Links). Kurz-Domain: DNS und Zertifikat prüfen (**HTTPS & Zertifikat**, `docker compose logs caddy`) |
| Formular: „Formular geschlossen“ | In den Formular-Einstellungen „Nimmt Antworten an“ und die Frist prüfen |
| Formular-Upload scheitert | Dateityp/-größe in der Frage prüfen. Mehr als 60 MB je Absendung lässt der Proxy nicht zu |
| Jemand hat Telefon für Zwei-Faktor verloren | **Benutzer & Gruppen** › Schild-Symbol „Zwei-Faktor zurücksetzen“ |
| Anmeldecode per Mail kommt nicht an | Versandprotokoll unter **Benachrichtigungen** prüfen; Spam-Ordner; notfalls Zwei-Faktor zurücksetzen |
| Logo-Upload: „Das Bild lässt sich nicht lesen“ | Datei ist beschädigt oder hat eine falsche Endung. In einem Grafikprogramm als PNG neu speichern |
| Umfragen fehlen in der Aufnahme | Nur in Portal-Räumen und während einer Aufnahme. Nach dem Update `docker compose restart prosody` ausgeführt? |
| Anderes | `docker compose logs --tail 100 portal` und die Meldung an die Betreuung weitergeben |
