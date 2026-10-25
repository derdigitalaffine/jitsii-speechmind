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

Automatisierte Tests prüfen Rechte, Status, Fehlererhalt, Darstellung und Tastatur-Markup. Eine manuelle Prüfung mit realen Screenreadern ist gesondert zu benennen.

## Ergebnis der Umsetzung

Die Bestätigung der Schnellerfassung bleibt im gemeinsamen Arbeitsplatz. Archiv und abgeschlossene Delegationen sind wieder auffindbar. Liste, Board, Wochen-/Monatskalender und Zeitachse verwenden dieselben Berechtigungen und Filter. Statusformulare und native Details bieten Tastaturalternativen zu Drag & Drop.

Server-/Markup- und JavaScript-Prüfungen sind automatisiert. Die tatsächliche Browser-, Tastatur- und Screenreaderabnahme ist noch offen; die bereitstehende Chromium-Laufzeit konnte in der Arbeitsumgebung nicht gestartet werden. Dies ist keine abgeschlossene manuelle Barrierefreiheitsprüfung.
