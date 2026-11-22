# Passkeys und Pflicht-2FA im Realm AppsFab

Konfiguriert in `AppsFab-realm.json`, angewendet von keycloak-config-cli (siehe `../RECONCILE.md`).
Getestet 2026-11-22 gegen Keycloak 26.8.2 + kcc 6.5.0-26.5.4 mit einem virtuellen Passkey (Playwright/CDP).

## Grundsatz: ein Passwort allein reicht nie

| Weg | Was nötig ist |
|---|---|
| Passkey (Autofill im Username-Feld oder Button „Sign in with Passkey") | nur der Passkey (Gerät + Face ID/Touch ID/PIN) |
| Username + Passwort, User hat einen zweiten Faktor | Passwort **und** Passkey, Sicherheitsschlüssel, OTP-App oder Recovery-Code |
| Username + Passwort, User hat noch **keinen** zweiten Faktor | Passwort, danach **Pflicht**: Passkey registrieren (Required Action `webauthn-register`), sonst kein Login |
| Password-Grant (ROPC, `grant_type=password`) | für alle Clients gesperrt (`directGrantFlow` = `direct-grant-disabled`) |

Selbstregistrierung (`registrationAllowed`) und „Passwort vergessen" (`resetPasswordAllowed`) sind aus.

## Browser-Flow `browser-passkey`

```
Cookie | IdP-Redirector | browser-passkey-forms
  browser-passkey-forms
    Username Form (mit Passkey-Autofill, webAuthnPolicyPasswordlessPasskeysEnabled)
    browser-passkey-password-2fa   CONDITIONAL: nur wenn KEIN Passkey benutzt wurde (conditional-credential)
      Password Form
      browser-passkey-second-factor  CONDITIONAL: nur wenn der User einen 2. Faktor hat
        Passkey | WebAuthn-Schlüssel | OTP | Recovery-Code   (je ALTERNATIVE)
      browser-passkey-enroll         CONDITIONAL: nur wenn second-factor NICHT lief
        WebAuthn Authenticator REQUIRED, userSetupAllowed -> erzwingt die Registrierung
```

Warum `webauthn-authenticator` (2FA-Typ) beim Zwangs-Einrichten und nicht der Passwordless-Typ: Der
Passwordless-Authenticator erlaubt in Keycloak kein „Setup beim Login" (`isUserSetupAllowed() = false`),
ein REQUIRED-Schritt damit endet bei Usern ohne Passkey in „credential setup required". Der dort
angelegte Passkey ist ein 2FA-Passkey: er gilt nach dem Passwort, nicht für den Autofill-Login. Wer
Passkey-only will, legt zusätzlich einen Passkey in der Account-Konsole an (siehe unten).

Bekannte Kleinigkeit: Wer erst den Username tippt und dann auf der Passwortseite „Sign in with
Passkey" klickt, wird ein zweites Mal nach dem Passkey gefragt. Der Autofill direkt im Username-Feld
fragt nur einmal.

## Policies

- **Passwordless-Policy** (`webAuthnPolicyPasswordless*`): `RequireResidentKey = Yes` (echte Passkeys),
  `userVerification = preferred`, ES256/RS256, `PasskeysEnabled = true` (Autofill).
- **2FA-Policy** (`webAuthnPolicy*`): gleiche RpId, ebenfalls Resident Key, damit das Zwangs-Einrichten
  einen synchronisierbaren Passkey anlegt.
- **RpId** beider Policies = `appsfab.org`: Passkeys gelten für jeden Login-Host unter appsfab.org,
  aktuell `auth.appsfab.org`. Seit 2026-11 fest gesetzt. Passkeys, die vorher auf
  `auth.lab.appsfab.org` angelegt wurden, funktionieren NICHT mehr (Account-Konsole → Signing in:
  alten löschen, neuen anlegen).
- Keycloak warnt im Log, dass `requireResidentKey` veraltet ist (`residentKey` wäre neu). kcc
  6.5.0-26.5.4 kennt das neue Feld noch nicht und bricht damit ab. Umstellen, sobald Renovate eine
  kcc-Version bringt, die `webAuthnPolicyPasswordlessResidentKey` kennt.

## Eigenen Zugang absichern (einmalig, vor dem Merge)

1. Auf `https://auth.appsfab.org/realms/AppsFab/account` anmelden → **Signing in**.
2. Alte Passkeys aus der Zeit von `auth.lab.appsfab.org` **löschen**. Ein toter Passkey zählt als
   „zweiter Faktor eingerichtet" und würde nach dem Passwort verlangt.
3. **Passkey** anlegen (Abschnitt „Passkey" bzw. „Passwordless") und einmal abmelden + mit Passkey
   anmelden.
4. **Recovery Authentication Codes** einrichten und im 1Password-Vault `AppsFab` ablegen. Das ist der
   Notausgang, wenn das Gerät mit dem Passkey weg ist.
5. Optional: OTP-App als weiteren Faktor.

## Notausgänge, falls doch etwas klemmt

- **Recovery-Code**: Passwort → „Try Another Way" → Recovery Authentication Code.
- **Admin-Konsole** (nur LAN, `https://auth.lab.appsfab.org/admin`, Realm `master`, eigener Login, vom
  AppsFab-Flow nicht betroffen): Users → *User* → Credentials → kaputten Passkey löschen, oder
  Required Action „Webauthn Register Passwordless" setzen.
- **kcadm** auf dem NAS mit dem kcc-Service-Account (siehe `../RECONCILE.md`, Gate-Tests):
  `kcadm.sh get users/<id>/credentials -r AppsFab` und `kcadm.sh delete users/<id>/credentials/<cred-id> -r AppsFab`.
- **Rollback**: `browserFlow` im Realm-JSON auf `"browser"` setzen, `KCC_REALM_REV` hochzählen, deployen.

## DR / Frisch-Start

`--import-realm` stellt die Konfiguration (Flows, Policies) wieder her, nicht die registrierten Geräte.
Diese sind user-gebundene Credentials und müssen nach einem Neuaufbau ohne DB neu registriert werden.
