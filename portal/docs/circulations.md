# Umläufe & Aushänge

Das Modul wird unter Verwaltung → Module geschaltet. Bestehende Benutzerverwaltung,
Gruppen, Navigation, Startseitenanpassung, CSRF-Schutz und E-Mail-Warteschlange werden
weiterverwendet. Die drei Rechte heißen „Umläufe erstellen“, „Umläufe veröffentlichen“
und „Umläufe verwalten“. Empfang und persönliche Bestätigung benötigen kein Erstellerrecht.

Sammelmappen werden separat unter `/sammelmappen` als wiederverwendbare eigene oder gemeinsame Vorlagen gespeichert. Aushänge und Umläufe wählen diese Vorlagen aus; beim Speichern werden Dateien und Markdowntexte unabhängig kopiert. Portalverweise behalten ihre Quellrechte. Der getrennte Mappeneditor und die Rückkehr zur vorausgewählten Mappe sind in [UMLAEUFE-UND-SAMMELMAPPEN.md](../../docs/UMLAEUFE-UND-SAMMELMAPPEN.md) beschrieben.

Ein gespeicherter Umlauf-/Aushangentwurf wird separat veröffentlicht; spätere Entwurfsänderungen verändern keine Nachweise.
Die Veröffentlichung speichert Inhalt und SHA-256-Prüfsumme, einen Empfängersnapshot
und eine Fassung. Eine neue Fassung fordert standardmäßig erneut zur Bestätigung auf.
Übernommene Nachweise sind ausdrücklich als Nachweise der Vorfassung markiert.

Verteiler enthalten Benutzer, Gruppen, alle aktiven Benutzer und externe E-Mail-Adressen.
Gruppen sind standardmäßig statisch; automatische Aufnahme neuer Mitglieder ist optional.
Stationsfolgen haben einen festen Empfängerkreis. Ablehnungen benötigen eine Begründung
und stoppen die Folge. Ausnahmen sowie persönliche/Papiernachweise werden mit Grund,
Zeitpunkt und erfassender Person getrennt von eigenen digitalen Bestätigungen geführt.

Eine bestätigte, aktuell gültige Portal-Vertretung darf den Umlauf des Herausgebers
bearbeiten. Persönliche Bestätigungen verwenden ausschließlich die eigene Benutzer-ID.
Persönliche Einladungen und Gastfähigkeiten werden nicht an Vertretungen weitergeleitet.

Portal-Verweise gewähren keine neuen Quellrechte. DMS-Verweise sind intern, werden
beim Veröffentlichen für jeden Empfänger geprüft und bei jeder Anzeige erneut geprüft.
Für Gäste müssen ausdrücklich zur Verteilung freigegebene Kopien hochgeladen werden.
Dateien bleiben fassungsgebunden erhalten. PDF und Rasterbilder werden inline angezeigt;
Zusätzliche Markdown-Dokumente werden sicher gerendert und als Original zum Download angeboten. Office-Dateien, E-Mails und andere Texte stehen als Download bereit. Die Reihenfolge der Dokumente ist im Editor einstellbar. HTML/SVG sind ausgeschlossen.

Gastlinks sind zufällige, gehashte, befristete Fähigkeiten pro Person und Fassung.
Die Verwaltung kann sie widerrufen oder neu per E-Mail ausstellen. Ohne eingerichteten
Portal-Mailversand werden keine Gastlinks versandt; bestehende Portalempfänger finden
ihre Umläufe weiterhin im persönlichen Posteingang. Gastansichten unterdrücken Caching,
Referrer und Suchmaschinenindexierung. GET-Anfragen bestätigen niemals etwas.

Der vorhandene Hintergrundworker übernimmt geplante Veröffentlichung, dynamische
Empfängeraufnahme, Erinnerungen und einmalige Eskalation nach Fristüberschreitung.
Erinnerungsintervalle und Gastlinkdauer sind pro Umlauf/Aushang einstellbar, nicht in der wiederverwendbaren Sammelmappe. Eskalationshinweise
enthalten nur die Anzahl offener Bestätigungen; die Empfängerliste ist für Herausgeber,
berechtigte Verwaltung und deren aktive Vertretung reserviert.

PDF-, CSV- und JSON-Nachweise sowie Papier-Unterschriftenlisten sind in der geschützten
Verwaltung verfügbar. CSV/JSON-Zeitpunkte sind ausdrücklich UTC. Papierlisten gelten erst
nach dokumentiertem Nachtrag als Kenntnisnahme. Rückfragen und Antworten bleiben privat.

Die PDF-Vorschau nutzt den Browserbetrachter mit Downloadfallback. Dessen Werkzeuge
(Zoom, Suche, Druck) hängen vom Browser ab. OCR und Dokumentanmerkungen sind nicht enthalten.

Öffentliche Aushänge erscheinen im bestehenden öffentlichen Menü nur, wenn ein aktuell lesbarer öffentlicher Aushang vorhanden ist. Interne Umläufe erscheinen dort nicht. Widerrufene Gastlinks bleiben auch bei Erinnerungen gesperrt, bis die Verwaltung sie ausdrücklich neu ausstellt.

## Oberfläche und Speicherung

Das Schwarze Brett verwendet eine Beitragsansicht; der Entwurf ist in Inhalt, Empfänger und Ablauf gegliedert. Die Suchlisten und Inhaltskarten ersetzen Mehrfach-Dropdowns. Empfänger und Dokumente lassen sich per Tastatur oder Berührung ordnen. Erweiterte Einstellungen sind einklappbar. Die Markdown-Werkzeugleiste und verzögerte Vorschau nutzen den bestehenden, HTML-deaktivierten Renderer.

Vorlagen stehen in `circulation_bundles`, Dateien unter `data/portal/circulation-bundles/<id>/`. Die vorhandene Datenbankinitialisierung legt die zusätzliche Tabelle an. Private Vorlagen sind auf Eigentümer, berechtigte Verwaltung und aktive Vertretung beschränkt. Gemeinsame Vorlagen können Ersteller lesen, aber nicht allein deshalb bearbeiten. Portalobjekte werden bei der Übernahme und Veröffentlichung geprüft. Originaldateien sind nicht öffentlich abrufbar.

Dokumentfolgen enthalten ausschließlich serverseitig bekannte Referenzen; fehlende, doppelte oder fremde Referenzen werden abgewiesen. Uploads und Kopien werden bei einem fehlgeschlagenen Speichern zurückgerollt. Der Versionsstand verhindert konkurrierendes Überschreiben. Aus einem veröffentlichten Umlauf wird niemals automatisch auf eine spätere Vorlagenänderung umgeschaltet.

Der Schutz vor ungespeicherten Änderungen berücksichtigt nur Entwurfsdaten, keine Suchfelder oder Editoransichten. Eine erfolgreiche Speicherung navigiert ohne Verlassen-Warnung weiter. Veröffentlichung und Sicherung als Vorlage benötigen zuerst einen gespeicherten Entwurf; offene Änderungen werden vor dem Absenden mit einem Hinweis auf das Speichern angehalten. Fehlgeschlagene Speicherungen oder Weiterleitungen zur Anmeldung behalten den Schutz und die Eingaben.
