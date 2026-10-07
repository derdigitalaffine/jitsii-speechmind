# Dienstreisevorlage und Reisekosten

Die Vorlage wird im Formularbereich ausdrücklich als **inaktiver interner Entwurf** angelegt. Sie verwendet allgemeine Formularfelder, die Nachforderung für die tatsächlichen Daten, unveränderliche Prozessversionen und die vorhandene PDF-Aktion. Beschäftigte benötigen das Recht `internal_forms`; die Status- und Nachforderungslinks erfordern die Anmeldung der berechtigten Person. Keine gezeichnete Unterschrift: Antrag und Abrechnung verlangen eine ausdrückliche Pflichtbestätigung.

## Einrichtung

1. Dienstreisevorlage anlegen. Dienststellen, Gruppen/Zuständigkeiten, Abrechnungsfrist und eventuelle Gebühren-/Finanzfelder im vorhandenen Baukasten prüfen.
2. Zentrale Orte und geeignete Adress-/Routingdienste konfigurieren (siehe ORTE_UND_ROUTING.md).
3. Unter `/settings/expense-rules` Sätze und Anwendbarkeit je Gültigkeitszeitraum prüfen. Vorschläge sind nicht aktiv und eine fehlende geprüfte Fassung verhindert die Abrechnung mit geratenen Sätzen. Neue Fassungen können ausdrücklich und begründet ältere im Zeitraum ersetzen; gespeicherte Abrechnungen behalten ihren vollständigen Satz-Snapshot.
4. Prozess veröffentlichen und Formular aktivieren. Das Template allein aktiviert keinen produktiven Ablauf.

## Ablauf

Planung prüfen → gegebenenfalls korrigieren → Reise/Verkehrsmittel genehmigen → Genehmigungsdokument → Reise durchführen und tatsächlichen Verlauf abrechnen → sachlich/rechnerisch prüfen → gegebenenfalls Angaben korrigieren → Abrechnung feststellen → Personalabteilungs-PDF → abgeschlossen. Zuständigkeit ist in der Vorlage die Vorgangszuständigkeit und muss vor Freigabe passend eingerichtet werden. Auszahlung geschieht außerhalb des Portals. Ein freiwilliger Auszahlungshinweis ist vorbereitet, verhindert bei Leerwert den Abschluss aber nicht.

Anerkannter Privat-Pkw ist ein privat gehaltenes Fahrzeug mit anerkannter dienstlicher Nutzung; Dienstfahrzeuge gehören dem Arbeitgeber und haben keine private Kilometerentschädigung im Vorschlag. Triftige Gründe und Fahrzeuganerkennung werden im Prozess geprüft. Die Jahreskilometerstaffel ist konfigurierbar; der Stand wird erfasst und durch die Personalabteilung bestätigt. Gemeinsame Fahrten/Belege werden einem eigenen Antrag je Person zugeordnet und im Prüfprozess gegen doppelte Erstattung geprüft. Kein automatischer Abgleich mit fremden Lohn-/Gehaltsdaten.

## Berechnung und Dokument

Das allgemeine Feld `expense_accounting` verweist konfigurierbar auf Reisezeitraum, Fahrtstrecken, Kosten- und Verpflegungstabellen, Vorschuss, Gründe, Besonderheiten und Jahreskilometer. Es berechnet serverseitig und ignoriert gepostete Summen. Privat-/Wohnortstunden können tageweise ausgeschlossen werden. Die Mittagspause ist freiwillig und wird nicht automatisch abgezogen. Gestellte Mahlzeiten kürzen das zustehende Tagegeld mindestens um die konfigurierten Sachbezugswerte. Hotelmahlzeiten ohne Arbeitgeberveranlassung kürzen die Hotelposition; Mahlzeiten mit Arbeitgeberveranlassung müssen auf dem Verpflegungstag erfasst werden. Doppelte Hotel-/Übernachtungspauschalen am selben Tag werden abgefangen. Drittzahlungen und Vorschüsse werden abgezogen. Fehlende Belege benötigen eine Begründung.

Verwendete Sätze, Quelle, Zeitraum und prüfende Person bleiben als Snapshot im Ergebnis. Korrekturen öffnen auch die abhängige Berechnung und verlangen eine neue Pflichtbestätigung. Das Personalabteilungs-PDF enthält geplante und tatsächliche Zeiträume, Strecken, Tages-/Kostenpositionen, Satzfassungen, Vorschüsse, Bestätigung, festgestellten Erstattungsbetrag und Entscheidungsvermerk. Die generischen CSV-/JSON-Exporte enthalten auch nachgereichte Antworten und Formularnamen. Es erfolgt keine automatische Lohnbuchung oder Auszahlung.

## Fachliche Grenzen vor Freigabe

Die amtlichen LfF-Hinweise wurden im Oktober 2026 recherchiert. Einige Seiten tragen ältere Veröffentlichungsdaten oder widersprechen neueren Änderungen. Die JavaScript-basierte Landesrechtsseite konnte nicht als vollständiger Gesetzestext gelesen werden. Deshalb sind voreingestellte Sätze ausdrücklich ein **zu prüfender Vorschlag**, keine pauschale Erklärung aktueller Rechtskonformität.

Nach aktuellen LfF-Hinweisen: Pkw ohne/mit triftigem Grund 0,18/0,28 €, anerkannter Pkw 0,38 €, Fahrrad 0,05 €/km; Tagegeld >8 h 8 €, ab14 h14 €, voller Kalendertag24 €. Mahlzeitenabzüge in RLP beziehen sich auf das zustehende Tagegeld, mit Sachbezugs-Mindestwerten. Der 2026-Vorschlag enthält Frühstück2,37 €, Mittag-/Abendessen4,57 €. **Grenze und niedrigerer Satz der anerkannten Pkw-Jahresstaffel zusätzlich prüfen.** Fußwege und Übernachtung ohne Nachweis sind mit0 vorbelegt und erfordern Prüfung/Konfiguration. Vereinbarte Fahrzeuge, Mitnahmeentschädigung, dauerhaft wiederkehrende Reisen und Spezialtarife benötigen eine ergänzte Satz-/Formularkonfiguration.

Auslandsreisen, Abbruch/Ausfall, private Anteile und längerfristige Aufenthalte werden ausdrücklich erfasst und in Prüfhinweisen aufgeführt. Es werden keine ausländischen Sätze geraten; geprüfte Sonderbeträge können als Kostenpositionen erfasst und im Entscheidungsvermerk festgestellt werden. Keine automatische steuerliche Einstufung, keine automatische Dreimonatsprüfung über andere Vorgänge. Keine Garantie des Routings für die kürzeste übliche Strecke. Abweichender Reisebeginn/Ende wird erfasst und muss gegebenenfalls auf die Dienststätten-Kosten begrenzt werden. Diese fachlichen Prüfungen bleiben in der Personalabteilung.

Quellen: https://www.lff.rlp.de/fachliche-themen/reisemanagement/reisekosten/tagegeld_ft ; https://www.lff.rlp.de/fachliche-themen/reisemanagement/reisekosten/hotelkosten_ft ; https://www.lff.rlp.de/service/aktuelles/detail/informationen-zur-aenderung-des-landesreisekostengesetzes-lrkg-der-landestrennungsgeldverordnung-ltgv-sowie-des-landesumzugs-kostengesetzes-lukg ; https://www.lff.rlp.de/fachliche-themen/reisemanagement/reisekosten/wegstreckenentschaedigung_ft ; https://www.lff.rlp.de/fachliche-themen/reisemanagement/reisekosten/fahrrad_ft ; https://www.kbs.de/DE/AngeboteFuerFirmen/VersicherungsrechtBeitraegeUndMeldungen/news/25_08_Sachbezugswerte_2026

Tests: Berechnungsgrenzen, Mahlzeiten, Hotel, Fahrzeugtrennung, Jahresstaffel, Drittzahlungen/Vorschuss, fehlende Belege, Satzrevision/Snapshot, serverseitige Summen, Korrekturen/Pflichtbestätigung und Template-Zugriff. Produktive Anbieter-, Mail-, Browser- und fachliche PDF-Abnahme stehen aus.
