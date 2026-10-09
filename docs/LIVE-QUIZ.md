# Quiz und Rangfolge in Live-Umfragen

Unter **Umfragen & Abstimmungen → Live-Umfrage → Neue Frage** stehen zusätzlich **Quiz** und **Rangfolge** zur Verfügung. Die bestehenden Links, QR-Codes, Seminar-Verknüpfungen und Berechtigungen bleiben nutzbar.

## Quiz

Antwortmöglichkeiten stehen jeweils in einer Zeile. Unter **Richtige Lösung & Wertung** werden die Nummern der richtigen Zeilen eingetragen, etwa `1, 3`. Eine oder mehrere Lösungen sind möglich; Teilnehmende wählen die passenden Antworten und senden bewusst ab.

Punkte können pro Frage eingestellt werden (0 = ohne Wertung). Ohne Teilpunkte zählt nur die vollständig richtige Auswahl. Mit Teilpunkten erhält jede richtige Auswahl einen gleichen Anteil; jede falsche Auswahl zieht einen Anteil ab, die Wertung bleibt mindestens 0. Es gibt keinen Geschwindigkeitsbonus.

Lösungen, Punktwerte und Ranglisten werden erst nach ausdrücklichem **Freigeben** oder beim Wechsel von der Quizfrage zur nächsten Frage gezeigt. Auch die Beameransicht hält die Lösung vorher zurück. Freigabe sperrt gleichzeitig weitere Antworten. Bei „nie (nur Beamer)“ bleibt die Lösung auf Teilnehmergeräten verborgen.

Optionales Zeitlimit: 0 bedeutet ohne Limit. Im moderierten Ablauf beginnt es beim Anzeigen der Frage, im freien Ablauf beim Start der Umfrage. **Zeitlimit neu starten** startet die Zeit erneut; gesperrte oder bereits aufgelöste Fragen bleiben gesperrt. Nach Zeitablauf verweigert der Server weitere Antworten. Die Anzeige aktualisiert sich regelmäßig.

Teilnahme bleibt standardmäßig anonym. Ein freiwilliger Anzeigename kann pro Quizfrage angeboten werden; nur ausgefüllte Namen erscheinen in deren Top-N-Rangliste. Diese Rangliste gilt jeweils für die einzelne Frage, nicht über die gesamte Veranstaltung. Namen sind frei wählbar und keine verifizierte Identität.

## Rangfolge

Optionen lassen sich am Computer ziehen oder über große Aufwärts-/Abwärtstasten verschieben. Die Tasten funktionieren auch per Touch und Tastatur. Nur die eingestellten ersten N Plätze werden abgesendet; weitere Optionen bleiben unbewertet.

Die Auswertung nutzt Borda-Punkte: Bei fünf Optionen erhält der erste Rang fünf Punkte, der zweite vier usw.; nicht gewählte Optionen erhalten 0. Zusätzlich wird der mittlere Rang **der tatsächlich vergebenen Ränge** angezeigt. Mehr Punkte bedeuten höhere Gesamtpriorität; dies ist keine förmliche Wahl.

## Schutz und Export

Je Gerät und Frage bleibt eine änderbare Antwort gespeichert, bis Sperre, Freigabe oder Zeitablauf eintreten. Bereits beantwortete Fragen können nicht verändert werden; zuerst bewusst zurücksetzen oder eine neue Frage anlegen. Zurücksetzen löscht Antworten und deren Anzeigenamen und öffnet die Frage bewusst für eine neue Runde; eine aktive Frage startet ihr Zeitlimit dabei neu. Eine bloße erneute Freigabe oder Entsperrung kann eine bereits aufgelöste Frage nicht wieder öffnen.

Der CSV-Export enthält Rohantworten bzw. geordnete Optionskennungen und nachvollziehbare Ränge/Punkte. Anzeigenamen, Gerätekennungen und Gerätehashes werden nicht exportiert. Ergebnisse bleiben Eigentümern und Administratoren zugänglich; fremde Benutzer erhalten keinen Verwaltungszugang.
