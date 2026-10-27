# Umfragen & Abstimmungen

Im Hauptmenü: **Kommunikation → Umfragen & Abstimmungen**. Hier finden Sie Live-Umfragen, Abstimmungen und Terminumfragen. **Formulare bleiben eigenständig** unter Formulare & Vorgänge.

## Passenden Ablauf wählen

**Neu erstellen** öffnet drei sichtbare Auswahlkarten:

| Auswahl | Geeignet für | Teilnahme |
|---|---|---|
| Live-Umfrage | Veranstaltung, Feedback, Quiz, Wortwolke, Pinnwand und Q&A | QR-Code oder Link, ohne Anmeldung; je Gerät und Frage eine änderbare Antwort; bei offenen Beiträgen mehrere Beiträge nach Einstellung |
| Abstimmung | Einfache Entscheidungen bis zur förmlichen Wahl | Persönliche Einladungen, öffentlicher Link mit E-Mail-Bestätigung oder Einmalcodes |
| Terminumfrage | Gemeinsamen Termin finden | Öffentlicher Link oder persönliche Einladung; Ja / Wenn nötig / Nein |

Live öffnet direkt die erste Frage. Ein Titel muss nicht vorab eingegeben werden. Der Entwurf heißt zunächst „Live-Umfrage“; Titel und Begrüßung können unter Einstellungen geändert werden. **Anlegen startet keine Teilnahme.**

Eine neue unkomplizierte Abstimmung verwendet anonym gespeicherte Stimmen und sofort sichtbare Ergebnisse. Der öffentliche Zugang verlangt eine bestätigte E-Mail-Adresse; für spontane Teilnahme ohne E-Mail ist die Live-Umfrage geeignet. **Teilnahme & Wahlregeln** enthält weiterhin alle Einstellungen für Einladungen, Geheimhaltung, Codes, Ergebnisfreigabe und Änderbarkeit. Bestehende Abstimmungen behalten ihre Regeln.

## Gemeinsame Orientierung

| Bereich | Aufgabe |
|---|---|
| Fragen | Fragen und Antwortmöglichkeiten vorbereiten; bei Terminumfragen die Vorschläge |
| Teilnahme | Link und QR-Code weitergeben; bei Abstimmungen und Terminumfragen einladen und Freigaben verwalten |
| Durchführung | Teilnahme ausdrücklich starten, anhalten oder beenden; live moderieren |
| Ergebnisse | Antworten auswerten und exportieren; bei Terminumfragen den Termin festlegen |
| Einstellungen | Regeln, Titel und Ablauf; Aufbewahrung und Archivierung |

Die Funktionen unterscheiden sich je nach Anlass, die Orientierung bleibt gleich. Nur berechtigte Aktionen erscheinen. Geteilte Lesezugänge führen direkt zu den Ergebnissen. Bestehende `/votes`, `/polls`, öffentliche Links und Favoriten bleiben nutzbar; die bisherigen Übersichten verwenden den gemeinsamen Arbeitsbereich.

## Live vorbereiten und durchführen

1. **Neu erstellen → Live-Umfrage vorbereiten**.
2. Frageart wählen, Frage und gegebenenfalls Antwortmöglichkeiten eintragen. **Frage hinzufügen** speichert den Entwurf. Bei Fehlern bleiben die Angaben erhalten.
3. Unter **Einstellungen** bei Bedarf Titel, Begrüßung und Ablauf anpassen. Standard: **Moderiert**, Frage für Frage. **Frei** stellt alle Fragen gleichzeitig bereit.
4. Unter **Teilnahme** Link kopieren oder QR-Code herunterladen. Der Link kann vorab verteilt werden; Antworten sind erst nach dem Start möglich.
5. **Durchführung → Teilnahme starten**. Die aktuelle Frage, Antworten und **Nächste Frage** stehen im Mittelpunkt. Fragenübersicht ermöglicht gezielte Sprünge und zeigt Beiträge, die auf Freigabe warten.
6. **Präsentieren** öffnet die Beamer-Ansicht in einem separaten Tab. Änderungen der aktuellen Frage werden auch in der Moderation berücksichtigt. Der letzte Schritt hat keine weitere Folgefrage.
7. Wortwolken und offene Beiträge lassen sich moderieren. Bei neu eingegangenen Beiträgen aktualisiert **Beiträge aktualisieren** die bearbeitbare Liste. Quiz bietet weiterhin Lösungen, Freigabe, freiwillige Rangliste und Timer; beim Wechsel zur nächsten Frage gelten die bisherigen Quiz-Sperrregeln.
8. **Teilnahme beenden** erhält alle Antworten und führt zu den Ergebnissen. Erneutes Öffnen einer Live-Umfrage bleibt ausdrücklich möglich.

Die Live-Vorschau lädt den aktuellen Stand automatisch. Bei Verbindungsfehlern erscheint ein Hinweis; ein neuer Versuch erfolgt automatisch. CSV-Exporte und Wortwolken-PNG sind unter Ergebnisse verfügbar. Neue Fragen, Reihenfolge, Löschen und bewusstes Zurücksetzen liegen in der Vorbereitung, damit Routine-Steuerung und Datenpflege getrennt bleiben.

## Wiederfinden und aufbewahren

Suche, Art und **Anzeigen** (meine/geteilte, von mir erstellt, mit mir geteilt; für Admins zusätzlich alle im Portal) lassen sich kombinieren. Der Wechsel zwischen **Aktuell**, **Archiv** und **Papierkorb** erhält die Filter. Antwortzähler und Suchergebnisse stammen ausschließlich aus zugänglichen Objekten.

Ungenutzte Entwürfe kommen für 30 Tage in den Papierkorb. Verwendete Umfragen werden geschlossen und archiviert. Ergebnisse, Rechte und öffentliche Datenmodelle bleiben erhalten. Wiederherstellen startet keine Teilnahme. Festgeschriebene förmliche Abstimmungen werden nicht erneut geöffnet.

## Technische Prüfung

`python -m pytest -q tests` im Verzeichnis `portal` prüft die bestehenden Funktionen und den neuen Arbeitsbereich einschließlich Rechten, Modulschaltern, Filterkombinationen, Formularabgrenzung, direkten Live-Entwürfen, Fehlererhalt, Rücksprungzielen und Archiven.

Der Chromium-Job `surveys-browser` prüft Anlage ohne vorgeschalteten Titel, Fragefehler und Korrektur, Teilnahme mit einem zweiten Browserkontext, Moderation per Tastatur, separate Präsentation, Exporte, unkomplizierte Abstimmungen und mobile Ansichten in Hell/Dunkel. Screenshots und Serverlog stehen sieben Tage im CI-Artefakt `surveys-browser`. Der bestehende Aufgaben-Browserjob prüft weiterhin den gemeinsamen Seitenkopf. Eine manuelle Screenreader-Abnahme ist zusätzlich erforderlich.
