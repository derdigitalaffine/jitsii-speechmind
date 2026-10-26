# UX-Review: Aufgaben & Zusammenarbeit

- **Hauptrolle / Ziel:** Beschäftigte erfassen, bearbeiten und delegieren Aufgaben; erledigbare Arbeit steht vor Verwaltung.
- **Hauptaktion:** Im Arbeitsplatz „Aufgabe erfassen“, am Detail der nächste zulässige Arbeitsschritt. Weitere Änderungen im aufklappbaren Bereich.
- **Normalfall:** Kurztext → sichtbare Vorschau mit korrigierbarer Person/Frist → Anlegen → Bearbeiten → Erledigen. Keine Modalfolge.
- **Zustände:** Leere Liste mit Handlungsangebot; Filter ohne Treffer mit Zurücksetzen; Formfehler im selben Formular mit erhaltenen Werten; unzugängliche Objekte ohne Metadaten; bestätigte Änderungen mit Rückmeldung.
- **Fehler / Wiederaufnahme:** Mehrdeutiger Name verlangt Auswahl; ungültiges Datum bleibt sichtbar; konkurrierende Bearbeitung verlangt Neuladen; Uploadfehler erklärt erneute Dateiauswahl; Review-Rückgabe ohne Begründung bleibt im Formular.
- **Mobile:** Einspaltige Erfassung und Detailkarten, umbrechende Aktionen, keine Tabelle als einziger Zugang. Listenansicht bleibt Standard, Board ist optional.
- **Tastatur:** Native Formulare/Details, beschriftete Felder, sichtbarer vorhandener Fokus, keine nur per Drag & Drop ausführbare Aktion. Vorschau per Enter; Speichern erst in der sichtbaren Bestätigung.
- **Verborgen:** Auditdetails und seltene Optionen unter Details; Fachquelle sekundär. Status immer als Text, nicht allein Farbe.
- **Kontext:** GET-Filter und Ansichten im Rücksprung erhalten; Eingaben bei Validierungsfehlern serverseitig wieder anzeigen.
- **Komponenten:** page_header, filter_bar, status_chip, detail_meta und empty_state aus dem TAKT-Designsystem; vorhandene Mailqueue und CSRF-Prüfung.
- **Sicherheitsgrenzen:** Eine hauptverantwortliche Person; Beteiligte sehen nur explizite Aufgaben; Quellenrechte bleiben eigenständig. Änderungen und Review prüfen serverseitig Rolle und Version.

Automatisierte Tests prüfen Rechte, Status, Fehlererhalt, Darstellung und Tastatur-Markup. Zusätzlich prüft der CI-Job `tasks-browser` echte Bedienabläufe in Chromium auf Desktop- und Mobilbreiten sowie im hellen und dunklen Design. Eine manuelle Prüfung mit realen Screenreadern bleibt eine eigene Abnahme.

## Ergebnis der Umsetzung

Die Bestätigung der Schnellerfassung bleibt im gemeinsamen Arbeitsplatz. Archiv und abgeschlossene Delegationen sind wieder auffindbar. Liste, Board, Wochen-/Monatskalender und Zeitachse verwenden dieselben Berechtigungen und Filter. Statusformulare und native Details bieten Tastaturalternativen zu Drag & Drop.

Server-/Markup-, JavaScript- und Chromium-Prüfungen sind automatisiert. Der Browserjob umfasst die Anlage samt Dateien/Checkliste, Rücksprung, Download, Tastatur, Board/Kalender und Schnellfeld. Screenshots dokumentieren mobile und Desktopbreiten sowie die Farbmodi. Eine vollständige manuelle Barrierefreiheits- oder Screenreaderprüfung wird damit nicht behauptet.


## Formular und visuelle Angleichung

Die Erfassung bietet einen sichtbaren Formulareinstieg und das unverändert verfügbare Schnellfeld. Im Formular stehen Beschreibung, Person und Frist sowie optionale Checkliste/Dateien vor dem ersten Speichern bereit. Beide Wege kehren zur bisherigen Übersicht zurück. Das Speichern der Aufgabe einschließlich Checkliste und Dateien ist transaktional; Fehlermeldungen erhalten Textwerte und weisen auf die erneute Dateiauswahl hin.

Schaltflächen verwenden die gemeinsamen Bootstrap-/TAKT-Größen und die Hauptaktionsklasse `ds-primary`. Desktop-Schaltflächen werden nicht mehr pauschal auf Touch-Höhe vergrößert; auf kleinen bzw. mit Touch bedienten Geräten bleiben mindestens 44 Pixel hohe Ziele erhalten. Perspektiven verwenden Tabs; Ansichten und Kalendersteuerung verwenden zusammenhängende Schaltflächengruppen wie die Ressourcenübersicht. Zeilenaktionen im Aufgabenarbeitsplatz sind sekundär; die bestehende Dashboard-Darstellung bleibt unverändert. Farbcodierung, Fokus und dunkles Design verwenden vorhandene semantische Variablen.
