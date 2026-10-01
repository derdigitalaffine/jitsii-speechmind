# Mitgelieferte Frontend-Bibliotheken

Alle Dateien liegen lokal im Repository und werden vom Portal selbst ausgeliefert
(keine CDN-Aufrufe, keine Verbindung zu Drittanbietern – wichtig für den Datenschutz).

| Bibliothek | Version | Zweck |
|---|---|---|
| Bootstrap | 5.3.8 | Layout, Komponenten, Hell/Dunkel-Modus |
| Font Awesome Free | 7.3.1 | Icons |
| DataTables (+ Bootstrap 5, Responsive) | 3.1.2 / 4.1.1 | Tabellen mit Suche, Sortierung, Seiten |
| Tagify | 4.39.0 | E-Mail-Adressen als Tags eingeben (Mehrfach-Einladung) |
| Tom Select | 2.6.2 | Komfortable Auswahlfelder |
| SweetAlert2 | 11.26.25 | Bestätigungsdialoge |
| Coloris | 0.25.0 | Farbwähler für das Design |

Aktualisieren: `npm i <paket>` in einem Temp-Ordner und die Dateien aus `node_modules/<paket>/dist` hierher kopieren.
