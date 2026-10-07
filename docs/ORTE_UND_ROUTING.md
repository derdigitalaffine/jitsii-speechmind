# Zentrale Orte und Fahrtstrecken

Das allgemeine Formularfeld `route` speichert signierte Berechnungen je Fahrtabschnitt, Koordinaten, Fahrzeugkategorie, Datum, GeoJSON, Dienstadresse, Berechnungsdatum und begründete tatsächliche Kilometer. Anerkannter Privat-Pkw und Dienstfahrzeug sind getrennte Kategorien. Hin- und Rückfahrt werden separat berechnet, das Rückfahrziel kann verändert werden. Öffentliche Verkehrsmittel haben keinen Straßenkilometeranspruch; Tickets gehören zu den Kostenpositionen.

`/settings/locations` verwaltet zentrale Orte, Kategorien, eigene Orte und Favoriten. Das Recht `locations_manage` oder eine ausgewählte Pflegegruppe erlaubt zentrale Pflege. CSV (UTF-8, Semikolon) enthält name, category, street, zip, city, lat, lon, public; Import validiert komplett vor der Speicherung. Import erzeugt neue Orte, überschreibt keine bestehenden. Rathäuser können ausdrücklich angelegt werden; Koordinaten werden gesucht und von der pflegenden Person bestätigt.

OSRM-kompatible Dienste für Auto, Fahrrad und Fußwege sind zentral austauschbar. Defaults sind die öffentlichen FOSSGIS-Dienste. Nominatim bleibt über Karteneinstellungen austauschbar. Cache und dateibasierte Sperre begrenzen Anfragen installationweit auf höchstens eine Anfrage pro Sekunde je Dienstfamilie. Keine Adresssuche beim Tippen, keine automatische Suche für CSV-Importe.

Öffentliche Nominatim-Suche und FOSSGIS-Routing verlangen die ausdrückliche Erklärung, dass ausschließlich öffentliche Orte übertragen werden. Persönliche/vertrauliche Reiseziele benötigen einen dafür geeigneten eigenen Anbieter. Koordinaten manuell einzugeben ersetzt diese Voraussetzung für den öffentlichen Routingdienst nicht. Öffentliche Routingdienste protokollieren Streckenpunkte. Routing liefert einen Routenvorschlag und garantiert nicht die reisekostenrechtlich kürzeste übliche Strecke. Abweichungen prüft der allgemeine Prozess.

Tests mocken externe Dienste. Produktive Anbieteranbindung, Kartenlayout und Bedienung im Browser sind vor Freigabe zu prüfen. Tarifberechnung und Dienstreisevorlage folgen in einem separaten PR.
