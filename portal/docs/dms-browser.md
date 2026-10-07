# DMS-Ordnerbrowser und Vorschau

Bestehende Aktenplanbereiche werden als Ordner dargestellt, Vorgänge als Aktenordner
und deren Dateien als Dokumente. Ordnerkarten, einklappbare Navigation, klickbare
Pfadangaben und „Übergeordneter Ordner“ funktionieren auch auf schmalen Bildschirmen.
Die Aktenplanverwaltung nutzt verschachtelte aufklappbare Ordner; ihre bestehenden
Bearbeitungs-, Zugriffs- und Fristformulare bleiben erhalten.

Ohne Suchfilter werden Vorgänge direkt im gewählten Ordner angezeigt. Volltext und
weitere Suchfilter durchsuchen Unterordner; die Option „Unterordner mit durchsuchen“
ermöglicht das auch ohne Suchbegriff. CSV-Export übernimmt den aktuellen Suchbereich.
Gespeicherte Suchen, Mehrfachauswahl und protokolliertes Verschieben bleiben integriert.
Einträge und Namen aus nicht lesbaren Bereichen erscheinen nicht in Ordnernavigation
oder Antragsartfiltern. Lesbare Unterordner unter einem nicht lesbaren Elternordner
werden als eigene erreichbare Wurzelordner angezeigt.

Die Vorgangsansicht bietet eine eingebettete PDF-/Bildvorschau und einen großen separaten
Betrachter. Das gilt für DMS-Dateien, Antrags-PDFs, erzeugte Prozessdokumente und PDF/Bilder
aus Anträgen oder Nachforderungen. Jede Vorschau verwendet die vorhandene Zugriffsprüfung
und prüft die Zugehörigkeit zum Vorgang. Ohne `preview=1` bleiben vorhandene Dateilinks
Downloads. HTML/SVG und andere unsichere Dateitypen bleiben Downloads. Vorschauen sind
nur im selben Ursprung einbettbar und werden nicht gecacht. Dieselben Header ermöglichen
PDF-Vorschauen im neuen Umlaufmodul, ohne die Schutzheader des übrigen Portals aufzuweichen.

Blättern, Zoom, Suche und Druck nutzen den PDF-Betrachter des Browsers. Browser ohne
PDF-Vorschau erhalten einen Download-/Öffnen-Link. OCR ist nicht enthalten.
Die Datenstruktur, Aktenplanvorlagen, bestehende Ablage und Rechte werden nicht migriert.
