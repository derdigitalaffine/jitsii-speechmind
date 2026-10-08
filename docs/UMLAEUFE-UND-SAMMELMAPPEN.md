# Aushänge, Umläufe und wiederverwendbare Sammelmappen

Das Modul nutzt Benutzer, Gruppen, Vertretungen, Navigation und den zentralen E-Mail-Versand des Portals. Es wird unter **Verwaltung → Module** eingeschaltet. **Umläufe erstellen**, **Umläufe veröffentlichen** und **Umläufe verwalten** sind getrennte Rechte. Empfänger benötigen kein Erstellerrecht.

## Sammelmappen separat zusammenstellen

Unter **Aushänge & Umläufe → Sammelmappen** (`/sammelmappen`) werden wiederverwendbare Vorlagen gespeichert. Eine Mappe enthält geordnete Dokumente und Portalobjekte, noch keine Empfänger, Fristen oder Kenntnisnahmen.

1. **Neue Sammelmappe** wählen, Name und kurze Beschreibung eingeben.
2. Dateien auswählen oder ablegen. Bereits gewählte Inhalte erscheinen als Karten mit Typ und Reihenfolge.
3. Unter **Portalobjekte hinzufügen** nach Rechtstext, Formular, Dateiname oder Akte suchen. Typfilter und einzeln auswählbare Treffer ersetzen lange Dropdowns. Größere Trefferlisten lassen sich schrittweise erweitern.
4. Mit Pfeilen die Lesereihenfolge ändern oder Inhalte entfernen. Optional ein Markdown-Textdokument direkt erstellen; vorhandene Markdown-Dokumente können im Mappeneditor bearbeitet werden.
5. **Sammelmappe speichern**. Standardmäßig ist sie privat. **Als gemeinsame Vorlage bereitstellen** macht sie für berechtigte Ersteller lesbar; hochgeladene Dateien werden dadurch mit diesen Personen geteilt.

PDF, Bilder, Markdown, Text, Office-Dateien und E-Mails sind unterstützt. Maximal 100 Dokumente pro Mappe, 25 MB je Datei und 100 kB je Markdown-Dokument. HTML/SVG-Uploads sind nicht erlaubt. Die Kurzbeschreibung dient der Auswahl und wird nicht als Dokument übernommen.

Eigene Mappen können bearbeitet werden; die Verwaltung und eine aktuell bestätigte Portalvertretung können im berechtigten Rahmen aushelfen. Gemeinsame Vorlagen anderer Ersteller dürfen angesehen und verwendet werden, werden dadurch aber nicht frei bearbeitbar.

## Im Umlauf oder Aushang verwenden

**Neu erstellen** öffnet die drei Bereiche **Inhalt**, **Empfänger** und **Ablauf**. Ein Aushang informiert; ein Umlauf kann eine Kenntnisnahme oder Entscheidung verlangen. Beide können Sammelmappen verwenden.

Unter **Sammelmappen auswählen** nach einer gespeicherten Mappe suchen und sie auswählen. **Bearbeiten** öffnet den getrennten Mappeneditor; **Sammelmappen verwalten / neue Mappe** führt zur Mappenübersicht. Die Rückkehr über **Gespeicherte Mappe im Umlauf auswählen** wählt die Mappe im Entwurf vor. Erst **Entwurf speichern** übernimmt sie.

Die Übernahme erstellt unabhängige Kopien der Dateien und Markdowntexte. Portalobjekte bleiben Verknüpfungen mit ihren bestehenden Leserechten. Spätere Änderungen an der Vorlage verändern weder den gespeicherten Umlauf noch veröffentlichte Fassungen oder Nachweise. Mehrfach enthaltene identische Portalverweise werden einmal übernommen. Hochgeladene Dateien bleiben eigene Dokumente.

Zum individuellen Anpassen einer übernommenen Mappe zuerst den Entwurf speichern; danach können einzelne Dokumente entfernt oder neu geordnet werden. Vor dem Speichern entfernt das Abwählen die ganze ausgewählte Mappe. Bereits gespeicherte Umlauf-Inhalte lassen sich mit **Gespeicherte Inhalte als Mappe sichern** in eine neue wiederverwendbare Vorlage kopieren.

## Empfänger und Ablauf

Personen und Gruppen werden über Suchlisten einzeln gewählt; die Auswahl bleibt sichtbar. Pfeile ordnen einzelne Personen für Stationsfolgen. Gruppen folgen danach, doppelte Portalempfänger werden nur einmal aufgenommen. Die Zusammenfassung zeigt ausgewählte Portalpersonen und Gäste; ein gespeicherter Verteiler wird erst beim Speichern ergänzt.

Gäste werden als `Name;E-Mail` oder nur E-Mail eingetragen, eine Person je Zeile. Persönliche Gastlinks sind befristet und widerrufbar. Interne Rechtstexte, interne Formulare und DMS-Verweise werden nicht durch den Gastlink freigegeben. Für Gäste müssen ausdrücklich freigegebene Kopien verwendet werden.

**Nur lesen**, **Kenntnis nehmen** oder **Freigeben / ablehnen** wird über Auswahlkarten festgelegt. Einzelbestätigungen und Stationsfolgen sind optional. Sichtbarkeit, redaktionelle Freigabe, Zeitplanung, Erinnerungen, Eskalation und Verteileroptionen sind einklappbar. Ein öffentlicher Aushang erlaubt nur Information mit öffentlichen Inhalten und ohne Gastempfänger. Die Veröffentlichung prüft Quellrechte erneut.

Speichern aktualisiert nur den Entwurf. Veröffentlichen ist eine getrennte Aktion und versendet über die vorhandene Mailwarteschlange. Persönliche Nachweise sind fassungsgebunden; eine Vertretung nimmt niemals für eine andere Person Kenntnis. Bei paralleler Bearbeitung verhindert der Änderungsstand das Überschreiben. Mit JavaScript bleiben Eingaben auch bei Speicherfehlern auf der Seite.

## Schwarzes Brett und Lesen

Das **Schwarze Brett** stellt Beiträge blogartig mit Kategorie, Titel, Datum, Herausgeber, Textauszug und Dokumentenlink dar. Wichtige Beiträge sind angeheftet. Suche und Kategorie grenzen die Beiträge ein. Interne Inhalte bleiben nur für berechtigte angemeldete Personen sichtbar; öffentliche Beiträge können ohne Anmeldung gelesen werden.

Die Leseansicht bietet ein Inhaltsverzeichnis der Mappe. PDF-Vorschauen verwenden den Browserbetrachter; bei fehlender Browserunterstützung steht die Datei als Download bereit. Kenntnisnahmen entstehen ausschließlich durch ausdrückliche Bestätigung, nie durch das Öffnen einer Seite.

## Markdown komfortabel bearbeiten

Die Werkzeugleiste fügt Fett/Kursiv, Überschriften, Listen, Zitate, Links, Code und Tabellen ein. **Strg+B / Strg+I** bzw. die entsprechenden Cmd-Tasten formatieren die Auswahl. Links werden über Text und Zieladresse eingegeben. **Schreiben**, **Nebeneinander** und **Vorschau** wechseln die Ansicht; in Vorschauansichten wird nach Eingaben verzögert neu gerendert. Auf schmalen Bildschirmen werden die beiden Bereiche untereinander dargestellt.

Die Vorschau nutzt denselben serverseitigen Markdownrenderer wie die Veröffentlichung. HTML wird als Text behandelt und unsichere Linkprotokolle werden nicht zu aktiven Links. Ohne JavaScript funktionieren native Auswahl, Reihenfolge bestehender Dokumente und Speichern; Suche, direkte Textdokument-Vorschau und komfortable Sortierung benötigen JavaScript.

Technische Details zu Nachweisen, Erinnerungen, Gastlinks und Datenschutz: [Moduldokumentation](../portal/docs/circulations.md).


## Rückmeldungsberichte und Empfängerführung

`/umlaeufe/auswertung` enthält eigene Umläufe und optional alle zur Bearbeitung zugänglichen Umläufe. Die Fassungsauswertung trennt Dokumentnachweise, Entscheidungen, offene Rückfragen und Versandaufträge. Zugriff auf eine Sammelmappe oder die Rolle als Empfänger erteilt keine Berichtsrechte. Exporte enthalten keine Gasttoken. In der Sammelmappenübersicht wird nur die Verwendung in berechtigt auswertbaren Umläufen gezeigt.

Die Leseansicht besitzt Aktionsbanner, persönlichen Dokumentfortschritt, Inhaltsindex und Vorschauen. Dashboard und Mail nennen erforderliche Handlung und Frist. Mails versenden keine internen Volltexte; die optionale Kurzbeschreibung wird bewusst durch den Herausgeber eingetragen. Gastlinks enthalten Ablaufhinweis und Weitergabeverbot.

Der erweiterte Modus ergänzt verbindliche Dokumentreihenfolge bei Einzelbestätigungen (`require_item_sequence`), aggregierten Fortschritt ohne fremde Einzelangaben (`share_progress`) und ausdrückliche Vertretungsfreigabe (`allow_proxy_approval`). Reihenfolge und Vertretung werden serverseitig geprüft. Persönliche Kenntnisnahme ist auch bei Vertretung nicht delegierbar; Freigaben protokollieren den tatsächlichen Akteur.

## Entwürfe löschen und Änderungen verwerfen

In **Entwürfe** können berechtigte Bearbeitende einzelne oder mehrere Entwürfe auswählen und löschen. „Alle angezeigten Entwürfe“ bezieht sich auf die aktuell gefilterte Liste. Noch nie veröffentlichte Umläufe werden samt Dokumenten in den bestehenden Papierkorb verschoben und können dort 30 Tage lang wiederhergestellt werden. Der Umlauf-Papierkorb zeigt nur Entwürfe, die Sie bearbeiten dürfen.

Im Editor kann ein einzelner unveröffentlichter Entwurf ebenfalls gelöscht werden. Bei bereits veröffentlichten Umläufen steht stattdessen **Entwurfsänderungen verwerfen** zur Verfügung: Der Bearbeitungsstand wird auf die veröffentlichte Fassung zurückgesetzt. Veröffentlichte Dokumente und Rückmeldungen bleiben erhalten. Bei zwischenzeitlichen Änderungen durch andere Bearbeitende muss die Seite zuerst neu geladen werden.


## Umlaufaufgaben im Arbeitsplatz

**Meine Aufgaben** führt sämtliche offenen eigenen Kenntnisnahmen und Freigaben neben Antrags- und Buchungsaufgaben auf. Die Liste zeigt die erforderliche Aktion, Frist, Fortschritt pro Dokument und einen direkten Link zur richtigen Empfängerstation. Wartende Stationen und nach einer Ablehnung gestoppte Umläufe sind erkennbar. Zulässige Freigaben in Vertretung nennen die vertretene Person. Informationen ohne Rückmeldepflicht sowie erledigte, abgelaufene oder archivierte Fassungen erscheinen nicht als offene Aufgaben. Der Aufgabenindikator im Menü und die Aufgaben-Kachel auf der Startseite berücksichtigen ebenfalls Umläufe; der Menüindikator wird bis zu 30 Sekunden zwischengespeichert.
