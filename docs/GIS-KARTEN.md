# GIS und Karten im Portal

## Amtliche öffentliche Quellen

| Quelle | Verwendung |
| --- | --- |
| [Geoportal Rheinland-Pfalz](https://www.geoportal.rlp.de/) | Dienstkatalog und Metadaten |
| [LVermGeo Open Data](https://lvermgeo.rlp.de/geodaten-geoshop/open-data/) | Datenangebot und Nutzungsbedingungen |
| [ALKIS-WFS, Registrierung 519](https://www.geoportal.rlp.de/registry/wfs/519) | Öffentliche Flurstücke: Geometrie, Kennzeichen, Gemarkung, Flur, Nummer, Fläche, Lage und Nutzung, soweit geliefert |
| DTK5 RP farbig/grau | Topographischer Kartenhintergrund; heutiger Dienst zur früheren DGK5-Anforderung |
| LiKa RP | Tagesaktuelle Liegenschaftskarte als zusätzliche Ebene |
| Verwaltungsgrenzen RP | Verwaltungs-, Gemarkungs- und Flurgrenzen |
| Kommunale Bebauungsplandienste Otterbach/Otterberg | Räumliche Planübersicht; Nutzungsbedingungen des Herausgebers beachten |

LVermGeo-Quellen werden mit Quellenvermerk und Datenlizenz Deutschland – Namensnennung 2.0 gekennzeichnet. Abrufzeit und vom Dienst gelieferter Datenstand sind verschiedene Angaben. Kommunale Bebauungspläne erhalten einen eigenen Herausgebervermerk. Öffentliche Verfügbarkeit ersetzt nicht die Nutzungsbedingungen einer Quelle. Verfügbarkeit und Inhalt liegen beim jeweiligen Anbieter.

## Bedienung

Bestehende Startgrundkarte und vorhandene Ebenen bleiben erhalten. Verwaltung und angemeldete Nutzer können passende amtliche Quellen ergänzen. Die öffentliche Auskunft benötigt keine Anmeldung. Eigene Dienste hinzufügen und Karten speichern können ausschließlich angemeldete Nutzer; zentrale Ebenen verwalten Personen mit `maps_admin`.

Suche nach Gemarkung, optional Flur und Zähler/Nenner, oder vollständigem Kennzeichen. Ergebnisse lassen sich markieren und mehrfach auswählen. Kartenklick prüft die Geometrie, einschließlich Innenflächen. CSV/JSON und die Druckansicht mit Browser-PDF geben die Auswahl, Quellen und Abrufzeit aus. Eigentümerdaten sind nicht Bestandteil dieses Moduls.

Der einfache Modus priorisiert Auskunft und Ebenen; Zeichenwerkzeuge stehen im erweiterten Modus. Zeitdimensionen bieten eine Zeitauswahl, noch keinen Vergleich. Auswahl wird im Zustand eigener Karten gespeichert. Interne Benutzer-/Gruppenfreigaben erlauben Lesen und eigene Kopie, keine Bearbeitung der Ursprungskarte. Öffentliche Tokenlinks sind davon getrennt. Interne Ebenen erfordern stets eine Anmeldung.

Formular-Kartenfelder können die Flurstücksübernahme aktivieren, wenn Flächen erlaubt sind. Übernommene Geometrien und Metadaten verwenden die vorhandenen Antwort-, Antrags- und DMS-Wege. Teilflächen zählen gegen das Objektlimit. CSV-Geometriespalte und JSON erhalten die Metadaten. Katasterflächen bleiben in der Oberfläche unverändert; diese Informationsausgabe ist kein amtlich beglaubigter Auszug und keine rechtliche Prüfung von Nutzereingaben.

## OGC-Unterstützung und Grenzen

- WMS 1.1.1/1.3.0 in EPSG:3857, Operationsadresse aus GetCapabilities, vererbte Abfragefähigkeit und Zeitdimension. GetFeatureInfo fragt exakt den geklickten Kachelausschnitt ab, auch bei gedrehter Karte.
- WMTS GetTile über KVP oder REST mit echten Matrixkennungen, Matrixset, Stil und Kachelgröße 256/512. Unterstützt wird ein globales Web-Mercator-Raster mit Standardursprung und zweierpotenzigen Matrixgrößen. Andere Raster benötigen eine spätere Reprojektion und werden nicht als funktionierend angeboten.
- WFS: bevorzugtes angebotenes GeoJSON-Format, alternativ GML für Punkte, Linien und Flächen. Koordinaten in WGS84/CRS84 oder Web-Mercator werden normalisiert; unbekannte CRS oder ungültige Koordinaten erzeugen eine verständliche Fehlermeldung. GeoJSON in WGS84 wird nicht allein wegen einer EPSG-URN achsenvertauscht.
- Öffentliche ALKIS-Textsuche nutzt WFS-POST, da der Geoportal-Proxy XML-Filter in GET-URLs ablehnt. Punktabfragen verwenden eine kleine räumliche Begrenzung und geometrische Trefferauswahl. Maximal 20 Treffer pro Suche; die Suche bei weiteren Treffern genauer eingrenzen.
- Begrenzte Abrufwarteschlange, vorhandener Kachelcache und Netzwerkschutz bleiben erhalten. Fehler in XML-Antworten werden auch bei HTTP 200 erkannt. Netzwerkstörungen können weiterhin dazu führen, dass externe Ebenen vorübergehend fehlen.
- Bestehender GeoJSON-Austausch freier Zeichnungen bleibt verfügbar. Für die neue Flurstücksauskunft werden CSV, JSON und Drucken/PDF angeboten; kein zusätzlicher GeoJSON-Export.

## Technische Integration

`map_layers.service_json` hält Dienstoptionen; `user_maps.share_json` die internen Benutzer-/Gruppenfreigaben. Bestehende SQLite-Datenbanken bekommen beide Spalten mit leerem Standardwert. Es werden keine vorhandenen Layer neu gesät oder ersetzt.

`parcels.py` kapselt die öffentliche Quelle und eine feste Attributauswahl. Auswahl-Snapshots speichern Geometrie, Kennzeichen, Quelle und Abrufzeit. Innenringe werden erhalten und bei geometrischen Flächenberechnungen abgezogen. Zu große Polygone werden abgewiesen statt still gekürzt.

Regressionstests liegen in `portal/tests/test_gis_services.py` und `portal/tests/test_maps.py`; sie prüfen Dienstadressen, WMTS-Matrixkennungen, CRS, Filter, Geometrien, Formulare, Rechte und Fehlerantworten. Live geprüft wurden die öffentliche Flurstückssuche und Punktabfrage in Otterbach sowie GetMap für DTK5, LiKa, Verwaltungsgrenzen und beide kommunalen Planquellen. Externe Anbieter können ihr Angebot unabhängig vom Portal ändern.
