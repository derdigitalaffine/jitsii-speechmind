# Interne Dienstanweisungen

Das Rechtstextmodul behält Gliederung, Volltextsuche, geplante Fassungen, Versionsvergleich,
Anlagen, Markdown-Import und bestehende Redaktionsrechte. „Veröffentlicht“ und „intern“
sind getrennt: veröffentlichte interne Texte lesen angemeldete Portal-Benutzer, Entwürfe
weiterhin nur Personen mit dem bestehenden Recht „Rechtstexte“.

Die Dokumentart „Interne Dienstanweisung“ aktiviert den internen Schutz automatisch.
Auch andere Dokumentarten können „Nur angemeldete Portal-Benutzer“ verwenden.
Im Lesekatalog gibt es eine eigene Ansicht für interne Texte und eine gemeinsame Ansicht;
das öffentliche Ortsrecht bleibt die Standardansicht. Öffentliche und eingebettete
Abfragen ignorieren interne Inhalte, einschließlich Treffer, Vorschläge, Querverweiscache
und Rechtsgrundlagen öffentlicher Formulare/Ressourcen. Downloads und frühere Fassungen
prüfen denselben Schutz. Interne Fassungen und Anlagen bleiben intern, wenn später eine
öffentliche aktuelle Fassung angelegt wird. JSON-Import/Export erhält diese Kennzeichnung.
Markdown-Metadaten unterstützen „Intern: ja“.

Das Umlaufmodul kann interne Dienstanweisungen in internen Sammelmappen verknüpfen.
Es friert den Text der bestätigten Fassung ein, erlaubt aber keine Verteilung interner
Rechtstexte an Gäste oder als öffentlichen Aushang. Quellrechte werden bei jeder Anzeige
geprüft. Bestehende öffentliche Texte bleiben bei der Datenbankmigration öffentlich.
