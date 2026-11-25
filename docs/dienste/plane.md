# 14-plane

| | |
|---|---|
| **Zweck** | Projekt- und Aufgabenverwaltung (Jira-/Kanban-Ersatz), Plane Community Edition |
| **Adresse** | `https://plane.lab.appsfab.org` (nur LAN), Instanz-Admin unter `/god-mode` |
| **Login** | `sso@docker` und danach Plane-Konto (CE kann kein OIDC); God Mode hinter `sso-admin@docker` |
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

## Offen

Optionaler Login über Forgejo („Gitea“-OAuth) statt Plane-Passwort ist vorbereitet (Traefik-Alias
`git.appsfab.org` in `edge-plane`), aber noch nicht eingerichtet. Anleitung im
[README](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/14-plane/README.md#6-optional-login-über-forgejo-statt-plane-passwort).
