# 14-plane

| | |
|---|---|
| **Zweck** | Projekt- und Aufgabenverwaltung (Jira-/Kanban-Ersatz), Plane Community Edition |
| **Adresse** | `https://plane.lab.appsfab.org` (nur LAN), Instanz-Admin unter `/god-mode` |
| **Login** | `sso@docker`, danach in Plane „Continue with Gitea“ = Keycloak (eigener Patch, CE kann kein OIDC); God Mode hinter `sso-admin@docker` |
| **Daten** | `fast/appdata/plane/{db,uploads}` |
| **Backup** | Tier 2 + `pg_dump` und Uploads offsite |
| **Quelle** | [`stacks/14-plane/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/14-plane) |

## Bausteine

Elf Container: Web, Admin, API, Worker, Beat, Live (WebSocket), Migrator (pro Deploy einmal), Postgres 17,
Valkey, RabbitMQ, MinIO-Fork für Anhänge. Traefik routet die Pfade direkt (`/api/`, `/auth/`, `/live/`,
`/uploads`, `/god-mode`), Planes eigener Caddy-Proxy entfällt. Limits zusammen etwa 3,5 GB, real 1,5 bis 2 GB.

## Betrieb

- Die Arcane-App muss `plane` heißen; das Backup sucht den Container `plane-plane-db-1`.
- Renovate hebt alle `makeplane/*`-Images gemeinsam; Migrationen laufen automatisch beim Deploy.
- Anhänge mit Dateitypen außerhalb der Plane-Liste (z. B. HEIC) lehnt Plane mit 400 ab.
- Die Plane-API (`/api/v1/`) liegt hinter SSO; für n8n bräuchte es einen eigenen Router oder n8n in `edge-plane`.

## Keycloak-Login (Patch)

Plane CE hat kein OIDC. [`stacks/14-plane/patches/gitea.py`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/14-plane/patches/gitea.py)
ersetzt per Bind-Mount in `plane-api` Planes „Gitea“-Provider durch OpenID Connect gegen Keycloak (Client `plane`).
Kein eigenes Image, keine Lizenzprüfung angefasst; der Button heißt weiter „Continue with Gitea“.

- Konten werden über die E-Mail verknüpft. Keycloak muss die Adresse als **verifiziert** führen
  („Email verified“ beim Benutzer), sonst lehnt Plane mit `OAUTH_PROVIDER_UNVERIFIED_EMAIL` ab.
- Neue Personen brauchen weiterhin eine Workspace-Einladung an genau diese E-Mail (Signup bleibt aus).
- „Sign up disabled“ nach dem Login: Keycloak- und Plane-Adresse unterscheiden sich. Plane CE lässt die E-Mail im
  Profil nicht ändern; in Keycloak oder per SQL in der Plane-DB angleichen (README).
- Einrichtung (Client-Secret, God Mode, Passwort-Login abschalten) im
  [README](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/14-plane/README.md#6-login-über-keycloak-statt-plane-passwort).
- **Updates:** Der CI-Schritt `scripts/check-plane-patch.sh` hält Renovate-PRs auf, wenn Plane die Dateien ändert,
  auf denen der Patch aufbaut. Dann Patch anpassen und `--update` laufen lassen. Nach einer Änderung nur an
  `patches/gitea.py` `plane-api` von Hand neu starten (Arcane erkennt das nicht).
