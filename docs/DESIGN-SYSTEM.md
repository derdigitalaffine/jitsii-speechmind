# Gemeinsame Oberflächen

Das Designsystem vereinheitlicht wiederkehrende Aufgaben. Fachnavigation, Rechte, Archivregeln und Spezialansichten bleiben im jeweiligen Modul. DMS, Ressourcen und Umläufe verwenden die Komponenten produktiv; weitere Module folgen bei normalen Änderungen.

## Seitenmuster

**Liste:** Titel und kurze Beschreibung; eine sichtbare Hauptaktion rechts bzw. auf Mobilgeräten über die volle Breite; seltene Aktionen unter „Mehr“. Suche/Filter sind einklappbar, aktive Filter und Ergebniszahl bleiben außerhalb sichtbar. Leere Ergebnisse bieten eine sinnvolle Folgeaktion. Ressourcen suchen in beiden Ansichten gleich, ausschließlich in bereits zugänglichen Objekten; Ansichtwechsel erhalten die Suche. DMS-Filterreset erhält Ordner und Archivansicht.

**Detail:** Zurückpfad, Titel, verständlicher Status, wichtigste Metadaten (`detail_meta`), eine Hauptaktion und weitere Aktionen unter „Mehr“. Fachliche Abschnitte und Verlauf stehen darunter.

**Editor:** Titel und Entwurfsstatus; Speichern und danach Vorschau/Veröffentlichen/Abbrechen konsistent anordnen. Vorhandene Dirty-State-Warnung erst nach echten Änderungen; erfolgreiches Absenden darf keine Verlassen-Warnung auslösen. Fehler erhalten Eingaben und verweisen auf das betroffene Feld. Die drei Piloten betreffen Listen, keine vollständige Migration aller Editorseiten.

## Komponenten

Import: `{% import '_macros.html' as m with context %}`. Beschriftungen werden automatisch escaped; URLs nur aus bekannten Portalpfaden erstellen. `caller` für Komponenten enthält vom Template kontrolliertes HTML.

| Makro | Verwendung |
|---|---|
| `page_header(title, lede, primary_url, primary_label, primary_icon)` | Titel/Hauptaktion; optionaler call-Block für weitere Aktionen |
| `action_menu(label='Mehr')` | Native Details/Summary; call-Block für seltene Aktionen, ohne extra JavaScript bedienbar |
| `filter_bar(label, expanded)` | Einklappbare Filterzone; call-Block enthält das GET-Formular |
| `active_filter(label, value)` | Aktiver Filter, außerhalb der einklappbaren Zone |
| `result_summary(count, label)` | Ergebniszahl mit Statussemantik |
| `status_chip(label, tone, icon)` | `neutral`, `info`, `success`, `warning`, `error`; immer Text plus Icon |
| `empty_state(title, description, action_url, action_label, icon)` | Leerzustand und berechtigte Folgeaktion |
| `detail_meta(items)` | Semantische Beschreibungsliste aus (Label, Wert)-Paaren |

Farben in `design-system.css` sind semantisch und unabhängig von frei einstellbaren Brandingfarben. Helle und dunkle Varianten erfüllen für Chiptext mindestens WCAG AA (4,5:1). Tastaturfokus ist sichtbar; native Details und echte Buttons/Links erhalten Tastaturverhalten. Lange Titel umbrechen.

Tabellen der Ressourcenliste verwenden `ds-mobile-table`: alle Zellen besitzen `data-label`, mobil erscheinen beschriftete Zeilen statt versteckter Spalten. Für diese Tabellen ist DataTables Responsive deaktiviert; Sortierung und Seitennavigation bleiben erhalten. Weitere Tabellen bleiben unverändert.

## Referenz und Prüfung

[Komponentenreferenz](design-system-reference.html) lokal im Browser öffnen. Sie rendert die tatsächlichen Jinja-Makros mit hellen und dunklen Zuständen: Normal, Leer, Laden, Fehler, Disabled, Felder, Tabelle, Karte und nativer Dialog. Sie ist bewusst kein neuer Eintrag im Benutzermenü. Bei Komponentenänderungen im Repositorywurzelverzeichnis `python scripts/generate-design-reference.py` ausführen (Jinja2 ist erforderlich).

Automatische Prüfungen testen Kontrast der semantischen Tokenpaare, echtes Makro-Markup, mobil beschriftete Tabellenzellen, beide Ressourcenansichten mit Suche und Rechtefilterung. Eine vollständige manuelle Tastatur-/Browserprüfung bleibt zusätzlich sinnvoll; keine Zertifizierung der gesamten Plattform.
