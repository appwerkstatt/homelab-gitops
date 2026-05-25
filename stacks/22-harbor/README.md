# 22-harbor — Container-Registry

Harbor wird **nicht** von Hand als Compose geschrieben, sondern über den **offiziellen Offline-Installer**
bereitgestellt, der ein `docker-compose.yml` generiert. Vorgehen:

1. Harbor-Offline-Installer laden, `harbor.yml` konfigurieren:
   - `hostname: registry.lab.appsfab.org`
   - `external_url: https://registry.lab.appsfab.org` (TLS terminiert Traefik → Harbor http)
   - `data_volume: /mnt/data/harbor`
   - `database.password: ${HARBOR_DB_PASSWORD}`, `harbor_admin_password: ${HARBOR_ADMIN_PASSWORD}`
   - Trivy aktivieren (Vulnerability-Scanning).
2. `./prepare` ausführen → erzeugtes `docker-compose.yml` **hier in `22-harbor/` ablegen** (committen).
3. Traefik-Router auf den Harbor-Proxy-Port (80) setzen; Robot-Account für den k3s-Cluster-Pull anlegen.
4. **Pull-Through-Proxy-Cache** für Docker Hub / ghcr.io einrichten (wegen 100-Mbit-Internet) — siehe Runbook Phase 2.5.

## Schlanke Alternative: Zot (`compose.yaml` in diesem Ordner)

Wenn Harbor (mehrere Container, Java/Trivy, ~2–3 GB RAM) zu schwer ist, deployt `compose.yaml`
**Zot** (CNCF, ein einzelner OCI-Registry-Container) als sofort lauffähigen Start. Später auf Harbor
wechseln, wenn RBAC/Scanning/Replication gebraucht werden.
