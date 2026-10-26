# Aufgaben & Zusammenarbeit

## Einstieg

Die Administration schaltet **Aufgaben & Zusammenarbeit** unter **Module** ein und vergibt **Aufgaben erstellen** bzw. **Aufgaben verwalten**. Das neue Modul ist bei bestehenden Installationen zunächst ausgeschaltet. Die vorhandenen Aufgaben aus Anträgen, Umläufen und Ressourcen bleiben davon unabhängig verfügbar.

**Meine Aufgaben** bleibt der gemeinsame Arbeitsplatz. Frei erstellte Aufgaben und Fachaufgaben werden hier zusammen angezeigt. Fachaufgaben bleiben in ihren ursprünglichen Modulen; ihr Zustand wird nicht in eine zweite Tabelle kopiert.

## Schnell erfassen

Im Arbeitsplatz einen Satz eingeben, z. B.:

`Präsentation vorbereiten bis nächsten Freitag 14 Uhr @Anna #Marketing !hoch`

Nach Enter erscheinen Titel, Person, Datum, Uhrzeit, Tags und Priorität direkt in einer korrigierbaren Vorschau. Erst **Aufgabe anlegen** speichert. Mehrdeutige oder unbekannte Namen verlangen eine ausdrückliche Auswahl; die ursprüngliche Eingabe bleibt erhalten. Mehrteilige Namen können als `@"Anna Schneider"` geschrieben werden.

Die Erkennung versteht heute/morgen/übermorgen, Wochentage, `31.10.`/`31.10.2026`, `14 Uhr`/`14:30`, `#Tag` und `!dringend`, `!hoch`, `!mittel`, `!niedrig`. Ein Datum ohne Jahr bezeichnet den nächsten passenden Termin. Ungültige Werte werden nicht still korrigiert.

## Mit Formular anlegen

Neben dem Schnellfeld ist **Mit Formular anlegen** als sichtbarer Einstieg in der Kopfzeile erreichbar. Das vollständige Formular öffnet eine eigene Seite, bleibt mobil einspaltig bedienbar und bietet direkt:

- Titel und Beschreibung
- genau eine verantwortliche Person, zunächst die eigene Person
- Fälligkeitsdatum und optionale Uhrzeit
- eine Checkliste mit einem Punkt pro Zeile, in der eingegebenen Reihenfolge
- mehrere Dateien vor dem ersten Speichern

Priorität, Tags, Freigabe, Start und Gruppenkontext liegen unter **Weitere Angaben**. Checkliste und Dateien bleiben optional. Es gelten höchstens 50 neue Checklistenpunkte mit je 500 Zeichen und die vorhandenen Dateigrenzen (10 Dateien pro Upload, je 20 MB, insgesamt 100 MB).

**Aufgabe anlegen** speichert Aufgabe, Checkliste und Dateien gemeinsam. Bei einem Fehler wird keine teilweise angelegte Aufgabe zurückgelassen. Texte und die Rückkehr zur bisherigen Ansicht bleiben erhalten; Dateien müssen ausdrücklich erneut ausgewählt werden. Die Dateiauswahl zeigt Namen und meldet zu große Mengen bereits vor dem Absenden; die gleichen Grenzen gelten serverseitig.

Nach erfolgreicher Anlage führen sowohl Formular als auch Schnellfeld zurück in die bisherige Aufgabenübersicht einschließlich Filter und Ansicht. Dort bestätigt eine Meldung den gespeicherten Titel. Beim Bearbeiten vorhandener Aufgaben bleibt der Rücksprung zur Detailansicht bestehen.

## Verantwortung und Abschluss

Jede Aufgabe hat genau eine verantwortliche Person: intern oder extern. Eine Gruppe kann den Kontext beschreiben, vergibt aber keine Sichtrechte.

| Rolle | Zugriff |
| --- | --- |
| Erstellende Person | Aufgabe sehen, Planung und Verantwortung ändern, mitarbeiten, freigeben, stornieren, archivieren |
| Verantwortliche interne Person | Aufgabe sehen, beginnen und abschließen/einreichen, kommentieren, Checkliste und Dateien bearbeiten |
| Explizite Mitwirkende | Aufgabe sehen, kommentieren, Checkliste bearbeiten und Dateien hinzufügen; kein Statuswechsel und keine Freigabe |
| Aufgabenverwaltung / Administration | Alle nativen Aufgaben sehen und verwalten; Quellenrechte bleiben eigenständig |
| Externe Person | Ausschließlich die über ihren gültigen persönlichen Link freigegebene Aufgabe und Inhalte |

**Loslegen** setzt die Aufgabe auf **In Bearbeitung**. **Erledigen** schließt sie ab. Wenn eine Freigabe verlangt wird, reicht die verantwortliche Person sie stattdessen ein. Erstellende Person bzw. Aufgabenverwaltung können freigeben oder mit verpflichtendem Kommentar zurückgeben. Offene Checklistenpunkte und unerledigte Vorgänger verhindern einen Abschluss.

**Geöffnet** bedeutet nur, dass die verantwortliche Person die Detailseite aufgerufen hat. Es ist keine Lese- oder Verständnisbestätigung. Es werden keine Tracking-Pixel verwendet.

Abgeschlossene/stornierte Aufgaben lassen sich archivieren und im **Archiv** wiederfinden. Die Perspektive **Delegiert von mir** enthält auch erledigte/stornierte Arbeit; die Aufgabenverwaltung erhält zusätzlich **Alle Aufgaben verwalten**.

## Zusammenarbeit, Dateien und Quellen

Beschreibungen und Kommentare unterstützen Markdown ohne ungefiltertes HTML. **Person erwähnen** fügt eine eindeutig bezeichnete beteiligte Person in den Kommentar ein. Neue Erwähnungen verleihen keine Sichtrechte; eine neue Person muss vorher ausdrücklich als Mitwirkende hinzugefügt werden. Bearbeitete bzw. entfernte Kommentare bleiben als solche erkennbar. Status-, Frist-, Prioritäts-, Verantwortungs- und Zusammenarbeitsschritte erscheinen im Aktivitätsverlauf.

Anhänge liegen außerhalb statischer Webpfade. Grenzen: 20 MB pro Datei, 100 MB pro Aufgabe, bis zu zehn Dateien je Upload. Dateinamen werden bereinigt; Dateipfade bestehen aus zufälligen internen Schlüsseln. Nur anhand ihrer Bytes überprüfte Rasterbilder werden als Vorschau ausgeliefert. Andere Formate werden mit `application/octet-stream`, `nosniff` und restriktiver CSP heruntergeladen.

Eine DMS-Datei kann über ihre Datei-ID als Referenz verknüpft werden. Dabei werden keine Dateiinhalte kopiert. Der Link prüft beim Öffnen erneut die aktuelle DMS-Berechtigung. Ohne diese Berechtigung werden weder ursprünglicher Dateiname noch Inhalt offengelegt.

Aus einem DMS-Eintrag kann eine zusätzliche freie Aufgabe angelegt werden. Erkannte SpeechMind-Aufgaben einer Aufzeichnung können einzeln oder gemeinsam geprüft und übernommen werden. Person und Frist werden vor Anlage bestätigt. Stabile Quellschlüssel verhindern doppelte Übernahmen; `summary_json` bleibt unverändert. Die Aufgabe führt über einen berechtigungsgeprüften Link zur Quelle zurück. Gelöschte, archivierte oder nicht mehr zugängliche Quellen erscheinen als nicht verfügbar.

Das interne Interface `task_sources.create_from_source(...)` nimmt explizite Aufgabenfelder, Quelltyp, stabile Objekt-ID und optional einen Idempotenzschlüssel entgegen. Neue Quellen benötigen einen eigenen Adapter mit aktueller Fachberechtigungsprüfung. Bestehende Workflow-/Umlauf-/Ressourcenaufgaben werden darüber nicht kopiert.

## Ansichten und Abhängigkeiten

Liste, Board, Monats-/Wochenkalender und einfache Zeitachse verwenden denselben gefilterten Bestand. Filter und Rücksprünge bleiben erhalten. Sortierung ist nach Frist, Priorität, Verantwortlichkeit und Status möglich. Aufgaben ohne Frist stehen im Kalender separat.

Im Board sind normale Statusformulare vollständig mit Tastatur bedienbar; Drag & Drop ist eine zusätzliche Bedienmöglichkeit. Kalender-Drag & Drop ändert nur die Fälligkeit und verwendet dieselbe Planungserlaubnis und Versionsprüfung wie das Bearbeitungsformular. Fachaufgaben lassen sich nicht frei verschieben. Mobil werden Boardspalten untereinander und Kalendertage mit Aufgaben als Liste angezeigt.

Native Aufgaben können unter **Abhängigkeiten** einen Vorgänger erhalten. Selbstbezüge und Zyklen werden abgelehnt. Blockierte Aufgaben bleiben unter **Wartet auf andere** sichtbar. Die Zeitachse zeigt Start, Fälligkeit und zugängliche Vorgänger. Abschlüsse heben Blockierungen nachvollziehbar auf; das Lösen einer Abhängigkeit erfordert Planungsrechte und wird protokolliert.

## Wiederholungen und Erinnerungen

Eine Serie verwendet eine stabile Serien-ID und RRULE-Semantik mit Portalzeitzone. Muster: täglich, wöchentlich, bestimmte Wochentage, monatlich, jährlich, erster/letzter Werktag (Montag bis Freitag) oder erster Montag. Das Ende kann durch Datum oder Anzahl begrenzt werden. Nach RRULE werden nicht existierende Kalendertage ausgelassen, z. B. der 31. in einem Monat ohne 31. Tag. Feiertagskalender und Kapazitätsplanung sind nicht Teil der Serie.

Der vorhandene Worker bereitet Vorkommen für die nächsten 30 Tage vor, mit begrenzter Arbeit pro Durchlauf. Er setzt nach Neustarts an den bereits gespeicherten Vorkommen fort. Ein Zeitstempel im lokalen Zeitraster identifiziert jedes Vorkommen eindeutig. Ein Termin in einer Sommerzeitlücke wird um die Lücke nach vorne geschoben; in einer doppelt vorkommenden Stunde gilt die erste Instanz. Manuell eingegebene ungültige oder doppeldeutige Uhrzeiten erfordern eine Korrektur. Historische Vorkommen bleiben eigenständige Aufgaben. **Serie stoppen** beendet neue Erzeugung, vorhandene Aufgaben bleiben erhalten. Eine geänderte Folge wird als neue Serie begonnen.

Erinnerungen lassen sich vor/bei/nach Fälligkeit einrichten. Beteiligte erhalten Hinweise über die vorhandene Mailqueue; ohne eingerichteten Mailversand wird nichts versandt. Ein Ereignis wird je Empfänger und Frist höchstens einmal eingereiht. Ein späterer Fristwechsel ist ein neues Ereignis. Ersteller können Hinweise bei Überfälligkeit an sich selbst als Eskalation einrichten. Es gibt keine automatische Neuzuweisung. Einzelne Vorkommen konfigurieren ihre Erinnerungen unabhängig; externe Aufträge werden einzeln beauftragt.

Bei abgeschaltetem Modul entstehen weder Vorkommen noch Erinnerungen oder fälligkeitsbedingte Regelaktionen.

## Externe Aufträge

Im Bearbeitungsformular **extern beauftragen** wählen und Name/E-Mail angeben. Danach auf der Aufgabe einen zeitlich begrenzten persönlichen Link erzeugen und an die Person weitergeben. Der Link wird einmalig angezeigt; serverseitig bleibt nur sein Hash gespeichert. Neue Links ersetzen alte; ein Widerruf gilt sofort. Die E-Mail-Adresse wird nicht durch die Linknutzung als verifiziert behauptet.

Die externe Ansicht enthält keine Portalnavigation, internen Personenlisten oder Fachquellen. Sie ist nicht indexierbar, verwendet `no-store` und `no-referrer` und unterliegt Ratenbegrenzungen. Kommentare sind optional aktivierbar. Interne Kommentare und Dateien werden erst durch eine ausdrückliche Inhaltsfreigabe sichtbar. DMS-Referenzen sind niemals extern freigebbar. Externe Uploads werden in dieser Version nicht angeboten. Abschluss und Kommentare erscheinen mit der externen Identität im internen Verlauf.

## Aufgabenregeln

Die Aufgabenverwaltung erreicht Regeln über **Mehr → Aufgabenregeln**. Ein definierter Trigger wird mit festen Feldbedingungen und genau einer angebotenen Aktion kombiniert. Es gibt keine Skripte, Ausdrücke oder frei ausführbaren Templates. Regeln können zunächst pausiert gespeichert und ihre Bedingungen ohne Seiteneffekte an einer Beispielaufgabe geprüft werden.

Verfügbare Ereignisse: erstellt, zugewiesen, Status geändert, erledigt, Freigabe erteilt/zurückgegeben, Fälligkeit erreicht, bestimmte Aufgabe erledigt. Bedingungen: Tag, Priorität, Ersteller, Verantwortlichkeit, Gruppe, Herkunft, Status und konkrete Aufgabe. Aktionen: Folgeaufgabe, Zuweisung, Tag/Priorität, relative Fälligkeit, Mitwirkung oder Benachrichtigung.

Regeln behalten Ersteller und Version. Ausführung prüft dessen aktuelle Rechte einschließlich Quellberechtigung. Ereignisschlüssel verhindern doppelte Aktionen bei Retry; automatische Aktionen sind im Verlauf erkennbar. Rekursion ist auf drei Ebenen begrenzt und dieselbe Regel läuft innerhalb einer Kette nicht erneut. Zielpersonen müssen aktiv sein; reine Benachrichtigungen verleihen keine Sichtrechte. Änderungen erfolgen transaktional. Definitionen werden als neue Regeln gespeichert; eine alte Definition kann pausiert werden.

## Issue-Stand und verbleibende Prüfung

| Issues | Stand |
| --- | --- |
| #149–#154 | Implementiert: Kern, Arbeitsplatz, Inline-Erfassung, Zusammenarbeit, Anhänge, Delegation/Freigabe |
| #155–#160 / #110 | Implementiert: Ansichten, Serien/Erinnerungen, Abhängigkeiten, externe Aufträge, SpeechMind-Übernahme und interne Quelladapter |
| #161 | Implementiert: begrenzte Regeln mit Vorschau, Autoritätsprüfung, Retry-Schutz und Rekursionsgrenze |
| #162 | Offen, fachlich abhängig von der zentralen Integrationsschicht #101. Keine zweite Aufgaben-Spezial-API eingeführt. |
| #163 | Offen, abhängig von #162/#101 und Anbieter-App-/OAuth-Konfiguration. Keine Anbieter-Tokens oder produktiven Verbindungen eingerichtet. |
| #148 | Epic bleibt offen, bis Integrationsstufen und Abnahme abgeschlossen sind. |

Automatisierte Tests decken Rechte/CSRF/Modulabschaltung, Status und Review, parallele Versionen, Parser, sichere Darstellung, Dateien, DMS-Rechtewechsel, Ansichten, Serien/DST/Retry, externe Links, SpeechMind-Übernahme sowie Regeln ab. JavaScript wird zusätzlich auf Syntax geprüft.

Der zusätzliche CI-Job **tasks-browser** prüft die tatsächliche Oberfläche in Chromium: Formular mit Checkliste und Dateien, Rückkehr zur Übersicht, Dateidownload, Tastaturbedienung, Boardstatus, Kalender und Schnellfeld. Desktop- und Mobilansichten sowie helles/dunkles Design werden mit Screenshots dokumentiert; der Job legt diese zusammen mit dem Serverlog als Artefakt **tasks-browser** ab. Eine manuelle Prüfung mit einem Screenreader wird dadurch nicht ersetzt.
