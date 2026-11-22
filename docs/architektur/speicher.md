# Speicher (ZFS)

## Pools

| Pool | Aufbau | Inhalt |
|---|---|---|
| `fast` | NVMe, Mirror | App-Daten und Datenbanken (`fast/appdata/<dienst>`), VM-Zvols (`fast/vm`), TrueNAS-App-Engine (`fast/ix-apps`) |
| `data` | HDD, Mirror | große Nutzdaten: Dokumente, Homes, Medien, Provisioning, Garage-Objekte, Registry-Daten |
| `backup` | eine 6-TB-Disk, **verschlüsselt**, ohne Redundanz | lokale Replika (`backup/replica`), Dumps (`backup/dumps`), Backup-Skripte, Time Machine, Archiv |

Das System selbst liegt auf dem `boot-pool`. Bei einer Neuinstallation von TrueNAS geht dort alles verloren,
was nicht in der TrueNAS-Konfiguration oder auf den Datenpools steht. Deshalb liegen die Backup-Skripte unter
`/mnt/backup/scripts/` und die Konfiguration wird jede Nacht exportiert.

!!! warning "Single-Disk `backup`"
    `backup` hat keine Redundanz. Fällt die Disk aus, sind lokale Replika und Dumps weg, die Originale auf
    `fast`/`data` und die Offsite-Kopie in B2 aber nicht. Bewusst akzeptiert (`SECURITY.md`, Punkt E).

## Datasets und wer sie nutzt

| Dataset / Pfad | Genutzt von | Backup-Stufe |
|---|---|---|
| `fast/appdata/traefik` | Traefik (`acme.json`) | Tier 2 |
| `fast/appdata/forgejo` | Forgejo (SQLite `gitea.db`, Repos, `jwt/private.pem`) | Tier 2 + Offsite-Dump |
| `fast/appdata/keycloak` | Keycloak-Postgres | Tier 2 + Offsite-Dump |
| `fast/appdata/paperless`, `fast/appdata/paperless-ai` | Paperless-Postgres/Redis/Index, paperless-ai (ChromaDB) | Tier 2 + Offsite-Dump |
| `fast/appdata/n8n` | n8n-Daten und -Postgres | Tier 2 + Offsite-Dump |
| `fast/appdata/plane` | Plane-Postgres, Uploads (MinIO) | Tier 2 + Offsite-Dump + Uploads offsite |
| `fast/appdata/{vm,loki,grafana,alertmanager,node-exporter}` | Observability | Tier 2 |
| `fast/appdata/garage/meta` | Garage-Metadaten (LMDB) | Tier 2 |
| `fast/appdata/registry`, `fast/appdata/cloudflared`, `fast/appdata/netboot-console` | Datei-Secrets (htpasswd, Tunnel-Credentials, SSH-Key) | Tier 2 |
| `fast/appdata/_secrets` | `restic-b2.env` für das Offsite-Backup | Tier 2 |
| `data/paperless` | Paperless-Dokumente (`media`, `consume`, `export`) | **Tier 1** + offsite |
| `data/homes`, `backup/HomeFolders` | Benutzer-Homes | **Tier 1** + offsite |
| `data/makerlab` | Makerlab-Daten | Tier 2 |
| `data/provisioning` | Netboot: Images, Seeds, TFTP, `control` | Tier 3 |
| `data/media` | Medien | Tier 3 |
| `data/garage` | Garage-Objekte (Cluster-Backups) | **bewusst kein Backup** |
| `data/harbor/zot` (Ordner, kein Dataset) | Zot-Registry | **bewusst kein Backup**, Images sind neu baubar |
| `data/registry-cache` | Docker-Hub-Cache | **bewusst kein Backup** |
| `fast/vm/n8n-sandbox` (Zvol) | Sandbox-VM | **bewusst kein Backup**, wegwerfbar |
| `fast/ix-apps` | TrueNAS-App-Engine (Images, Named Volumes) | **bewusst kein Backup** |
| `backup/dumps` | App-Dumps + TrueNAS-Konfig-Export | **Tier 1** + offsite |
| `backup/replica/*` | lokale Replika von Tier 1 + 2 | ist selbst das Backup |
| `backup/archive` | Archiv (z. B. altes Preinstall-Abbild) | nur lokal |

Was die Stufen bedeuten und wann was läuft, steht unter [Backup](../backup/index.md).

## Rechte und Ordner

- Container laufen meist mit `PUID`/`PGID` aus der Arcane-Env. Ausnahmen legen ihren Ordner vorher mit
  passenden Rechten an, z. B. n8n (`uid 1000`) und Alertmanager (`uid 65534`); die Befehle stehen als
  Kommentar im jeweiligen `compose.yaml`.
- Postgres-Container `chown`en ihr Datenverzeichnis selbst.
- Datei-Secrets liegen mit `chmod 600` unter `fast/appdata/…` und zusätzlich als Dokument in 1Password.
