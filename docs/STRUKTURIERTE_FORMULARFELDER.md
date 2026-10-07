# Wiederverwendbare Formularfelder

Die Typen Zeitraum, wiederholbare Tabelle, Berechnung, ausdrückliche Bestätigung und gezeichnete Unterschrift stehen in Formularen und in Prozess-Nachforderungen zur Verfügung. Die gemeinsame Feldvorlage wird auch für eingebettete Formulare verwendet. Tabellen und Erklärungen sind im Baukasten und im kompakten Nachforderungseditor bearbeitbar.

## Berechnung

Summe, Differenz, Produkt oder Tabellensumme werden auf dem Server mit Decimal geprüft. Übermittelte Ergebnisse werden ignoriert. Die Vorschau im Browser dient nur der Orientierung. Beträge werden mit ROUND_HALF_UP auf Cent gerundet. Ungültige Quellen, Zyklen, nicht endliche Zahlen und zu große Ergebnisse verhindern die Abgabe.

## Interne Formulare

Die Einstellung „Nur berechtigte angemeldete Beschäftigte“ erfordert das Benutzerrecht `internal_forms`. Interne Formulare sind nicht anonym. Statusseiten, Nachforderungen, Dokumente und Download-Bündel sind zusätzlich auf die einreichende Person oder berechtigte Bearbeitende beschränkt. Ein weitergegebener Vorgangslink reicht nicht aus.

## Erklärungen und Unterschriften

Bestätigungsfelder speichern den ausdrücklich bestätigten Wortlaut und Zeitpunkt. Sie werden beim Wiederherstellen eines Entwurfs nicht automatisch angekreuzt. Dienstreisevorlagen verwenden diese Bestätigung; eine gezeichnete Unterschrift wird dort nicht benötigt.

Das allgemeine Unterschriftsfeld speichert begrenzte normalisierte Zeichenpunkte, den Namen, Wortlaut und Zeitpunkt. Es akzeptiert keine SVG-/HTML-Dateien und ist keine qualifizierte elektronische Signatur. Maus, Stift, Touch und Tastatur werden unterstützt. Export und Textdarstellung enthalten die Bestätigung; die vollständigen Punkte bleiben im JSON erhalten.

## Planung und spätere Angaben

Ein Nachforderungsfeld kann `prefill_from` auf eine frühere Frage-ID setzen. Bei Erstellung der Nachforderung wird die damalige Antwort als unabhängiger Vorschlag eingefroren. Neue IDs bewahren die ursprüngliche Planung; erneute Erklärungen, Dateien, Unterschriften und Berechnungsergebnisse werden nicht vorausgefüllt.

Die Dienstreisevorlage baut auf diesen allgemeinen Funktionen auf. Die Grundlage kombiniert die getrennten PRs für Benachrichtigungen und Formularbedienung im Branch `work/form-foundation`; keine dieser Änderungen ist damit bereits veröffentlicht oder deployt.
