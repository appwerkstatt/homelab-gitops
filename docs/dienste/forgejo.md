# 01-forgejo

| | |
|---|---|
| **Zweck** | Git-Hosting (u. a. das Cluster-Repo `christian/cluster`), Repo für die Netboot-Konsole |
| **Adresse** | `https://git.appsfab.org` (öffentlich über Tunnel und im LAN), SSH `git@git.appsfab.org` (Port 22 auf Traefik `.48`) |
| **Login** | Web nur per Keycloak-SSO (Quelle `keycloak`); Git über HTTPS und API nur mit Token (kein Passwort), SSH mit Schlüssel |
| **Daten** | `fast/appdata/forgejo` (SQLite `gitea.db`, Repos, `jwt/private.pem`) |
| **Backup** | Tier 2 + nächtlicher `forgejo dump` offsite |
| **Abhängig von** | Keycloak (Login), Traefik |
| **Quelle** | [`stacks/01-forgejo/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/01-forgejo/compose.yaml) |

GitHub bleibt die Quelle der Wahrheit für **dieses** Repo. Forgejo ist für eigene Repos und den Cluster.

## Login

- `ENABLE_INTERNAL_SIGNIN=false`: kein Passwort-Formular. Traefik leitet `/user/login` direkt auf
  `/user/oauth2/keycloak` um (Router `forgejo-login`).
- `ENABLE_BASIC_AUTHENTICATION=false`: API und Git über HTTPS nehmen kein Passwort mehr an, nur Tokens
  (Personal Access Token als Passwort oder `Authorization: token …`). Sonst ginge ein lokales Passwort aus
  dem Internet an Keycloak, Passkey/2FA und der Brute-Force-Sperre vorbei.
- Keycloak-Gruppe `lab-admins` macht zum Forgejo-Admin (`--admin-group`). Anmelden darf nur, wer in
  `lab-users` ist (`--required-claim-name groups --required-claim-value lab-users`).
- Die OAuth-Quelle steht in der Datenbank, nicht in der Env. Einmalig angelegt mit
  `forgejo admin auth add-oauth …` (Befehl im `compose.yaml`). Nach `update-oauth` den Container neu starten.

## Betrieb

- **Notzugang**, wenn Keycloak nicht geht: `FORGEJO__service__ENABLE_INTERNAL_SIGNIN` auf `"true"` setzen
  und deployen, oder per CLI: `docker exec -u git forgejo-forgejo-1 forgejo admin user …`.
- Geht ein OAuth-Login schief, landet man in einer Schleife zu Keycloak. Dann das Forgejo-Log lesen.
- `git.appsfab.org` ist von der Cloud aus (z. B. GitHub Actions) und aus manchen Fremdnetzen nicht erreichbar;
  gepusht wird vom Mac.
