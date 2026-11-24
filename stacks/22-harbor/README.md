# 22-harbor — Zot (OCI-Registry)

Hier läuft **Zot** (ein Container, `compose.yaml` + `config/zot.json`), **nicht** Harbor. Der Ordnername
ist historisch und bleibt, weil die Arcane-Gitsync-App auf diesen Pfad zeigt (Projekt-Slug `registryzot`,
Container `registryzot-zot-1`). Umbenennen hieße: Arcane-App neu anlegen, sonst entsteht ein zweites Projekt.

- **Zweck:** private Registry für eigene Images (netboot-console, lab-status, gmb-*). Kein Pull-Through-Cache
  (Docker Hub cached `23-registry-cache`).
- **Erreichbar:** `https://registry.lab.appsfab.org` (LAN, über Traefik) und NAS-lokal `127.0.0.1:5000`
  (der NAS-Host erreicht Traefik `.48` wegen macvlan-Hairpin nicht).
- **Daten:** `/mnt/data/harbor/zot`. **Extras:** UI, Suche, Trivy-CVE-Scan, scrub.
- **Zugang:** kein anonymer Zugriff. Menschen per Keycloak-SSO (UI) bzw. Zot-API-Key (CLI),
  Robots per htpasswd (`/mnt/fast/appdata/registry/htpasswd`, Original als 1Password-Dokument
  `homelab-zot-htpasswd`): `ci` = Push aus CI, `pull` = nur Lesen (NAS über Arcane-Registry-Credentials,
  k3s über `registries.yaml` im Cluster-Repo).
- **Monitoring:** blackbox-Probe `probe-registry` (`/v2/` → 401 = lebt).

## Pflicht-Login für Lesen (seit 2026-11, #123)

`anonymousPolicy` ist leer: ohne Credentials antwortet Zot mit 401. Zwei Robot-User im htpasswd:
`ci` (read/create/update, Push) und `pull` (nur read, für NAS + Cluster).

Einmaliger Rollout (erledigt 2026-11-21; für einen Neuaufbau):

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

## Web-UI-Login über Keycloak (OIDC, #124)

Die Zot-UI (`https://registry.lab.appsfab.org`) zeigt „Sign in with Keycloak“ statt nur des
Passwort-Formulars. Rechte kommen aus den Keycloak-Gruppen (Claim `groups`):
`lab-admins` → read/create/update/delete, `devs` → read. Benutzername = `preferred_username`.

- Keycloak-Client `zot` (Realm-JSON, kcc), Redirect `https://registry.lab.appsfab.org/zot/auth/callback/oidc`,
  Post-Logout `https://registry.lab.appsfab.org/login` (#127). Issuer `https://auth.appsfab.org/realms/AppsFab`.
- Secret: 1Password `homelab-zot` / Feld `oidc-client-secret` → Env `ZOT_OIDC_CLIENT_SECRET`
  in **beiden** Arcane-Stacks (`keycloak` UND `registryzot`). Der One-Shot `zot-oidc-creds`
  rendert daraus `/etc/zot/oidc/oidc.json` (Zot kann keine Env-Variablen in der Config).
- Server-seitige OIDC-Calls laufen über den Traefik-Netz-Alias `auth.appsfab.org` (kein Hairpin, kein Umweg übers Internet).
- CLI/CI (docker, k3s, Arcane) bleiben bei htpasswd (`ci`, `pull`). Persönliche CLI-Zugänge:
  nach dem OIDC-Login in der UI einen API-Key erzeugen (`apikey: true`) und mit
  `docker login -u <keycloak-user> -p <api-key> registry.lab.appsfab.org` nutzen.

Rollout-Reihenfolge für einen Neuaufbau (sonst setzt kcc das Secret leer bzw. `zot-oidc-creds` bricht ab):

1. `openssl rand -base64 32 | tr -d '/+=' ` → 1Password `homelab-zot`, Feld `oidc-client-secret`.
2. `ZOT_OIDC_CLIENT_SECRET` in Arcane → `keycloak` → Environment und → `registryzot` → Environment
   setzen (`scripts/render-env.sh keycloak` / `scripts/render-env.sh harbor`).
3. Deploy keycloak (kcc legt Client `zot` an) und registryzot.
4. Test: UI → „Sign in with Keycloak“ → Repos sichtbar; `curl -u pull:… …/v2/_catalog` weiterhin 200.

Rollback: `openid`-Block aus `zot.json` entfernen (htpasswd-Login bleibt unverändert).
