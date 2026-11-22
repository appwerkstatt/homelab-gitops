# 21-garage

| | |
|---|---|
| **Zweck** | S3-kompatibler Objektspeicher, vor allem für den Cluster |
| **Adresse** | `https://s3.lab.appsfab.org` (path-style) |
| **Login** | S3-Access-Keys je Bucket; Verwaltung per CLI |
| **Daten** | Metadaten `fast/appdata/garage/meta` (LMDB), Objekte `data/garage/data` |
| **Backup** | **bewusst keins** für die Objekte (Entscheidung 2026-11-21, Cluster wird neu aufgebaut) |
| **Quelle** | [`stacks/21-garage/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/21-garage/compose.yaml) |

Buckets: `velero`, `artifacts`, `k3s-etcd-backups`, `longhorn-backup`, `loki` (ungenutzt, Loki speichert lokal).
Single-Node, `replication_factor = 1`.

## Betrieb

```bash
docker exec garages3-garage-1 /garage status        # Projekt heißt garages3, nicht garage
docker exec garages3-garage-1 /garage bucket list
```

Nie `docker compose up` ohne `-p garages3`: zwei Garage-Prozesse auf derselben LMDB zerstören die Metadaten.

Ein Wechsel zu RustFS ist als [Idee](../ideas/2026-11-21-rustfs-statt-garage.md) dokumentiert.
