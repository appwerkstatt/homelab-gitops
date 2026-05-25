# Passkeys (WebAuthn passwordless) im Realm AppsFab

Konfiguriert in `AppsFab-realm.json`:

- **Policy** (`webAuthnPolicyPasswordless*`): `requireResidentKey = Yes` (= echte Passkeys / discoverable credentials),
  `userVerificationRequirement = preferred`, Signatur-Algorithmen ES256/RS256.
  `RpId` ist leer → Keycloak leitet sie automatisch vom Host ab (`auth.lab.appsfab.org`).
- **Required Action** `webauthn-register-passwordless`: aktiviert (User können in der Account-Console einen Passkey anlegen).
  Nicht als Default erzwungen — soll jeder neue User direkt zur Passkey-Registrierung aufgefordert werden,
  `defaultAction` auf `true` setzen.
- **Browser-Flow** `browser-passkey` (als `browserFlow` gebunden): Cookie/IdP → Username-Form →
  **Passkey (ALTERNATIVE) ODER Passwort (ALTERNATIVE)**. Passkey steht zuerst = „bevorzugt", Passwort bleibt Fallback.

## WICHTIG — vor Produktivnutzung verifizieren

Authentication-Flows sind in Keycloak **versionsabhängig** (Authenticator-Provider-IDs und JSON-Feldnamen
variieren minimal zwischen Releases). Diese Vorlage ist für **Keycloak 26.5.4** gebaut, sollte aber beim
ersten Import geprüft werden:

1. Realm importieren (`--import-realm` greift nur, wenn der Realm noch nicht existiert).
2. In der UI prüfen: *Authentication → Flows → browser-passkey* — sind alle Schritte vorhanden und nicht „DISABLED"?
3. *Authentication → Policies → WebAuthn Passwordless Policy* — sind die Werte gesetzt?

**Goldstandard (empfohlen):** Den Flow einmal in der UI klicken (oder importieren + anpassen), dann den Realm
**exportieren** (`kc.sh export`) und das Ergebnis committen — der Export passt dann garantiert zu deiner Version.

## Wichtig zur Migration

- Bei der **DB-Migration** (Phase 3, PG 17) kommen Policy **und** bereits registrierte Passkeys deiner Nutzer
  mit — dann ist dieser Import gar nicht nötig (er wird übersprungen, weil der Realm existiert).
- Diese Vorlage zählt für den **DR-/Frisch-Start**: Sie stellt die Passkey-*Konfiguration* wieder her.
  Die einzelnen registrierten Geräte sind user-gebundene Credentials und müssen dann neu registriert werden.
