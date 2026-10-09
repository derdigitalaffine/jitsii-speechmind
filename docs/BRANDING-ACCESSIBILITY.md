# Design & Branding: Kontrast und Bedienbarkeit

Unter **Administration → Design & Branding** zeigt die Qualitätskontrolle die tatsächlich erzeugten Farben getrennt für Hell und Dunkel. Die Vorschau bleibt vom Design der geöffneten Adminseite isoliert. Erst **Design speichern** übernimmt die Einstellungen.

## Geprüfte Farben

Die zentrale Palette in `portal/app/branding.py` versorgt sowohl die Portal-CSS als auch die Liveprüfung. Die Prüfung verwendet die relative sRGB-Luminanz und das Verhältnis `(hellere Luminanz + 0,05) / (dunklere Luminanz + 0,05)`.

| Element | Geprüfter Zustand | Mindestkontrast |
| --- | --- | --- |
| Primärbutton, Badge und primäre Auswahl | Normale Schrift, Hover und gedrückter Button mit automatischer Schwarz-/Weißwahl | 4,5:1 |
| Link | Normal und Hover auf dem jeweiligen Seitenhintergrund | 4,5:1 |
| Aktive Seitennavigation | Schrift auf dem tatsächlichen gemischten Auswahlhintergrund | 4,5:1 |
| Kopfzeile | Schrift und Produktbezeichnung inklusive 75 % Deckkraft | 4,5:1 |
| Fokus | Seitenhintergrund, helle/dunkle Nebenflächen und eigener Kopfzeilenhintergrund | 3:1 |
| Checkbox, Radio, Schalter | SVG-Markierung auf der Hauptfarbe | 3:1 |

Automatische Schwarz-/Weißschrift wird nach relativer Luminanz gewählt. Badges behalten auch im Dunkelmodus den geprüften Primärhintergrund. Fokusmarkierungen sind deckend, 3 px breit und haben Abstand; eine eigene Kopfzeilenfarbe verhindert einen unsichtbaren Ring auf einer gleichfarbigen Kopfleiste.

## Warnungen und Speichern

Die Angaben zeigen Verhältnis, betroffenes Element und Bewertung: **gut – AA für normalen Text**, **nur große Schrift** oder **zu geringer Kontrast**. Fokus/Markierungen haben eine eigene Bewertung. Wenn eine nahe Farbe alle gemessenen Kombinationen verbessert und deren Mindestwerte erfüllt, lässt sie sich per Knopfdruck übernehmen; andernfalls wird kein pauschales Farbversprechen angezeigt.

Ein problematisches eigenes Design bleibt zulässig. Vor dem Speichern muss die ausdrücklich beschriftete Bestätigung angekreuzt werden. Änderungen der Hauptfarbe oder Kopfleiste löschen diese Bestätigung. Der Server prüft erneut und akzeptiert sie nur für die eingereichte Kombination; ein manipuliertes oder veraltetes Formular umgeht die Prüfung nicht. Bei deaktiviertem eigenem Design wirken die problematischen Farben nicht, die Text-/Fotoeinstellungen lassen sich weiterhin speichern.

Die Clientprüfung verhindert bei bekannten aktuellen Warnungen unnötiges Absenden und setzt den Fokus auf die Bestätigung. Falls der Server noch unbestätigte Warnungen findet, zeigt er alle Text-, Auswahl- und Schalterwerte erneut an, ohne Einstellungen oder vorhandene Bilder zu verändern. Eine ausgewählte Datei kann der Browser bei diesem erneuten Anzeigen nicht erhalten; die Seite erklärt ausdrücklich, dass sie nochmals ausgewählt werden muss.

## Vorschau und Tests

Hell und Dunkel lassen sich unabhängig von der gespeicherten Gerätepräferenz vergleichen. Die Vorschau enthält Kopfzeile/Logo, aktive Navigation, einen Link im Text, Primärbutton mit Fokusmarkierung, Auswahlbadge, ein beschriftetes fehlerhaftes Eingabefeld und eine Checkbox. Mit Tab können echte Fokuszustände einschließlich der Kopfzeile geprüft werden. Organisations- und Produkttexte werden vor dem Einbetten maskiert, die iframe-Vorschau erlaubt keine Skripte.

`test_branding_accessibility.py` prüft konkrete Farbverhältnisse, Extremfarben, Hell-/Dunkelzustände, serverseitige Warnungsbestätigung und echte gerenderte Login-, Dashboard-, öffentliche Formular- und Antragsdetailseiten. Die Smokes prüfen Inhalts-Sprungziele, zugängliche Feldnamen und die ausgegebene Fokusregel einschließlich Navigation für mobile/desktop Controls. Die Antrags-Mitteilung hat dafür einen eigenen zugänglichen Namen; der Login hat einen Skip-Link zum Hauptinhalt.

`test_branding_editor_client.js` führt die tatsächliche Editor-JavaScriptdatei aus und prüft maskierte Vorschauinhalte, Schemawechsel, ignorierte veraltete Liveantworten, gelöschte Bestätigung bei Änderungen und den Submit-Guard. Die bestehenden Foto-/Mailtests sichern benachbarte Designfunktionen ab.

Diese gezielten Prüfungen ersetzen weder ein vollständiges WCAG-Audit noch visuelle und assistive Browserprüfungen. Semantische Fremdkomponenten, Bilder, unbekannte Hintergrundflächen und frei eingegebene Inhalte werden nicht vollständig bewertet.
