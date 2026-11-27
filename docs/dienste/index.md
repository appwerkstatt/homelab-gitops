# Dienste

Alle Stacks laufen auf dem NAS und werden von Arcane aus `stacks/<nn>-<name>/compose.yaml` deployt.
Versionen stehen bewusst nur im jeweiligen `compose.yaml`.

| Stack | Was | Adresse | Login | Daten |
|---|---|---|---|---|
| [00-traefik](traefik.md) | Reverse Proxy, TLS, Stack-Netze | `traefik.lab` (Dashboard) | SSO | `fast/appdata/traefik` |
| [01-forgejo](forgejo.md) | Git-Hosting | **`git.appsfab.org`** (öffentlich) | Keycloak (OIDC) | `fast/appdata/forgejo` |
| [02-keycloak](keycloak.md) | Identität, SSO, Passkeys | **`auth.appsfab.org`** (öffentlich), Admin `auth.lab` | Passkey / 2FA | `fast/appdata/keycloak` |
| [03-oauth2-proxy](oauth2-proxy.md) | SSO-Türsteher für Apps ohne OIDC | – (Middleware `sso@docker`) | – | zustandslos |
| [11-paperless](paperless.md) | Dokumentenarchiv + KI-Suche | `docs.lab`, `docs-ai.lab` | Keycloak (OIDC) / SSO | `data/paperless`, `fast/appdata/paperless*` |
| [12-cloudflared](cloudflared.md) | Tunnel ins Internet | – | – | `fast/appdata/cloudflared` |
| [13-n8n](n8n.md) | Workflow-Automatisierung | `n8n.lab`, **`hooks.appsfab.org`** (nur Webhooks) | SSO + n8n-Konto | `fast/appdata/n8n` |
| [14-plane](plane.md) | Projekte, Issues, Kanban | `plane.lab` | SSO + Keycloak-Login (Patch) | `fast/appdata/plane` |
| [15-doku](doku.md) | dieses Handbuch als Website | `doku.lab` | SSO | – |
| [20-observability](observability.md) | Metriken, Logs, Dashboards, Alarme | `grafana.lab` | Keycloak (OIDC) | `fast/appdata/{vm,loki,grafana}` |
| [21-garage](garage.md) | S3-Objektspeicher | `s3.lab` | S3-Keys | `data/garage` |
| [22-harbor](zot.md) | Zot, private OCI-Registry | `registry.lab` | Keycloak (UI), htpasswd (CLI) | `data/harbor/zot` |
| [23-registry-cache](registry-cache.md) | Pull-Through-Cache für Docker Hub | `mirror.lab` | IP-Allowlist | `data/registry-cache` |
| [30-netboot](netboot.md) | Pi-Netboot und Provisioning | `netboot.lab` | Keycloak (OIDC) | `data/provisioning` |
| [40-homepage](homepage.md) | Startseiten Familie + Admin | `home.lab`, `admin.lab` | SSO / SSO-Admin | Config im Repo |

`.lab` steht für `.lab.appsfab.org` (nur LAN). „SSO“ heißt Traefik-Middleware `sso@docker`, erlaubt ist
die Keycloak-Gruppe `lab-users`; Entwickler-Werkzeuge hinter `sso-devs@docker` (nur `devs`), Admin-Werkzeuge hinter `sso-admin@docker` (nur `lab-admins`), siehe
[Rechtekonzept](../sicherheit/rechtekonzept.md).

Außerhalb von Arcane laufen die [Sandbox-VM für n8n](../extern/n8n-sandbox.md) und die
[LLM-Dienste auf dem Mac Studio](../mac-studio-llm.md).

## Aufbau jeder Dienstseite

Jede Seite folgt demselben Schema: **Steckbrief** (Zweck, Adresse, Login, Daten, Backup, Abhängigkeiten),
**Betrieb** (häufige Handgriffe) und **Stolperfallen**. Ausführliche Ersteinrichtungen bleiben im README des
Stacks und sind verlinkt.
