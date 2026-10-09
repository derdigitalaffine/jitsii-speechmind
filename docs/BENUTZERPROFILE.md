# Freiwillige Benutzerprofile und Formularvorbelegung

Unter **Profil → Freiwillige Angaben** pflegt jede angemeldete Person ihre eigenen Angaben. Alle neuen Felder sind optional. Kontodaten, Passwort, Anmeldung und Berechtigungen werden weiterhin separat verwaltet.

## Umfang

| Bereich | Angaben / interne Feldschlüssel |
| --- | --- |
| Person | Anrede (`salutation`), Titel vor/nach dem Namen (`honorific_prefix`, `honorific_suffix`), Vorname (`given_name`), weitere Vornamen (`middle_name`), Nachname (`family_name`), Rufname (`nickname`), Geburtsdatum (`birthdate`), freiwillige Geschlechts-/Selbstbezeichnung (`gender`) |
| Kontakt | Diensttelefon (`work_phone`), Mobiltelefon (`mobile_phone`), Privattelefon (`private_phone`), zusätzliche Kontakt-E-Mail (`contact_email`), Website (`website`) |
| Privatanschrift | Straße, Hausnummer, PLZ, Ort, Ortsteil, Region und zweistelliger ISO-Ländercode: `home_street`, `home_house_no`, `home_zip`, `home_city`, `home_district`, `home_region`, `home_country` |
| Dienstanschrift | Entsprechende `work_*`-Adressfelder; Dienststätte/Gebäude (`work_location`) und Raum (`room`) |
| Beschäftigung | Organisation (`organization`), Bereich (`division`), Abteilung (`department`), Funktion (`job_title`), Personalnummer (`employee_number`), Kostenstelle (`cost_center`), Beschäftigungsart (`employment_type`), Name der vorgesetzten Person (`manager_name`) |
| Bankverbindung | Kontoinhaber:in (`account_holder`), IBAN (`iban`), BIC (`bic`), Bank (`bank_name`) |
| Sprache / Zeitzone | Sprachkennung wie `de-DE` (`locale`), Zeitzone wie `Europe/Berlin` (`zoneinfo`) |

Personalnummern bleiben Text, damit führende Nullen erhalten bleiben. E-Mail, Datum, Länderformat, Sprachkennung, Zeitzone, IBAN-Prüfziffer und BIC werden serverseitig geprüft. Die zusätzliche Kontakt-E-Mail ersetzt weder die Anmelde-E-Mail noch deren Verifikation. Sprache und Zeitzone sind derzeit Profilangaben; sie stellen die Portaloberfläche nicht automatisch um.

## Vorbelegung verwenden

1. Gewünschte Angaben im eigenen Profil eintragen.
2. **Meine freiwilligen Angaben für meine Formulare vorbelegen** einschalten und **Freiwillige Angaben speichern** wählen.
3. Im Formular- oder Datenblockbaukasten die passende Vorbelegung auswählen. Die Auswahl ist nach Profilbereichen gruppiert.

Kurze/lange Textfelder können einzelne Angaben oder zusammengesetzte Anschriften übernehmen. Datumsfelder unterstützen das Geburtsdatum; Adressfelder die Privat- oder Dienstanschrift. Adressvorbelegungen beachten den Modus „nur PLZ/Ort“ und die Ortsteil-Einstellung. Es werden keine GPS-Koordinaten aus Profilanschriften geraten.

Vorbelegt wird ausschließlich aus dem Profil der aktuell angemeldeten Person, auch bei Nachforderungen. Bereits vorhandene Antworten, ausdrücklich leere Antworten und Vorgangsvorbelegungen haben Vorrang. Vorbelegte Antworten sind bearbeitbar. Ohne Zustimmung werden neue freiwillige Angaben nicht übernommen. Die bisherigen Vorbelegungen für Anzeigename und Anmelde-E-Mail bleiben verfügbar.

## Datenschutz und Betrieb

Die neuen Angaben liegen als verschlüsseltes JSON in `users.profile_data_enc`, mit der vorhandenen Portalverschlüsselung auf Basis von `PORTAL_SECRET_KEY`. Bestehende Konten bekommen eine leere, nullable Spalte; die Migration ist wiederholbar. Den Portalschlüssel zusammen mit der Datenbank sichern: Bei einem Schlüsselwechsel ohne Migration können verschlüsselte Angaben nicht mehr gelesen werden.

Es gibt keine öffentliche Profilabfrage und kein neues personenbezogenes Benutzerverzeichnis. Export und Löschung unter `/profile/details/export` bzw. `/profile/details/clear` betreffen nur die eigene angemeldete Person; schreibende Aktionen benötigen CSRF. Der JSON-Export enthält ausschließlich die freiwilligen Angaben und die Zustimmung. Passwort, API-Schlüssel und Berechtigungen gehören nicht hinein.

**Alle freiwilligen Angaben löschen** entfernt auch die Zustimmung zur Vorbelegung. Schon abgesendete Formularantworten und deren Nachweise bleiben erhalten. Sobald eine Person Profilangaben als Formularantwort absendet, gelten die Rechte und Aufbewahrungsregeln dieses Formulars/Vorgangs. Die Angaben sind Selbstauskünfte und vergeben weder Gruppenmitgliedschaften noch Freigabezuständigkeiten.

## OIDC-Anbindung und weitere Identitätsstandards

**Die OIDC-Anmeldung über Nextcloud oder einen konfigurierten OIDC-Anbieter ist vorhanden.** Einrichtung und Grenzen stehen unter [Nextcloud / OIDC](NEXTCLOUD-OIDC.md). Die Administration kann ausgewählte Profilfelder aus Anbieter-Claims aktualisieren; andere freiwillige Angaben und die Zustimmung zur Formularvorbelegung bleiben erhalten. SCIM-Provisionierung ist nicht implementiert. Die Tabelle beschreibt mögliche Standardzuordnungen; sie bedeutet nicht, dass alle Felder automatisch synchronisiert werden.

| Portalangaben | Mögliche Standardzuordnung |
| --- | --- |
| Vor-, weitere und Nachnamen, Rufname | OIDC `given_name`, `middle_name`, `family_name`, `nickname`; SCIM `name` |
| Konto-Anzeigename / Konto-E-Mail | OIDC `name` / `email`; getrennt von freiwilliger Kontakt-E-Mail |
| Geburtsdatum, Geschlecht, Website, Sprache, Zeitzone | OIDC `birthdate`, `gender`, `website`, `locale`, `zoneinfo` |
| Telefonnummern | OIDC `phone_number` für eine konfigurierte Hauptnummer; SCIM typisierte `phoneNumbers` |
| Privat-/Dienstanschrift | SCIM typisierte `addresses`; OIDC `address` für eine konfigurierte Hauptanschrift |
| Titel vor/nach dem Namen | SCIM `name.honorificPrefix`, `name.honorificSuffix` |
| Personalnummer, Kostenstelle, Organisation, Bereich, Abteilung | SCIM Enterprise User: `employeeNumber`, `costCenter`, `organization`, `division`, `department` |
| Funktion | SCIM `title` |
| Name der vorgesetzten Person | Anzeigeinformation; keine Identitätsreferenz und keine Rechtezuweisung |
| Bank, Dienststätte, Raum, Beschäftigungsart | Eigene Erweiterungsfelder; keine automatische Weitergabe an Identitätsanbieter |

Die OIDC-Anbindung führt externe Identitäten (`iss` + `sub`) getrennt und serverseitig. Diese Identifikatoren sind keine selbst editierbaren Profilfelder. Rollen/Gruppen, Rechte, Tokens und Passwörter bleiben von freiwilligen Angaben getrennt. E-Mail oder Personalnummer allein dürfen keine Identitätsverknüpfung auslösen.

Grundlagen: [OpenID Connect Core, Standard Claims](https://openid.net/specs/openid-connect-core-1_0.html#StandardClaims) und [SCIM Core Schema, RFC 7643](https://www.rfc-editor.org/rfc/rfc7643.html). Die weiterführenden SCIM-Zuordnungen sind ein Datenmodell-Vorschlag; eine SCIM-Schnittstelle besteht nicht.
