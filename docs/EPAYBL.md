# ePayBL: vorbereitet, noch nicht verfügbar

Die Vorbereitung nutzt die zentrale Zahlungsfunktion für Ressourcenbuchungen, Kautionen, Formulare, Anträge und Prozessschritte. ePayBL wird als noch nicht verfügbar angezeigt und auf öffentlichen Zahlseiten nicht als ausführbarer Zahlweg angeboten. Importierte Aktivierungswerte und hinterlegte Mandantenangaben können die Sperre nicht umgehen. Der vorbereitete Adapter führt keine Netzwerkanfragen aus.

In den Zahlungseinstellungen können Betreiber, Mandantenkennung, Schnittstellenversion und Buchungszuordnung vorgemerkt werden. Es werden keine vermuteten API-Endpunkte oder Authentifizierungsverfahren verwendet. `epaybl.payment_context()` stellt die bestehende Zahlungsnummer, Modulzuordnung, Betrag in Cent, Währung, Zweck und Kostenstelle bereit; dies ist ausdrücklich kein ePayBL-Sendeformat.

## Voraussetzung für die ausführbare Anbindung

- Betreiber-Dokumentation mit der eingesetzten Version und vereinbarten Schnittstelle (z. B. XBezahldienste).
- Testmandant und bestätigte Authentifizierung einschließlich eventuell benötigter Zertifikate.
- Zahlungsübergabe, Rückkehr, authentifizierte Statusmeldungen und Statusabgleich.
- Teil- und Vollerstattungen mit dauerhafter Idempotenz und korrekter Buchungszuordnung.
- Ende-zu-Ende-Tests für alle Module, Kautionen sowie Abbruch, Timeout und wiederholte Meldungen.

Die Adaptergrenzen sind `ready`, `start`, `refund` und `reconcile`. Erst die fertige Implementierung darf `ready` nach geprüfter Konfiguration auf wahr setzen. Erstattungen sollen die dauerhaften Aufträge aus dem separaten Kautions-/Erstattungs-PR wiederverwenden.

Offizielle Grundlage: https://www.epaybl.de/faq-25840.html (Schnittstellendokumentation über die Geschäftsstelle, Betrieb durch die jeweiligen Mitglieder).
