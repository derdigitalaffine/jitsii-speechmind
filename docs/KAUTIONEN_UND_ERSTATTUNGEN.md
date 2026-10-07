# Separate Kautionen und Erstattungen

Neue Ressourcenbuchungen erhalten bei einer Kaution einen eigenen Zahlungsvorgang. Miete und Kaution haben unterschiedliche Zahlungsnummern, Zahlwege, Status und Quittungen. Bestehende kombinierte Zahlungen bleiben erhalten; deren Kaution kann weiterhin aus derselben Zahlung erstattet werden.

In der Ressource wird der vorgegebene Kautionszahlweg festgelegt. Optional darf der Gast zusätzlich freigegebene Zahlwege wählen. Eine offene Barkaution lässt die Reservierung nicht automatisch verfallen. Auch bei monatlicher Vereinsabrechnung wird die Kaution separat angelegt.

## Vor Ort und nachträglich

Hausmeister können außerhalb des Portals kassieren und zurückzahlen. Berechtigte Bearbeitende erfassen anschließend Zahlungseingang bzw. „Bereits bar ausgezahlt“ mit tatsächlichem Datum und einer Bemerkung zur handelnden Person. Quittungen zeigen tatsächlichen Zeitpunkt und Erfassungszeitpunkt getrennt. Die Abnahme kann mit „Kaution noch nicht ausgezahlt“ gespeichert werden; die Rückzahlung wird anschließend separat erfasst. Es ist keine zusätzliche Vier-Augen-Freigabe erforderlich, sofern die vorhandene optionale Kautionsfreigabe nicht eingeschaltet wurde.

Bei Stornierung einer bar oder per Überweisung bezahlten separaten Kaution wird die Rückzahlung nicht als bereits erfolgt behauptet: Die Verwaltung muss sie tatsächlich ausführen und bestätigen.

## PayPal

Jeder Erstattungsauftrag erhält eine dauerhaft gespeicherte UUID. Bei einer unklaren Antwort bleibt der Betrag reserviert und weitere Erstattungen sind gesperrt. „Erstattungsstatus abgleichen“ fragt bei bekannter PayPal-ID den Status ab; andernfalls wird innerhalb von 24 Stunden ausschließlich derselbe Auftrag mit identischem Payload und derselben UUID wiederholt. Ältere unklare Aufträge ohne Anbieter-ID müssen in PayPal geprüft werden. Der Auftrag darf nicht durch eine neue Auszahlung ersetzt werden.

Nur COMPLETED wird verbucht; PENDING und unklare Ergebnisse erzeugen keine Rückzahlungsquittung. Definitive Ablehnungen geben die Reservierung frei. Anbieterreferenzen werden in Fehlermeldungen angezeigt. Bestätigte Rückzahlungen werden auch bei wiederholten Statusmeldungen nur einmal verbucht.

Eingang, Rückzahlung und Einbehalt haben eigene nummerierte PDF-Belege. Eingangs- und Rückzahlungsquittungen werden der jeweiligen Benachrichtigung beigefügt und sind über den betreffenden Zahlungsvorgang abrufbar. Ein abweichender manueller Rückzahlungsweg erfordert eine Begründung.

## Noch zu prüfen

Vor Produktivfreigabe: PayPal-Sandbox mit echter Teilrückzahlung, Zeitüberschreitung und Webhook; visuelle Prüfung auf Mobilgerät; bestehende Datenbankmigration. Eine Änderung bereits bezahlter Kautionsbeträge weist derzeit auf den separat erforderlichen Ausgleich hin.
