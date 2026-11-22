# 03-oauth2-proxy

| | |
|---|---|
| **Zweck** | Traefik-ForwardAuth: schützt Dienste ohne eigenes OIDC mit einem Keycloak-Login |
| **Adresse** | `/oauth2/*` auf jedem Lab-Host; Middleware `sso@docker` |
| **Login** | Keycloak-Client `oauth2-proxy`, nur Gruppe `lab-users` |
| **Daten** | keine (Sitzung im Cookie auf `.lab.appsfab.org`) |
| **Quelle** | [`stacks/03-oauth2-proxy/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/03-oauth2-proxy/compose.yaml) |

Hinter `sso@docker` stehen derzeit: Traefik-Dashboard, paperless-ai, n8n-Editor, Plane, Handbuch, Homepage.

## Einen Dienst dahinter hängen

1. Am Router des Dienstes: `traefik.http.routers.<name>.middlewares=sso@docker`.
2. In `stacks/02-keycloak/realm/AppsFab-realm.json` beim Client `oauth2-proxy` die Redirect-URI
   `https://<host>.lab.appsfab.org/oauth2/callback` und den Web-Origin ergänzen.
3. `KCC_REALM_REV` hochzählen. Ohne Schritt 2 lehnt Keycloak den Login mit „Invalid redirect_uri“ ab.

## Stolperfallen

- `groups` ist **kein** anforderbarer Scope (der Claim kommt per Mapper). Steht es in `--scope`, scheitert
  der Login mit `invalid_scope`.
- Nach Umzügen zwischen Netzen oder Arcane-Projekten auf verwaiste zweite oauth2-proxy-Container achten
  ([Fehlersuche](../betrieb/fehlersuche.md#doppelte-container)).
