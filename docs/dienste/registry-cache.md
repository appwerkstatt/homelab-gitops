# 23-registry-cache

| | |
|---|---|
| **Zweck** | Pull-Through-Cache für Docker Hub (spart Rate-Limit und Bandbreite) |
| **Adresse** | `https://mirror.lab.appsfab.org`; NAS-Daemon über `127.0.0.1:5001` |
| **Login** | keiner, aber nur aus VLAN 80 und 10 (`MIRROR_ALLOWED_CIDRS`), sonst 403 |
| **Daten** | `data/registry-cache` (Cache, 7 Tage TTL) |
| **Backup** | bewusst keins |
| **Quelle** | [`stacks/23-registry-cache/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/23-registry-cache/compose.yaml) |

Der Cache meldet sich mit einem Docker-Hub-Token an (`homelab-dockerhub`). Er ist strikt von Zot getrennt.
Die Arcane-App heißt `registry-cache`.
