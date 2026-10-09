# UX-Review: öffentliche Formulare und Anträge

Vor Umsetzung festgelegter Pilot für #119.

- Rolle: Ausfüllende ohne Kenntnisse der internen Architektur.
- Aufgabe: Absenden, Fehler korrigieren, nächsten Schritt erkennen.
- Hauptaktion: Weiter/Absenden; beim Antrag Bestätigen, Ergänzen, Bezahlen oder Antworten.
- Zustände: leer, ausgefüllt, fehlerhaft, gesendet, Handlung nötig, Zahlung wird geprüft, in Bearbeitung, abgeschlossen.
- Normalfall: Ausfüllen → prüfen → absenden → Eingangsbestätigung → persönlicher Bearbeitungsstand.
- Fehlerpfade: ungültige Angabe mit Fehlerlink und erhaltenen Werten; Dateien nach Fehler erneut auswählen, da Browser sie nicht wiederherstellt; ungültiger Link mit Kontakt zur zuständigen Stelle; Zahlung pending ohne erneute Zahlungsaufforderung.
- Mobil: Fehlerlink öffnet richtige Formularseite und fokussiert sichtbares Feld; Aktionen umbrechen.
- Leer: Pflichtfelder erklären Aufgabe; ohne offene Aufgabe wird das Warten erklärt.
- Rechte: persönliche Links bleiben geschützt; keine Änderung am Datenmodell oder Zugriff.
- Nach Entscheidung: offene Gebühren bleiben erreichbar; abgeschlossene Bearbeitung bedeutet nicht automatisch bezahlte Gebühren. Veraltete Bestätigungs-/Ergänzungsaufgaben werden nicht erneut angefordert.
- Verborgen: technische Prozessobjekte; weitere Aufgaben sekundär sichtbar.
