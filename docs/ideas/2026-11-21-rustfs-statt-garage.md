# Idee: RustFS statt Garage (21-garage)

Status: **Idee für später**, nicht geplant. Stand der Recherche: 2026-11-21.

## Entscheidung für jetzt

Wir bleiben bei Garage (`stacks/21-garage`, `dxflrs/garage:v2.5.0`, Single-Node).
Für Loki, Velero, Artefakte sowie die etcd- und Longhorn-Backups reicht die S3-API von Garage.

## Wann wir es wieder anschauen

- beim nächsten Neuaufbau des Clusters (dann müssen kaum Daten umziehen)
- wenn wir unveränderliche Backups mit **Object Lock** oder **Versionierung** brauchen
- wenn wir eine **Web-Konsole** für Buckets und Keys wollen
- wenn RustFS 1.x ein paar Monate ohne neue schwere Bugs oder CVEs gelaufen ist

## RustFS: Vorteile

- 1.0.0 ist seit 2026-09-16 GA, Apache-2.0
- Versionierung, Object Lock, Lifecycle (inkl. Tiering) und Replikation gelten als fertig
- eingebaute Web-Konsole (Port 9001), dazu IAM, STS und OIDC/SSO (z. B. Keycloak)
- großes Projekt (über 30k GitHub-Sterne, 160+ Contributors), gedacht als MinIO-Ersatz

## RustFS: Nachteile

- sehr jung: GA erst seit 2 Monaten
- in der Pre-Release-Zeit gab es mehrere Sicherheitslücken, darunter ein Fehler beim
  Durchsetzen von Object Lock (CVE-2026-73288, behoben in 1.0.0-rc.1) und ein
  Path-Traversal über Buckets hinweg (CVE-2026-49991)
- braucht mehr RAM: laut Anleitungen mindestens 2 GB, 4 GB für Produktion
  (Garage läuft hier mit `mem_limit: 512m`)
- Single-Node/Single-Disk lässt sich nicht nachträglich erweitern, nur per neuem Deployment und Umzug
- noch Preview: S3 Tables und die MinIO-Datenkompatibilität

## Garage: zum Vergleich

- stabil und schlank, läuft hier ohne Probleme
- keine Versionierung, kein Object Lock, keine Bucket Policies; Lifecycle nur Expiration
  und AbortIncompleteMultipartUpload
- keine Web-Konsole, Verwaltung per CLI
- NLnet-Förderung (2026-04) für über ein Jahr Arbeit an Zuverlässigkeit und Performance,
  ausdrücklich auch für `replication_factor = 1`
- AGPL-3.0 (für Eigenbetrieb egal)

## Was ein Wechsel im Repo bedeuten würde

1. `stacks/21-garage` durch einen RustFS-Stack ersetzen: Image `rustfs/rustfs:1.0.x` gepinnt,
   S3 auf 9000, Konsole auf 9001, Datenordner im Besitz von UID/GID 10001.
2. Traefik: Router `s3.${LAB_DOMAIN}` auf Port 9000, zweiter Router für die Konsole
   (nur intern, `*.lab.appsfab.org`). Netz `edge-garage` in `00-traefik` umbenennen.
3. Zugangsdaten (`RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`) in den 1Password-Vault `AppsFab`,
   `scripts/render-env.sh` entsprechend.
4. Homepage-Eintrag (`40-homepage`) und Scrape-Config (`20-observability`) anpassen.
5. Buckets `loki`, `velero`, `artifacts`, `k3s-etcd-backups`, `longhorn-backup` und ihre Keys neu anlegen.
   In den Clients die Region `garage` ändern.
6. Bestehende Daten (vor allem `artifacts`, `velero`) per `rclone sync` umziehen.
   Alte etcd- und Longhorn-Backups braucht ein neu aufgebauter Cluster nicht.
7. Hinweis: RustFS blockiert ausgehende Aufrufe an private Adressen (Webhooks, OIDC-Discovery)
   standardmäßig. Für Keycloak im LAN `RUSTFS_OUTBOUND_ALLOW_ORIGINS` setzen.

## Quellen

- https://linuxiac.com/rustfs-1-0-s3-compatible-object-storage-reaches-ga/
- https://aicybr.com/blog/rustfs-1-0-ga-s3-object-storage
- https://www.bitdoze.com/rustfs-self-host/
- https://www.mend.io/vulnerability-database/CVE-2026-73288/
- https://www.sentinelone.com/vulnerability-database/cve-2026-49991/
- https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/
- https://garagehq.deuxfleurs.fr/blog/2026-04-performance-reliability/
- https://lwn.net/Articles/1077739/
