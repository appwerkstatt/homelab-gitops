# 03-oauth2-proxy

| | |
|---|---|
| **Zweck** | Traefik-ForwardAuth: schützt Dienste ohne eigenes OIDC mit einem Keycloak-Login |
| **Adresse** | `/oauth2/*` auf jedem Lab-Host; Middlewares `sso@docker`, `sso-devs@docker`, `sso-admin@docker` |
| **Login** | Keycloak-Client `oauth2-proxy`; `sso` nur Gruppe `lab-users`, `sso-devs` nur `devs`, `sso-admin` nur `lab-admins` |
| **Daten** | keine (Sitzung im Cookie auf `.lab.appsfab.org`) |
| **Quelle** | [`stacks/03-oauth2-proxy/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/03-oauth2-proxy/compose.yaml) |

Hinter `sso@docker` stehen derzeit: Plane, Handbuch, Familien-Startseite (`home.lab`).
Hinter `sso-devs@docker`: n8n-Editor.
Hinter `sso-admin@docker` (Admin-Werkzeuge): Traefik-Dashboard, paperless-ai, Plane-God-Mode, Admin-Startseite (`admin.lab`).
Welche Middleware wofür: [Rechtekonzept](../sicherheit/rechtekonzept.md).

## Einen Dienst dahinter hängen

1. Am Router des Dienstes: `traefik.http.routers.<name>.middlewares=sso@docker` (Entwickler: `sso-devs@docker`, Admin-Werkzeug: `sso-admin@docker`).
2. In `stacks/02-keycloak/realm/AppsFab-realm.json` beim Client `oauth2-proxy` die Redirect-URI
   `https://<host>.lab.appsfab.org/oauth2/callback` und den Web-Origin ergänzen.
3. `KCC_REALM_REV` hochzählen. Ohne Schritt 2 lehnt Keycloak den Login mit „Invalid redirect_uri“ ab.

## Stolperfallen

- `groups` ist **kein** anforderbarer Scope (der Claim kommt per Mapper). Steht es in `--scope`, scheitert
  der Login mit `invalid_scope`.
- Die Gruppen stehen in der Sitzung (Cookie). `--cookie-refresh=1h` holt sie stündlich neu aus Keycloak,
  eine Gruppenänderung wirkt also nach spätestens einer Stunde. Sofort: `https://<host>.lab.appsfab.org/oauth2/sign_out`
  öffnen und neu anmelden. Welche Gruppen die Sitzung hat, zeigt `/oauth2/userinfo`.
- Ist die Keycloak-Sitzung beim stündlichen Erneuern abgelaufen (nach 30 min Leerlauf), kommt ein neuer Login.
- Nach Umzügen zwischen Netzen oder Arcane-Projekten auf verwaiste zweite oauth2-proxy-Container achten
  ([Fehlersuche](../betrieb/fehlersuche.md#doppelte-container)).
