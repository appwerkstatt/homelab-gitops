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

## Pflicht-Login für Lesen (seit 2026-11, kein anonymer Pull mehr)

`anonymousPolicy` ist leer: ohne Credentials antwortet Zot mit 401. Zwei Robot-User im htpasswd:
`ci` (read/create/update, Push) und `pull` (nur read, für NAS + Cluster).

Rollout (VOR dem Merge, sonst schlagen Pulls fehl):

1. Passwort erzeugen und in 1Password ablegen: Item `homelab-zot`, Feld `pull-password`
   (`openssl rand -base64 24`).
2. User anhängen und Dokument in 1Password aktualisieren:
   ```sh
   htpasswd -nbB pull "$(op read op://AppsFab/homelab-zot/pull-password)" \
     | ssh truenas.server 'sudo tee -a /mnt/fast/appdata/registry/htpasswd >/dev/null'
   ```
   Zot liest das htpasswd beim Start → nach dem Merge Recreate (passiert durch den Deploy).
   Danach `homelab-zot-htpasswd` in 1Password durch die neue Datei ersetzen.
3. NAS-Pulls (netboot-console `127.0.0.1:5000/...`): In Arcane unter Settings → Container
   Registries `127.0.0.1:5000` mit User `pull` anlegen (oder auf dem NAS `sudo docker login 127.0.0.1:5000`).
4. Cluster (`christian/cluster`, k3s `registries.yaml`): unter `configs:` für
   `registry.lab.appsfab.org` `auth: {username: pull, password: ...}` setzen und auf die Nodes ausrollen
   (k3s neu starten).
5. Test vor dem Merge: `curl -u pull:… https://registry.lab.appsfab.org/v2/_catalog` → 200.
   Nach dem Merge: ohne `-u` → 401, und netboot-console bzw. ein Pod mit Zot-Image lässt sich neu pullen.

Rollback: `"anonymousPolicy": ["read"]` zurück.

## Login über Keycloak (OIDC)

Die Web-UI (https://registry.lab.appsfab.org) bietet "Sign in with Keycloak" (Realm AppsFab,
Client `zot`). Benutzername in Zot = Keycloak-`preferred_username`.

- Gruppe `lab-admins` = Admin (read/create/update/delete auf allen Repos, `adminPolicy`).
- Jeder andere Keycloak-User = read (`defaultPolicy`).
- Robots bleiben im htpasswd: `ci` (Push aus CI), `pull` (NAS/Cluster).

Docker-CLI kann kein OIDC → nach dem SSO-Login in der UI unter "API Keys" einen Key erzeugen
(Prefix `zak_`) und damit einloggen:

```sh
docker login registry.lab.appsfab.org -u <keycloak-username> -p zak_...
```

Das Client-Secret (`ZOT_OIDC_CLIENT_SECRET`, 1Password `AppsFab/homelab-zot/oidc-client-secret`) muss
in BEIDEN Arcane-Envs stehen: `keycloak` (kcc legt den Client an) und `registryzot`
(`zot-oidc-init` schreibt es nach `/run/zot/oidc-credentials.json`).
