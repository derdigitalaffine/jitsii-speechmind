# Seminare und Lehrgänge

Das abschaltbare Modul **Seminare & Lehrgänge** liegt unter **Termine & Räume**. Es verwendet die bestehenden Benutzer, Gruppen, Vertretungen, Formulare, Terminumfragen, Abstimmungen, Liveumfragen, Ressourcen und Sammelmappen. Die erste Ausbaustufe organisiert kostenlose Veranstaltungen; Gebühren, Prüfungen und Noten sind nicht enthalten.

## Einrichtung und Zuständigkeit

Unter **Administration → Module** das Modul einschalten. Das Recht **Seminare** erlaubt, eigene Veranstaltungen anzulegen und zu planen. **Seminare verwalten** erlaubt die Verwaltung aller Veranstaltungen. Zur Teilnahme benötigt ein angemeldeter Benutzer keines dieser Verwaltungsrechte.

Im einfachen Modus betreut der Ersteller Planung und Durchführung. Portalbenutzer und externe Dozenten können bereits beim Anlegen zugeordnet werden. Externe benötigen keinen Portalzugang; Name, Organisation und E-Mail dienen zunächst der Zuordnung. Dozenten mit Portalzugang dürfen Unterlagen und Aktivitäten betreuen, Anwesenheit erfassen und Bescheinigungen ausstellen; Einstellungen, Termine, Einladungen und Zulassung bleiben bei der Planung. Wer nur einem Einzeltermin zugeordnet ist, erhält diese Rechte nur für diesen Termin. Ob Teilnehmer Dozenten-Kontaktadressen sehen und ob Dozenten Teilnehmer-E-Mail-Adressen sehen dürfen, wird ausdrücklich eingestellt. Die vorhandene Vertretung unterstützt die berechtigte Planung im Abwesenheitszeitraum.

Für Gäste und öffentliche Anmeldung müssen SMTP und die öffentliche Portaladresse richtig eingerichtet sein. Versandaufträge, Fehler und die zentrale Seminar-Mailvorlage stehen in der bestehenden Benachrichtigungsverwaltung. Der laufende Portal-Worker bearbeitet Erinnerungen und abgelaufene Platzangebote etwa alle fünf Minuten.

## Eine Veranstaltung planen

1. **Neues Seminar** anlegen. Titel, Beschreibung und gegebenenfalls eine Kontaktadresse eintragen.
2. Zugang wählen: interne Portalnutzer, persönlich eingeladene Gäste und/oder öffentliche Anmeldung. Die öffentliche Übersicht zeigt ausschließlich veröffentlichte Veranstaltungen mit öffentlicher Anmeldung.
3. Buchung einstellen: standardmäßig **einzelne Termine**, alternativ die ganze Reihe oder beide Möglichkeiten. Termine und Buchungsmodus vor den ersten Anmeldungen festlegen; der Modus kann danach nicht mehr geändert werden. Bei bereits gebuchten Reihen werden zusätzliche Termine nicht stillschweigend ergänzt.
4. Termine eintragen. Wiederholungen: wöchentlich, vierzehntägig, monatlich an einem Datum oder am ersten bis fünften beziehungsweise letzten Wochentag. Nicht vorhandene fünfte Wochentage werden übersprungen. Zeiten verwenden die Portal-Zeitzone; nicht existierende Zeiten beim Wechsel auf Sommerzeit werden abgewiesen.
5. Vor Ort einen Raum oder eine externe Ortsangabe verwenden; mit einem HTTPS-Link sind Online- und hybride Veranstaltungen möglich. Ein Portalraum wird **ausdrücklich über die vorhandene Ressourcenbuchung reserviert**. Die Planung zeigt Konflikte und öffnet ein vorausgefülltes Buchungsformular; eine Raumauswahl allein erzeugt keine Buchung.
6. Optional eine eigene oder berechtigt vertretene Terminumfrage zur Vorplanung verknüpfen. Das Ergebnis wird ausdrücklich als endgültiger Termin übernommen. Eine Stimme ist keine Seminaranmeldung.
7. Unterlagen und Aktivitäten vorbereiten, danach **Veröffentlichen**.

Der Editor bietet Speichern ohne Seitenwechsel sowie Speichern und Schließen. Geänderte Einstellungen werden vor einer Terminaktion gespeichert. Schlägt das Speichern fehl, bleiben die Eingaben erhalten. Bei paralleler Bearbeitung wird eine veraltete Einstellung nicht über neuere Änderungen geschrieben.

Termine lassen sich einzeln oder zusammen mit den Folgeterminen ändern. Absagen benötigen einen Grund und werden in den persönlichen Kalenderdateien berücksichtigt. Das Absagen einer Veranstaltung informiert die betroffenen Teilnehmer über die Benachrichtigungsverwaltung.

### Kompakte Planung und Assistent

**Neues Seminar** öffnet eine gemeinsame Planung mit kompakter Ansicht und optionalem Schritt-für-Schritt-Assistenten. Die Schritte sind **Grunddaten → Termine → Ort und Dozenten → Anmeldung und Prüfen**. Beim Ansichts- oder Schrittwechsel bleiben Eingaben erhalten. **Als Entwurf speichern** ist auch für eine noch unvollständige Planung möglich; Unterlagen und weitere Einstellungen können anschließend ergänzt werden.

Bei regelmäßigen Reihen Beginn, Uhrzeit, Dauer und Ende nach Terminanzahl oder Datum wählen. Beispiele sind alle 14 Tage, der erste Montag oder der letzte Freitag im Monat. Für unregelmäßige Reihen einzelne Tage hinzufügen. Vor dem Speichern erzeugt **Vorschau** eine bearbeitbare Terminliste: Thema, Zeit, Ort und abweichende Dozenten lassen sich pro Termin ergänzen. Gemeinsame Angaben werden einmal erfasst. Ein noch offenes Thema verhindert das Speichern als Entwurf nicht.

Eine Ortsfolge wie **Otterbach → Otterberg** wird über die tatsächlich enthaltenen Termine wiederholt. Feiertage in Rheinland-Pfalz werden gekennzeichnet und können ausgelassen werden; sie werden nicht automatisch verschoben. Die Terminanzahl zählt die geplanten Wiederholungen, sodass ausgelassene Feiertage die Zahl der enthaltenen Termine vermindern können. Schulferien sind nicht automatisch hinterlegt; die Vorschau weist auf ihre zusätzliche Prüfung hin. Höchstens 100 Termine können zusammen geplant werden.

Dozenten der Reihe werden als Vorgabe übernommen. Pro Termin sind eigene interne oder externe Dozenten möglich; ein Hauptdozent ist optional. Externe Dozenten können nur für die aktuelle Veranstaltung erfasst oder ausdrücklich in einer gemeinsamen Liste zur Wiederverwendung gespeichert werden. Eine E-Mail-Adresse erzeugt keinen Benutzerzugang. Das Benachrichtigen der Betreuung wird beim Veröffentlichen ausdrücklich angeboten. Die Nachricht an externe Dozenten nennt ihre Termine, Themen und Orte. Bei Online- oder Hybridterminen enthält sie einen persönlichen Konferenzzugang, der ausschließlich die Betreuung der zugeordneten Konferenz ermöglicht, keine Teilnehmerlisten, Unterlagenverwaltung oder Bescheinigungen. Der Zugang endet spätestens einen Tag nach dem Termin und wird bei entfernter Zuordnung, Absage oder zurückgenommener Veröffentlichung ungültig.

Eine gespeicherte Terminliste wird nicht durch eine neu erzeugte Wiederholung ersetzt; einzelne zusätzliche Termine können ergänzt werden. Gemeinsame Änderungen an Uhrzeit, Dauer, Orten, Dozenten oder Durchführung lassen sich auf diesen Termin, diesen und folgende zukünftige Termine oder alle zukünftigen Termine anwenden. Bereits individuell angepasste andere Termine bleiben geschützt; Änderungen veröffentlichter Termine benötigen eine ausdrückliche Bestätigung. Eine neue Dozentenvorgabe schreibt vergangene oder nicht ausgewählte Termine nicht um. Bereits veröffentlichte Termine ausdrücklich in der Terminverwaltung absagen. Neu hinzugefügte Termine einer veröffentlichten Reihe beginnen als Entwurf und können einzeln oder gesammelt freigegeben werden. Erst veröffentlichte Termine werden zur Buchung angeboten und an Abonnenten gemeldet.

### Vor Ort, online und hybrid

Pro Termin **Vor Ort**, **Online** oder **Hybrid** auswählen. Bei hybriden Terminen wählen Teilnehmer bei der Anmeldung ihre Teilnahmeart; Präsenz- und Online-Plätze werden getrennt begrenzt. **0** bedeutet jeweils unbegrenzt. Ein externer HTTPS-Konferenzlink oder ein Raum des vorhandenen Videokonferenzmoduls ist möglich; Portalräume können je Termin oder gemeinsam für die Reihe verwendet werden. Das Videokonferenzmodul muss für Portalräume aktiviert sein.

Teilnehmer können bis zum Anmeldeschluss selbst die Teilnahmeart wechseln, solange Plätze verfügbar sind. Die Planung kann sie später ebenfalls ändern. Bestätigung, persönliche Terminansicht und Kalender verwenden die gewählte Teilnahmeart. Konferenzzugänge sind nicht Teil der öffentlichen Seminarübersicht; sie werden für berechtigte Teilnehmer und Betreuung über den persönlichen Zugang bereitgestellt.

### Fester Teilnehmerkreis

Statt ausschließlich auf Einzelanmeldungen zu warten, kann eine Portalgruppe als fester Teilnehmerkreis gewählt werden, etwa für Führungsbesprechungen. Die Gruppenmitglieder werden beim Veröffentlichen der zukünftigen Termine ermittelt. Mit optionaler Teilnahmebestätigung erhalten sie zunächst eine Einladung; ohne diese Option wird die normale Platzvergabe angestoßen. Pflichtformulare, manuelle Zulassung, Platzlimits und Warteliste bleiben wirksam. Falls eine automatische Einplanung nicht möglich ist, bleibt eine bearbeitbare Einladung bestehen. Bestehende Antworten und Absagen werden bei erneutem Veröffentlichen nicht überschrieben; eine spätere Gruppenänderung ist keine laufende automatische Synchronisation.

## Anmeldung, Zulassung und Warteliste

Name und E-Mail-Adresse sind erforderlich, Organisation ist freiwillig. Bei angemeldeten Personen wird die Portalidentität verwendet; freiwillige Profildaten werden nur bei erlaubter Vorbelegung übernommen. Interne Nutzer melden sich über die Veranstaltungsseite an. Gäste werden per persönlichem E-Mail-Link eingeladen; bei öffentlicher Anmeldung wird die E-Mail-Adresse vor der Platzvergabe ausdrücklich bestätigt.

Die Planung kann Personen, Portalgruppen und externe E-Mail-Adressen einladen. Eine Einladung reserviert noch keinen Platz. Der persönliche Bereich zeigt die nächste erforderliche Aktion, Termine, Zulassungsstand und verfügbare Unterlagen. Fremde Teilnehmerdaten sind standardmäßig verborgen. Pro Termin kann eine Liste ausschließlich mit den Namen bestätigter Teilnehmer freigegeben werden; E-Mail-Adressen werden dort nicht angezeigt.

**Kapazität 0** bedeutet unbegrenzt. Bei Begrenzung zählt eine Reihenbuchung an jedem enthaltenen Termin. Optional ist die manuelle Zulassung erforderlich. Bei voller Veranstaltung kann die Warteliste eingeschaltet werden. Ein frei gewordener Platz wird der nächsten berechtigten Person angeboten und muss innerhalb der eingestellten Frist ausdrücklich angenommen werden; standardmäßig 48 Stunden, höchstens bis zum Terminbeginn. Das Angebot hält den Platz während dieser Zeit frei. Ein abgelaufenes Angebot gibt ihn wieder frei.

Teilnehmer dürfen bis zur eingestellten Frist selbst absagen; standardmäßig 24 Stunden vor Beginn. Die Planung kann jederzeit absagen. Zulassung und Platzvergabe werden auch bei gleichzeitigen Anmeldungen auf die Kapazität geprüft.

Persönliche Gastlinks können nach dem letzten Termin ablaufen. **0 Tage bedeutet unbefristet**. Ein früherer Linkablauf begrenzt auch den Zugriff auf Unterlagen. Das Portal verlangt für interne persönliche Links weiterhin die Anmeldung als richtiger Benutzer.

## Abonnement und Buchungshistorie

Ein **Reihenabonnement** informiert über neue veröffentlichte Termine und wichtige Reihenänderungen. Es reserviert keinen Platz; einzelne Termine oder die gesamte Reihe müssen zusätzlich gebucht werden. Angemeldete Portalbenutzer können direkt abonnieren. Externe bestätigen das Abonnement ausdrücklich per E-Mail-Link. Ein Abmelden vom Abonnement storniert keine bestehenden Buchungen.

Die Planung kann neue Termine sofort oder als tägliche Zusammenfassung melden. „Sofort“ bedeutet Versand über den nächsten Worker-Durchlauf, nicht unmittelbar im Browser. Bei täglicher Zusammenfassung werden neue Termine nach dem Wechsel des lokalen Kalendertags berücksichtigt. Wichtige Änderungen können unabhängig davon im nächsten Durchlauf versendet werden.

Unter **Meine Teilnahmen** gibt es anstehende, vergangene und alle Buchungen; **Meine Abonnements** zeigt abonnierte Reihen. Der persönliche Zugang erlaubt zusätzliche Einzelbuchungen und zeigt den bisherigen Buchungsverlauf. Eine Reihe abonnieren und später nur einzelne passende Termine buchen ist ausdrücklich vorgesehen.

## Formulare, Umfragen und Unterlagen

Vor der Platzvergabe kann ein Pflichtformular ausgefüllt werden müssen. Optional genügt dessen Abschluss einmal pro Reihe statt erneut pro Einzelbuchung. Zusätzlich sind Aktivitäten **vorher**, **live** und **nachher** möglich, gemeinsam für die Reihe oder einem einzelnen Termin zugeordnet. Weitere Pflichtformulare sind nur vor der Veranstaltung zulässig und werden vor den ersten Anmeldungen eingerichtet. Formulare nutzen den vorhandenen Renderer, seine Validierung und Benachrichtigungen; als Haupt-Anmeldeformular werden gewöhnliche, nicht anonyme Formulare ohne Zahlungsfunktion angeboten. Vor- und Nachfragen können dagegen anonym sein; ihr Abschluss wird für die Teilnahme vermerkt, ohne die Person in der anonymen Antwort einzutragen.

Abstimmungen und Liveumfragen verwenden die bestehenden Module und deren Freigaben. Freigabezeiten legen fest, wann ein persönlicher Schnelllink sichtbar und nutzbar wird.

Unterlagen können aus einer berechtigten Sammelmappe übernommen oder einzeln als Datei beziehungsweise Markdowntext erstellt werden. Die Vorlage wird kopiert; spätere Änderungen an der Mappe verändern das Seminar nicht. Rechtstexte, DMS-Dokumente und Formulare bleiben Portalverweise und behalten ihre Leserechte. **Ein Gastlink macht interne Portalobjekte nicht öffentlich.** Für externe Teilnehmer bei Bedarf ausdrücklich geeignete, freigegebene Dateien bereitstellen.

Jede Unterlage kann sofort, zu einem geplanten Zeitpunkt oder erst nach manueller Veröffentlichung erscheinen. Reihenfolge, Titel und Zuordnung zur Reihe oder zu einem Einzeltermin lassen sich pro Dokument bearbeiten. PDF-Dateien und Rechtstexte haben eine Vorschau. Unterlagen sind für bestätigte Teilnehmer des zugehörigen Umfangs zugänglich. Der Zeitraum nach dem letzten gebuchten Termin wird pro Veranstaltung eingestellt; **0 Tage bedeutet unbegrenzt**. Dateiuploads sind auf 20 MB pro Datei und die unterstützten Dokument-/Bildformate begrenzt.

## Durchführung und Nachbereitung

Die Teilnehmerverwaltung zeigt Zulassungsstand und Anwesenheit. CSV unterstützt die weitere Bearbeitung; die PDF-Liste bietet Platz für Unterschriften. Ein Terminfilter ermöglicht Listen für einzelne Termine. Teilnehmer sehen ihre eigenen Termine und können sie als ICS-Kalenderdatei herunterladen.

Ein persönlicher QR-Check-in führt zur Bestätigungsansicht für berechtigte Betreuung. **Das Öffnen oder Scannen bestätigt keine Anwesenheit automatisch.** Erst die ausdrückliche Aktion erfasst sie; frühestens 30 Minuten vor Terminbeginn. Der Check-in-Code enthält keinen persönlichen Gast-Zugangstoken.

Teilnahmebescheinigungen sind optional. Als Umfang stehen **wie gebucht**, **je Einzeltermin**, **gesamte Reihe** oder **Einzeltermine und gesamte Reihe** zur Wahl. Nach Ende der maßgeblichen Termine und ausreichender erfasster Anwesenheit kann die Betreuung eine PDF-Bescheinigung ausstellen; optional übernimmt dies der Worker automatisch. Eine Reihenbescheinigung berücksichtigt die gesamte veröffentlichte Reihe, auch wenn eine Person einzeln gebucht hat. Die Mindestanwesenheit wird nach Termindauer berechnet; Standard **80 %**. Aussteller, optionale Dozentennennung sowie Logo und Unterschriftsabbildung sind einstellbar. Die ausgestellten Angaben werden mit Bescheinigungskennung als unveränderlicher Stand gespeichert. Korrekturen erfolgen durch Widerruf und erneutes Ausstellen. Vor dem Zurücknehmen einer bescheinigten Anwesenheit muss die aktive Bescheinigung widerrufen werden.

Erinnerungen werden standardmäßig **7 und 1 Tag** vor einem Termin eingeplant. Die Tage sind konfigurierbar; ein leeres Feld schaltet Erinnerungen aus. Bei später Anmeldung wird die nächste passende Erinnerung verwendet. Änderungen und Absagen verwenden denselben zentralen Versandweg. Ein Versandauftrag ist kein Nachweis, dass eine E-Mail gelesen wurde.

Benachrichtigungen lassen sich getrennt für Anmeldung und Entscheidung, Änderungen und Absagen, Erinnerungen, neue Unterlagen, Bescheinigungen, Betreuung und Abonnenten einstellen. Optional erhält die Betreuung jede Anmeldung; Entscheidungen über manuelle Zulassung bleiben bei der Planung. Vor einem Termin kann die zuständige Betreuung einen Link zur Teilnehmerübersicht erhalten. Externe Dozenten ohne Portalzugang erhalten dadurch keine Verwaltungsrechte.

## Betrieb und Prüfung

Die zusätzlichen Tabellen werden beim normalen Portalstart angelegt. Vor einem Update wie üblich Datenbank und Datenverzeichnis sichern. Seminar-Uploads liegen im bestehenden Datenverzeichnis unter `seminars`; sie gehören in dieselbe Sicherung wie Datenbank und andere Portaldateien. Bestehende Formulare, Raumfreigaben und Rechte werden weiterverwendet, nicht durch die Seminarrechte ersetzt.

Automatisierte Prüfungen decken Platzvergabe, Zugriffsgrenzen, Pflichtformulare, Wartelisten, Kalender, Check-in, Bescheinigungen, Abonnements und Terminplanung ab. Ein echter Mailversand oder die Erreichbarkeit eines externen Konferenzanbieters wird dadurch nicht zugesichert; diese Betriebsfunktionen mit der eigenen Konfiguration prüfen.
