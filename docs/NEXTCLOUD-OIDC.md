# Anmeldung über Nextcloud / OpenID Connect

Das Portal kann einen externen OpenID-Connect-Anbieter zur Anmeldung verwenden. Nextcloud ist vorkonfiguriert; für andere Anbieter wie Keycloak wird eine vollständige Discovery-URL eingetragen. Die Einrichtung erfolgt unter **Administration → Nextcloud / OIDC-Anmeldung** (`/admin/oidc`). Ohne Konfiguration bleibt die Funktion ausgeschaltet. Lokale Anmeldung und lokale Administratorkonten bleiben verfügbar.

## Nextcloud vorbereiten

In Nextcloud wird die App **OIDC Identity Provider** (`oidc`, Projekt H2CK/oidc) benötigt. Die App **OpenID Connect user backend** (`user_oidc`) meldet Nextcloud selbst an einem anderen Anbieter an und ersetzt den Identity Provider nicht.

1. Die öffentliche Portaladresse korrekt konfigurieren. Die Einstellungsseite zeigt die daraus abgeleiteten Rücksprungadressen zum Kopieren.
2. In der Nextcloud-App einen vertraulichen Client für das Portal anlegen. Authorization Code, PKCE mit S256 und RS256-Signaturen verwenden; die RSA-Schlüssel müssen mindestens 2048 Bit haben.
3. Die angezeigte **Rücksprungadresse** exakt beim Client hinterlegen, zum Beispiel `https://portal.bachberg.de/auth/oidc/callback`.
4. Client-ID und Client-Secret im Portal eintragen. Standard ist `client_secret_basic`; falls beim Anbieter entsprechend konfiguriert, steht `client_secret_post` zur Auswahl.
5. Die Nextcloud-Basisadresse eintragen. Ohne eigene Discovery-URL verwendet das Portal `<Nextcloud-Adresse>/index.php/apps/oidc/openid-configuration`. Beim ersten Test darf **Anbieterkennung / Issuer** leer bleiben; der geprüfte Discovery-Eintrag wird übernommen. Später muss der Issuer exakt übereinstimmen, einschließlich eines gegebenenfalls vorhandenen abschließenden Schrägstrichs.
6. Zulassung, Gruppen und Profilübernahme einstellen. **Speichern & Verbindung prüfen** liest Discovery und Signaturschlüssel. Dieser Test prüft noch keine Benutzeranmeldung und keine Client-Zugangsdaten.
7. Nach erfolgreichem Test **OIDC-Anmeldung aktivieren** auswählen und speichern. Den vollständigen Login zunächst mit einem geeigneten Testkonto prüfen; das lokale Administratorkonto währenddessen verfügbar halten.

Die Anmeldung fordert die Scopes `openid profile email groups` an. Der Anbieter muss eine gültige E-Mail-Adresse liefern; standardmäßig wird zusätzlich `email_verified=true` verlangt. Die zugehörige Option lässt sich bewusst ausschalten, wenn der Anbieter keine Bestätigung ausliefert. Gruppen werden als Liste von Kennungen erwartet. Bei Nextcloud sind dies üblicherweise interne GIDs, nicht die sichtbaren Gruppennamen.

Alle Anbieteradressen benötigen HTTPS. Discovery- und Tokenanfragen folgen keinen Weiterleitungen. Liegen Endpunkte absichtlich auf zusätzlichen Servern, deren HTTPS-Ursprünge unter **Zusätzliche freigegebene Endpunktserver** eintragen. Das Client-Secret wird mit dem bestehenden Portalschlüssel verschlüsselt gespeichert und nicht erneut angezeigt; ein leeres Secret-Feld behält den vorhandenen Wert. Nach Konfigurationsänderungen kann ein erneuter Verbindungstest notwendig sein.

## Bestehende und neue Konten

Eine externe Identität wird über **Issuer und Subject (`iss` + `sub`)** zugeordnet. Gleiche E-Mail-Adressen führen niemals automatisch zum Zusammenlegen von Konten.

Für ein bestehendes Konto:

1. Mit dem bestehenden Portalkonto anmelden.
2. **Profil → Sicherheit → Kontoverknüpfung** öffnen (`/profile/identity`). Für die Verknüpfung muss die Anmeldung frisch sein; gegebenenfalls erneut anmelden.
3. **OIDC-Konto auswählen & verknüpfen** wählen und beim Anbieter das richtige Konto anmelden.
4. Die angezeigte Verknüpfung ausdrücklich bestätigen. Bestehende Buchungen, Umläufe und andere Objekte bleiben beim selben Portalkonto.

Die Administration kann die Verknüpfungsansicht eines Zielbenutzers über `/profile/identity?user_id=<Benutzer-ID>` öffnen. Auch dort sind Anbieteranmeldung und ausdrückliche Bestätigung erforderlich. Ein Anbieterwechsel wird nicht durch Änderung einer E-Mail-Adresse auf bestehende Identitäten übertragen.

Optional werden zugelassene neue Benutzer beim ersten Login angelegt. Sie erhalten ausschließlich die konfigurierte Standardgruppe und Startrechte; OIDC setzt kein Administratorkennzeichen. Ohne Startrechte gelten die minimalen Benutzerrechte. Ist das automatische Anlegen ausgeschaltet, muss zuvor eine ausdrückliche Kontoverknüpfung erfolgen. Gesperrte Portalkonten bleiben gesperrt.

Zum Entfernen einer Verknüpfung muss ein lokales Passwort vorhanden sein. Die zugehörigen OIDC-Sitzungen werden beendet. Ein ausschließlich über OIDC angelegtes Konto kann nach frischer OIDC-Anmeldung im Profil ein erstes lokales Passwort setzen. Vorhandene lokale Passwörter werden weiterhin mit dem bisherigen Passwort bestätigt.

## Gruppen, Profil und Formularvorbelegung

**Zugelassene Nextcloud-Gruppen** beschränkt den Zugang auf mindestens eine der angegebenen GIDs. Ein leeres Feld lässt alle sonst berechtigten Benutzer des Anbieters zu. Anbietergruppen können bestehenden Portalgruppen zugeordnet werden. Beim nächsten OIDC-Login werden diese verwalteten Mitgliedschaften aktualisiert; manuell zugewiesene Mitgliedschaften bleiben erhalten. Bestehende direkte Portalrechte werden nicht durch die Startrechte neuer Konten ersetzt.

Anzeigename und Anmelde-E-Mail können bei jeder Anmeldung aktualisiert werden. Eine neue E-Mail-Adresse, die bereits zu einem anderen Konto gehört, wird abgewiesen. Zusätzlich lassen sich Claims für Vorname, Nachname, Organisation, Abteilung, Funktion, Diensttelefon, Sprache und Zeitzone konfigurieren. Nur konfigurierte und gelieferte Angaben werden übernommen. Andere freiwillige Angaben und die Zustimmung zur Formularvorbelegung bleiben erhalten. Eine OIDC-Anmeldung erteilt diese Zustimmung nicht automatisch. Weitere Details: [Benutzerprofile](BENUTZERPROFILE.md).

## Sitzungen, Zwei-Faktor und Abmeldung

Die bestehende Portal-Zwei-Faktor-Regel gilt auch nach einer erfolgreichen OIDC-Anmeldung. Eine am Anbieter durchgeführte Anmeldung ersetzt den gegebenenfalls erforderlichen zweiten Faktor des Portals nicht.

OIDC-Sitzungen enden standardmäßig spätestens nach **acht Stunden**; einstellbar sind eine bis 24 Stunden. Die gewöhnliche Portal-Abmeldung beendet die Portalsitzung. Wenn aktiviert und vom Anbieter angeboten, erscheint zusätzlich eine zentrale Abmeldeaktion für den Anbieter.

Für zentrale Abmeldungen kann die auf der Einstellungsseite angezeigte **Backchannel-Logout-Adresse** beim Anbieter registriert werden, zum Beispiel `https://portal.bachberg.de/auth/oidc/backchannel`. Voraussetzung ist eine Provider-/App-Version, die signierte OIDC-Backchannel-Logout-Nachrichten tatsächlich unterstützt und sendet. Das Portal validiert Signatur, Issuer, Client, Zeitstempel und Sitzungs-/Benutzerbezug; wiederholte Nachrichten führen nicht zu einer zweiten Aktion. Lokale Passwortsitzungen werden durch einen Anbieter-Logout nicht beendet.

Eine Sperrung oder Gruppenänderung beim Anbieter beendet bereits laufende Portalsitzungen **nicht automatisch sofort**, wenn der Anbieter kein passendes Logout sendet. Profil- und Gruppenänderungen werden beim nächsten OIDC-Login übernommen; die maximale Sitzungsdauer begrenzt laufende Sitzungen. Für einen unmittelbaren Entzug im Portal das Portalkonto sperren oder dessen Sitzungen beenden. Das Ausschalten von OIDC verhindert weitere OIDC-Anmeldungen und macht bestehende OIDC-Sitzungen beim nächsten Zugriff ungültig.

## Betrieb und Grenzen

Die Datenbank wird beim üblichen Portalstart additiv erweitert. Datenbank und `PORTAL_SECRET_KEY` gemeinsam sichern; neben dem Client-Secret werden auch gespeicherte Anbieterinformationen verschlüsselt. Die Browser-Sitzung enthält keine Anbieter-Tokens. Das Portal verwendet keine Refresh-Tokens und fordert keinen `offline_access` an.

Die Integration unterstützt einen zentral konfigurierten Anbieter. SCIM-Provisionierung, Hintergrundsynchronisation und ein automatischer Import aller Nextcloud-Benutzer sind nicht enthalten. Es werden keine Nextcloud-Dateien oder Kalender freigegeben.

Ohne konkreten Nextcloud-Mandanten und dessen Client-Zugangsdaten ist kein echter Provider-Login geprüft. Automatisierte Tests mit signierten RSA-Tokens und nachgebildeten Anbieterantworten prüfen die Anmeldung, Zugriffsgrenzen, Verknüpfung und Abmeldung; der vollständige Abnahmetest gegen die eigene Nextcloud folgt nach der Einrichtung.

## Quellen

- [Nextcloud OIDC Identity Provider: Einrichtung und Endpunkte](https://github.com/H2CK/oidc)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [OpenID Connect Back-Channel Logout 1.0](https://openid.net/specs/openid-connect-backchannel-1_0.html)
