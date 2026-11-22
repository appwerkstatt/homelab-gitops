# 22-harbor (Zot)

| | |
|---|---|
| **Zweck** | Private OCI-Registry für eigene Images (netboot-console u. a.). **Kein** Harbor, Ordnername historisch |
| **Adresse** | `https://registry.lab.appsfab.org`; NAS-lokal `127.0.0.1:5000` |
| **Login** | kein anonymer Zugriff. UI per Keycloak; CLI per Zot-API-Key; Robots `ci` (Push) und `pull` (Lesen) per htpasswd |
| **Daten** | `data/harbor/zot` (Ordner, kein Dataset) |
| **Backup** | **bewusst keins**: die Images sind aus Forgejo neu baubar |
| **Quelle** | [`stacks/22-harbor/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/22-harbor) |

Extras: Suche, Trivy-CVE-Scan, scrub. Arcane-Projekt `registryzot`, Container `registryzot-zot-1`.
Docker-Hub-Images cached der getrennte [Registry-Cache](registry-cache.md).

## Rechte

| Wer | Wie | Rechte |
|---|---|---|
| Keycloak `lab-admins` | UI (OIDC) / API-Key | lesen, schreiben, löschen |
| Keycloak `lab-users` | UI (OIDC) / API-Key | lesen |
| `ci` | htpasswd | Push |
| `pull` | htpasswd | lesen (NAS über Arcane-Registry-Credentials, Cluster über `registries.yaml`) |

Einrichtung und Rollback: [README](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/22-harbor/README.md).

## Stolperfallen

- `ZOT_OIDC_CLIENT_SECRET` muss in den Arcane-Envs von `keycloak` **und** `registryzot` stehen.
- Zot liest das htpasswd nur beim Start.
