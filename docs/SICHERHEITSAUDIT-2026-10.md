# Sicherheitsaudit Oktober 2026

Stand: 6. Oktober 2026 · Portal-Version 2026.10.1

Geprüft wurden alle externen Abhängigkeiten (Python-Pakete, Docker-Images, Browser-Bibliotheken), die Container-Konfiguration und der eigene Code des Portals – auch der neue Code der parallel entwickelten Erweiterungen (Formular-Export, Ressourcenbuchung, Rechtstexte). Alle Funde sind behoben, sofern unten nicht anders vermerkt.

Schweregrade: **kritisch** – aus dem Internet ohne Anmeldung ausnutzbar mit großem Schaden · **hoch** · **mittel** · **niedrig**.

## Abhängigkeiten

| Komponente | Vorher | Nachher | Grund |
|---|---|---|---|
| MapLibre GL JS | 5.24.0 | **6.12.0** | **Kritisch:** GHSA-jrc7-96c5-q579 (XSS über Umgehung des HTML-Filters in Popups/Attributionen, alle Versionen bis 6.4.0, für 5.x kein Fix). MapLibre 6 gibt es nur noch als ES-Modul; `static/maplibre-global.js` stellt es wie bisher als `window.maplibregl` bereit |
| DataTables | 3.1.2 | 3.1.3 | Fehlerbehebungen |
| SQLAlchemy | 2.0.54 | 2.1.3 | aktuelle Hauptversion |
| tzdata | 2026.4 | 2026.5 | aktuelle Zeitzonen |
| markdown-it-py | 3.0.0 | 4.2.0 | aktuelle Hauptversion |
| reportlab | 4.4.10 | 5.0.1 | aktuelle Hauptversion |
| regex | neu | 2026.9.29 | Zeitlimit für Formular-Prüfmuster (ReDoS) |
| Caddy | `2` (wandernd) | `2.11.7` | fest versioniert |
| Jitsi | `stable` (wandernd) | `stable-11031` | fest versioniert |
| Python-Basisimage | `3.12-slim` | `3.12.15-slim` | fest versioniert |

`pip-audit` meldet für `portal/requirements.txt` keine bekannten Lücken. Die übrigen Browser-Bibliotheken (Bootstrap, Font Awesome, FullCalendar, SweetAlert2, Coloris, Tom Select …) haben keine offenen Sicherheitsmeldungen.

## Anmeldung, Sitzungen, Rechte

| Schwere | Fund | Behebung |
|---|---|---|
| hoch | Die Passwort-Bremse wertete den ersten Eintrag von `X-Forwarded-For` aus (frei wählbar) und leerte bei mehr als 5000 Einträgen den ganzen Speicher – beides hebelte sie aus | Adresse kommt von Uvicorn/Caddy; IPv6 je /64; älteste Einträge werden verworfen statt alles zu leeren |
| hoch | Fehlversuche beim zweiten Faktor wurden nur im Sitzungscookie gezählt; mit einer neuen Anmeldung war der Zähler wieder null (TOTP-Raten bei bekanntem Passwort) | Zusätzlicher Zähler je Konto auf dem Server (10 in 15 Minuten), danach verfällt auch der Mail-Code |
| mittel | Jede angemeldete Person mit Videorecht wurde in jedem Portal-Raum Moderator (Teilnehmende entfernen, aufnehmen) | Moderation und Aufnahme nur für Gastgeber:in und Admins |
| mittel | TOTP-Schlüssel, Wiederherstellungscodes und Einladungslinks lagen kurzzeitig im Sitzungscookie (nur signiert, nicht verschlüsselt) | Ablage im Speicher des Servers |
| mittel | „Benutzer verwalten“ konnte beliebige Rechte vergeben (auch sich selbst) und über Zurücksetzen-Links mächtigere Konten übernehmen | Nur eigene Rechte vergeben/entziehen; Konten mit weitergehenden Rechten nur durch Admins |
| mittel | Krankmelder: Zugangstickets blieben nach einem Passwortwechsel 12 Stunden gültig | Tickets hängen am aktuellen Passwort/Zugangslink |
| niedrig | Authenticator ließ sich ohne Passwort ersetzen | Passwort nötig |
| niedrig | Zahlungsseiten setzten Passwortwechsel- und 2FA-Pflicht nicht durch | wie alle anderen Seiten |
| niedrig | Ressourcen: Anmeldelink für Vereine wurde schon beim Aufruf verbraucht (Mail-Scanner); Vereins-Cookies ließen sich nicht widerrufen; Kalender-Abo-Links blieben gültig, wenn die anlegende Person den Zugriff verlor | Anmeldung erst per Knopf; „Auf allen Geräten abmelden“ (auch automatisch bei Sperre oder neuer Adresse); Kalender zeigen nur, was die Person noch sehen darf |

## Eingaben und Ausgaben

| Schwere | Fund | Behebung |
|---|---|---|
| hoch | ReDoS: Ein ungünstiges Prüfmuster in einem Formularfeld konnte den Server mit einer einzigen Einsendung blockieren | Prüfung mit Zeitlimit (`regex`-Modul) und Längenbegrenzung |
| mittel | SSRF über DNS-Rebinding bei Kartenebenen (Name zeigt bei der Prüfung nach außen, beim Abruf nach innen) | Nach dem Verbindungsaufbau wird die tatsächlich verbundene Adresse geprüft; gesperrt ist alles nicht Globale (auch 100.64/10, IPv4 in IPv6) |
| mittel | Eingangsbestätigungen ließen sich als Spam-Schleuder nutzen (fremde Adresse, eigener Text, Absender = Verwaltung) | Höchstens 5 je Adresse und Stunde |
| mittel | CSV-Exporte (Formulare, Anträge, Krankmeldungen, Buchungen, Zahlungen, Ablage, Umfragen, Abstimmungen, Kurzlinks, Ressourcen) übernahmen Formeln aus Eingaben | Zellen mit `= + - @` werden entschärft (`csvsafe.py`) |
| niedrig | Download von Buchungsanhängen: Dateiname ungeprüft im Header, Inhalt hätte im Portal angezeigt werden können | Korrekt kodiert, immer als Download mit `sandbox` |
| niedrig | Rechtstexte: Rücksprung über den `Referer` auch auf fremde Seiten | nur eigene Pfade |
| niedrig | Importe (Krankmelder-ZIP, Word-Dateien) ohne Grenze für die entpackte Größe | begrenzt |
| niedrig | Rechtstexte: Wortvergleich sehr großer Abschnitte ist rechenintensiv (öffentliche Seite) | Grenze für den Wortvergleich, Aufrufe je Adresse begrenzt |

CSRF-Schutz, Auto-Escaping der Vorlagen, Upload-Prüfungen und Datenbankzugriffe (nur über SQLAlchemy mit Parametern) waren bereits in Ordnung.

## Browser und Header

| Schwere | Fund | Behebung |
|---|---|---|
| mittel | Content-Security-Policy erlaubte `'unsafe-inline'` für Skripte – eine eingeschleuste Zeile HTML hätte Skripte ausführen können | Inline-Skripte nur mit einer Nonce je Antwort (wird beim Laden der Vorlagen automatisch ergänzt, Benutzereingaben bleiben unberührt); kurze Inline-Handler nur mit bekanntem Hash. Im Browser geprüft: erlaubte Skripte laufen, eingeschleuste werden blockiert |
| mittel | Nur einige Verwaltungsseiten wurden vom Browser-Cache ausgenommen | alle Seiten angemeldeter Personen |
| niedrig | HSTS fehlte für Konferenz- und Kurz-Domain | ergänzt (nur mit Let's Encrypt) |

## Container und Server

| Schwere | Fund | Behebung |
|---|---|---|
| hoch | `env_file: .env` gab `PORTAL_SECRET_KEY` und `PORTAL_ADMIN_PASSWORD` an alle Jitsi-Container | In den Jitsi-Containern geleert |
| hoch | Das Portal band Caddys Datenordner mit den privaten TLS-Schlüsseln ein (nur für das öffentliche Root-Zertifikat) | Caddy kopiert `root.crt` nach `/conf`; der Datenordner ist nicht mehr eingebunden |
| mittel | Wandernde Image-Tags (`caddy:2`, `jitsi/*:stable`, `python:3.12-slim`) | fest versioniert |
| mittel | Container ohne Rechte-Einschränkung | `no-new-privileges` überall außer Jibri, Portal mit `cap_drop: ALL` und nur `CHOWN`, `DAC_OVERRIDE`, `FOWNER` |
| mittel | `setup.sh` machte den Aufnahmeordner für alle Benutzer des Hosts beschreibbar | Datenordner `750`, Portal- und Caddy-Daten `700` (Container greifen über ihre Mounts direkt zu) |

## Bewusst offen (mit Begründung)

- **Einbettung ohne eingetragene Webseiten:** Einbettbare Seiten (`…-embed`) erlauben ohne Liste jede Webseite als Rahmen. Das ist gewollt (Einbinden auf der Gemeindeseite ohne Konfiguration). Empfehlung: unter den jeweiligen Modul-Einstellungen die eigene(n) Domain(s) eintragen – dann gilt nur diese Liste.
- **`style-src 'unsafe-inline'`** bleibt (viele `style`-Attribute, geringes Risiko ohne Skriptausführung).
- **Jibri** braucht `SYS_ADMIN` und läuft ohne `no-new-privileges`; mit selbst signiertem Zertifikat ignoriert Chrome in Jibri Zertifikatsfehler (nur für die eigene Konferenz-Domain). Mit Let's Encrypt `JIBRI_IGNORE_CERTIFICATE_ERRORS=false` setzen.
- **`JWT_ALLOW_EMPTY=1`** in Prosody ist nötig für Räume ohne Anmeldung; geschützte Portal-Räume prüft das Prosody-Modul `mod_portal_access`.
- **Portal als root im Container:** mit stark reduzierten Capabilities; ein eigener Benutzer würde Rechteänderungen an bestehenden Datenordnern erfordern und ist für ein späteres Update vorgemerkt.
- **Uvicorn `--forwarded-allow-ips "*"`**: unbedenklich, solange das Portal (wie in `docker-compose.yml`) nur über Caddy erreichbar ist; Caddy überschreibt `X-Forwarded-For` mit der echten Adresse.
