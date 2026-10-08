# Seminare und Lehrgänge

Das abschaltbare Modul **Seminare & Lehrgänge** liegt unter **Termine & Räume**. Es verwendet die bestehenden Benutzer, Gruppen, Vertretungen, Formulare, Terminumfragen, Abstimmungen, Liveumfragen, Ressourcen und Sammelmappen. Die erste Ausbaustufe organisiert kostenlose Veranstaltungen; Gebühren, Prüfungen und Noten sind nicht enthalten.

## Einrichtung und Zuständigkeit

Unter **Administration → Module** das Modul einschalten. Das Recht **Seminare** erlaubt, eigene Veranstaltungen anzulegen und zu planen. **Seminare verwalten** erlaubt die Verwaltung aller Veranstaltungen. Zur Teilnahme benötigt ein angemeldeter Benutzer keines dieser Verwaltungsrechte.

Im einfachen Modus betreut der Ersteller Planung und Durchführung. Im erweiterten Modus können zusätzlich Dozenten ausgewählt werden. Dozenten dürfen Unterlagen und Aktivitäten betreuen, Anwesenheit erfassen und Bescheinigungen ausstellen; Einstellungen, Termine, Einladungen und Zulassung bleiben bei der Planung. Ob Dozenten Teilnehmer-E-Mail-Adressen sehen dürfen, wird pro Veranstaltung eingestellt. Die vorhandene Vertretung unterstützt die berechtigte Planung im Abwesenheitszeitraum.

Für Gäste und öffentliche Anmeldung müssen SMTP und die öffentliche Portaladresse richtig eingerichtet sein. Versandaufträge, Fehler und die zentrale Seminar-Mailvorlage stehen in der bestehenden Benachrichtigungsverwaltung. Der laufende Portal-Worker bearbeitet Erinnerungen und abgelaufene Platzangebote etwa alle fünf Minuten.

## Eine Veranstaltung planen

1. **Neues Seminar** anlegen. Titel, Beschreibung und gegebenenfalls eine Kontaktadresse eintragen.
2. Zugang wählen: interne Portalnutzer, persönlich eingeladene Gäste und/oder öffentliche Anmeldung. Die öffentliche Übersicht zeigt ausschließlich veröffentlichte Veranstaltungen mit öffentlicher Anmeldung.
3. Buchung einstellen: standardmäßig **einzelne Termine**, alternativ die ganze Reihe. Termine und Buchungsmodus vor den ersten Anmeldungen festlegen; der Modus kann danach nicht mehr geändert werden. Bei bereits gebuchten Reihen werden zusätzliche Termine nicht stillschweigend ergänzt.
4. Termine eintragen. Wiederholungen: wöchentlich, vierzehntägig, monatlich an einem Datum oder am ersten bis fünften beziehungsweise letzten Wochentag. Nicht vorhandene fünfte Wochentage werden übersprungen. Zeiten verwenden die Portal-Zeitzone; nicht existierende Zeiten beim Wechsel auf Sommerzeit werden abgewiesen.
5. Vor Ort einen Raum oder eine externe Ortsangabe verwenden; mit einem HTTPS-Link sind Online- und hybride Veranstaltungen möglich. Ein Portalraum wird **ausdrücklich über die vorhandene Ressourcenbuchung reserviert**. Die Planung zeigt Konflikte und öffnet ein vorausgefülltes Buchungsformular; eine Raumauswahl allein erzeugt keine Buchung.
6. Optional eine eigene oder berechtigt vertretene Terminumfrage zur Vorplanung verknüpfen. Das Ergebnis wird ausdrücklich als endgültiger Termin übernommen. Eine Stimme ist keine Seminaranmeldung.
7. Unterlagen und Aktivitäten vorbereiten, danach **Veröffentlichen**.

Der Editor bietet Speichern ohne Seitenwechsel sowie Speichern und Schließen. Geänderte Einstellungen werden vor einer Terminaktion gespeichert. Schlägt das Speichern fehl, bleiben die Eingaben erhalten. Bei paralleler Bearbeitung wird eine veraltete Einstellung nicht über neuere Änderungen geschrieben.

Termine lassen sich einzeln oder zusammen mit den Folgeterminen ändern. Absagen benötigen einen Grund und werden in den persönlichen Kalenderdateien berücksichtigt. Das Absagen einer Veranstaltung informiert die betroffenen Teilnehmer über die Benachrichtigungsverwaltung.

## Anmeldung, Zulassung und Warteliste

Name und E-Mail-Adresse sind erforderlich, Organisation ist freiwillig. Bei angemeldeten Personen wird die Portalidentität verwendet; freiwillige Profildaten werden nur bei erlaubter Vorbelegung übernommen. Interne Nutzer melden sich über die Veranstaltungsseite an. Gäste werden per persönlichem E-Mail-Link eingeladen; bei öffentlicher Anmeldung wird die E-Mail-Adresse vor der Platzvergabe ausdrücklich bestätigt.

Die Planung kann Personen, Portalgruppen und externe E-Mail-Adressen einladen. Eine Einladung reserviert noch keinen Platz. Der persönliche Bereich zeigt die nächste erforderliche Aktion, Termine, Zulassungsstand und verfügbare Unterlagen. Teilnehmer sehen keine fremden Teilnehmerdaten.

**Kapazität 0** bedeutet unbegrenzt. Bei Begrenzung zählt eine Reihenbuchung an jedem enthaltenen Termin. Optional ist die manuelle Zulassung erforderlich. Bei voller Veranstaltung kann die Warteliste eingeschaltet werden. Ein frei gewordener Platz wird der nächsten berechtigten Person angeboten und muss innerhalb der eingestellten Frist ausdrücklich angenommen werden; standardmäßig 48 Stunden, höchstens bis zum Terminbeginn. Das Angebot hält den Platz während dieser Zeit frei. Ein abgelaufenes Angebot gibt ihn wieder frei.

Teilnehmer dürfen bis zur eingestellten Frist selbst absagen; standardmäßig 24 Stunden vor Beginn. Die Planung kann jederzeit absagen. Zulassung und Platzvergabe werden auch bei gleichzeitigen Anmeldungen auf die Kapazität geprüft.

Persönliche Gastlinks können nach dem letzten Termin ablaufen. **0 Tage bedeutet unbefristet**. Ein früherer Linkablauf begrenzt auch den Zugriff auf Unterlagen. Das Portal verlangt für interne persönliche Links weiterhin die Anmeldung als richtiger Benutzer.

## Formulare, Umfragen und Unterlagen

Vor der Platzvergabe kann ein Pflichtformular ausgefüllt werden müssen. Zusätzlich sind Aktivitäten **vorher**, **live** und **nachher** möglich. Weitere Pflichtformulare sind nur vor der Veranstaltung zulässig und werden vor den ersten Anmeldungen eingerichtet. Formulare nutzen den vorhandenen Renderer, seine Validierung und Benachrichtigungen; als Haupt-Anmeldeformular werden gewöhnliche, nicht anonyme Formulare ohne Zahlungsfunktion angeboten. Vor- und Nachfragen können dagegen anonym sein; ihr Abschluss wird für die Teilnahme vermerkt, ohne die Person in der anonymen Antwort einzutragen.

Abstimmungen und Liveumfragen verwenden die bestehenden Module und deren Freigaben. Freigabezeiten legen fest, wann ein persönlicher Schnelllink sichtbar und nutzbar wird.

Unterlagen können aus einer berechtigten Sammelmappe übernommen oder einzeln als Datei beziehungsweise Markdowntext erstellt werden. Die Vorlage wird kopiert; spätere Änderungen an der Mappe verändern das Seminar nicht. Rechtstexte, DMS-Dokumente und Formulare bleiben Portalverweise und behalten ihre Leserechte. **Ein Gastlink macht interne Portalobjekte nicht öffentlich.** Für externe Teilnehmer bei Bedarf ausdrücklich geeignete, freigegebene Dateien bereitstellen.

Jede Unterlage kann sofort, zu einem geplanten Zeitpunkt oder erst nach manueller Veröffentlichung erscheinen. Reihenfolge und Titel lassen sich pro Dokument bearbeiten. PDF-Dateien und Rechtstexte haben eine Vorschau. Unterlagen sind für bestätigte Teilnehmer zugänglich. Der Zeitraum nach dem letzten gebuchten Termin wird pro Veranstaltung eingestellt; **0 Tage bedeutet unbegrenzt**. Dateiuploads sind auf 20 MB pro Datei und die unterstützten Dokument-/Bildformate begrenzt.

## Durchführung und Nachbereitung

Die Teilnehmerverwaltung zeigt Zulassungsstand und Anwesenheit. CSV unterstützt die weitere Bearbeitung; die PDF-Liste bietet Platz für Unterschriften. Ein Terminfilter ermöglicht Listen für einzelne Termine. Teilnehmer sehen ihre eigenen Termine und können sie als ICS-Kalenderdatei herunterladen.

Ein persönlicher QR-Check-in führt zur Bestätigungsansicht für berechtigte Betreuung. **Das Öffnen oder Scannen bestätigt keine Anwesenheit automatisch.** Erst die ausdrückliche Aktion erfasst sie; frühestens 30 Minuten vor Terminbeginn. Der Check-in-Code enthält keinen persönlichen Gast-Zugangstoken.

Teilnahmebescheinigungen sind optional. Nach Ende der gebuchten Termine und ausreichender erfasster Anwesenheit kann die Betreuung eine PDF-Bescheinigung ausstellen. Bei Reihen wird die Mindestanwesenheit nach Termindauer berechnet; Standard **80 %**. Die ausgestellten Angaben werden als unveränderlicher Stand gespeichert. Korrekturen erfolgen durch Widerruf und erneutes Ausstellen. Vor dem Zurücknehmen einer bescheinigten Anwesenheit muss die aktive Bescheinigung widerrufen werden.

Erinnerungen werden standardmäßig **7 und 1 Tag** vor einem Termin eingeplant. Die Tage sind konfigurierbar; ein leeres Feld schaltet Erinnerungen aus. Bei später Anmeldung wird die nächste passende Erinnerung verwendet. Änderungen und Absagen verwenden denselben zentralen Versandweg. Ein Versandauftrag ist kein Nachweis, dass eine E-Mail gelesen wurde.

## Betrieb und Prüfung

Die zusätzlichen Tabellen werden beim normalen Portalstart angelegt. Vor einem Update wie üblich Datenbank und Datenverzeichnis sichern. Seminar-Uploads liegen im bestehenden Datenverzeichnis unter `seminars`; sie gehören in dieselbe Sicherung wie Datenbank und andere Portaldateien. Bestehende Formulare, Raumfreigaben und Rechte werden weiterverwendet, nicht durch die Seminarrechte ersetzt.

Die Umsetzung wurde mit den Portal-Integrationstests, Tests für parallele Platzvergabe, Zugriffsgrenzen, Pflichtformulare, Wartelisten, Kalender, Check-in, Bescheinigungen und Editor-Speicherverhalten geprüft. PDF-Listen und Bescheinigungen wurden zusätzlich gerendert und visuell kontrolliert.
