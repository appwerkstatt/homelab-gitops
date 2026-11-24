# 02-keycloak

| | |
|---|---|
| **Zweck** | Zentrale Identität (Realm `AppsFab`) für alle Dienste und den Cluster |
| **Adresse** | Login `https://auth.appsfab.org` (öffentlich + LAN, Issuer für alle Clients); Admin-Konsole nur LAN `https://auth.lab.appsfab.org/admin` |
| **Login** | Passkey allein **oder** Passwort + zweiter Faktor; Password-Grant (ROPC) gesperrt |
| **Daten** | `fast/appdata/keycloak/db` (Postgres 17) |
| **Backup** | Tier 2 + nächtlicher `pg_dump` offsite |
| **Abhängig von** | Traefik, Tunnel (für Logins aus dem Internet) |
| **Quelle** | [`stacks/02-keycloak/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/02-keycloak) |

## Bausteine

- **keycloak** + **keycloak-db** (Postgres 17, nicht auf 18 heben: braucht `pg_upgrade`).
- **keycloak-config-cli (kcc)**: Einmal-Container, der bei jedem Deploy `realm/AppsFab-realm.json` auf den
  laufenden Keycloak anwendet und sich beendet. Der Realm ist damit Code.
- Events (Logins, Fehlversuche, Sperren) gehen als Logzeilen über Alloy nach Loki; daraus entstehen die Alarme
  `KeycloakLoginFailures` und `KeycloakUserLockedOut`.

## Realm ändern

1. `realm/AppsFab-realm.json` ändern.
2. **Im selben Commit** `KCC_REALM_REV` im `compose.yaml` hochzählen.
3. PR, Merge; Arcane deployt, kcc läuft und endet mit Exit 0.

Neue OIDC-Client-Secrets (`*_OIDC_CLIENT_SECRET`) gehören in die Arcane-Env von `keycloak` **und** des
Consumers. Fehlt eins, setzt kcc das Secret leer. Details und Gate-Tests:
[`RECONCILE.md`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/02-keycloak/RECONCILE.md).

## Gruppen

| Gruppe | Wirkung |
|---|---|
| `lab-users` | Login bei allen Nutzer-Diensten (`sso@docker`, Grafana, Forgejo); Leserechte in Zot |
| `lab-admins` | zusätzlich `sso-admin@docker`; Admin in Grafana, Forgejo, Zot, Netboot |

Admins sind in beiden Gruppen. Details: [Rechtekonzept](../sicherheit/rechtekonzept.md).

## Weiterführend

- [Login & SSO](../sicherheit/sso.md): Login-Flow, Passkeys, Notausgänge
- [`realm/PASSKEYS.md`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/02-keycloak/realm/PASSKEYS.md): Flow-Details und Testnotizen
