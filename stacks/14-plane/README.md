# 14-plane — Plane (Community Edition)

Projekt- und Aufgabenverwaltung als Jira-/Kanban-Ersatz: Issues, Zyklen (Sprints), Module, Kanban/Liste/Kalender/Gantt, Seiten.
Nur im LAN unter **https://plane.lab.appsfab.org**, komplett hinter Keycloak (`sso@docker`, Gruppe `lab-users`; `/god-mode` hinter `sso-admin@docker`, nur `lab-admins`).

## Was läuft

| Dienst | Zweck | Limit |
|--------|-------|-------|
| `plane-web` | Web-App (statisch) | 64m |
| `plane-admin` | Instanz-Verwaltung unter `/god-mode` | 64m |
| `plane-api` | Django-API (`/api/`, `/auth/`, `/static/`) | 768m |
| `plane-worker` | Celery-Worker (2 Prozesse) | 768m |
| `plane-beat` | Celery-Zeitplaner | 384m |
| `plane-live` | Echtzeit-Editor (WebSocket, `/live/`) | 384m |
| `plane-migrator` | Django-Migrationen, läuft pro Deploy einmal und beendet sich | 512m |
| `plane-db` | Postgres 17 | 512m |
| `plane-redis` | Valkey, nur Cache (ohne Persistenz) | 128m |
| `plane-mq` | RabbitMQ (Celery-Queue) | 256m |
| `plane-minio` | S3 für Anhänge (`/uploads`) | 256m |

Summe der Limits ≈ 3,5 GB, real erwartet 1,5 bis 2 GB. Nicht dabei: `space` (öffentlich geteilte Seiten), der Plane-eigene Caddy-Proxy (Traefik routet die Pfade direkt).

**Login:** Die Community-Edition kann kein OIDC/SAML (das ist Plane Pro). Keycloak steht per `sso@docker` vor allem
(Passkey/2FA). In Plane selbst meldet ein kleiner AGPL-Patch über Keycloak an (Button „Continue with Gitea“,
Schritt 6), sodass kein zweites Passwort nötig ist.

## Erstinstallation

### 1. 1Password-Item `homelab-plane` (Vault `AppsFab`, auf dem Mac)

```bash
op item create --vault AppsFab --category "API Credential" --title homelab-plane \
  "db-password[password]=$(openssl rand -hex 32)" \
  "secret-key[password]=$(openssl rand -hex 32)" \
  "live-secret-key[password]=$(openssl rand -hex 32)" \
  "mq-password[password]=$(openssl rand -hex 32)" \
  "s3-access-key[text]=$(openssl rand -hex 10)" \
  "s3-secret-key[password]=$(openssl rand -hex 32)"
```

### 2. Datasets/Ordner auf dem NAS (TrueNAS-Shell, als root)

```bash
zfs create fast/appdata/plane            # oder in der UI: Datasets -> fast/appdata -> Add Dataset "plane"
install -d /mnt/fast/appdata/plane/db       # Postgres chownt selbst
install -d /mnt/fast/appdata/plane/uploads  # MinIO läuft als root
```

### 3. Deploy-Reihenfolge in Arcane

1. **traefik** neu deployen (legt das Netz `edge-plane` an).
2. **keycloak** neu deployen (Callback `plane.lab/oauth2/callback` am Client `oauth2-proxy`, `KCC_REALM_REV` 17).
3. Neue **Gitsync-App** anlegen, Anzeigename genau **`plane`**, Pfad `stacks/14-plane/compose.yaml`.
   Der Name ergibt den Projekt-Slug und damit den Container `plane-plane-db-1`, den das Offsite-Backup sichert.
4. Environment der App: auf dem Mac `scripts/render-env.sh plane` und die Ausgabe einfügen, dann deployen.
   Der erste Start dauert ein bis zwei Minuten (Migrationen); `plane-migrator` steht danach auf *exited (0)*.
5. **observability** neu deployen (blackbox hängt sich an `edge-plane`), danach **homepage**.

### 4. Instanz-Admin anlegen

https://plane.lab.appsfab.org/god-mode/ öffnen (erst Keycloak-Login), Admin-Konto anlegen. Danach in God Mode:

- **General → Telemetrie** ausschalten.
- **Authentication:** „Magic link" aus (ohne SMTP sinnlos), „Passwort" an. Unter *Workspace* die Anmeldung neuer Konten
  sperren („Allow anyone to sign up“ aus), sonst legt sich jeder `lab-users`-Benutzer selbst ein Konto an.
  Neue Personen als *Member* in den Workspace einladen.
- **SMTP** erst, wenn Mails gebraucht werden (Einladungen, Benachrichtigungen).

### 5. Workspace anlegen

https://plane.lab.appsfab.org/ → mit demselben Konto anmelden → Workspace anlegen, erstes Projekt.

### 6. Login über Keycloak (statt Plane-Passwort)

Die Community-Edition kann kein OIDC. `patches/gitea.py` (AGPL wie Plane, per Bind-Mount nur in `plane-api`)
ersetzt Planes „Gitea“-Provider: Der Button **„Continue with Gitea“** meldet jetzt per OpenID Connect bei Keycloak an
(Client `plane`). Lizenzprüfungen bleiben unangetastet, die übrigen Plane-Images sind die Originale.

- Plane verknüpft über die **E-Mail**: Wer schon ein Plane-Konto mit derselben Adresse hat, landet darin.
- Nur Adressen mit `email_verified = true` werden angenommen. Sonst könnte jemand im Keycloak-Kontoportal seine
  E-Mail auf eine fremde ändern und deren Plane-Konto übernehmen. In der Keycloak-Admin-Konsole beim Benutzer
  **„Email verified“** anhaken, sonst meldet Plane `OAUTH_PROVIDER_UNVERIFIED_EMAIL`.
- Die Signup-Sperre gilt weiter: Neue Personen kommen nur mit Workspace-Einladung an dieselbe E-Mail rein.
- Die Plane-API holt Token und Userinfo serverseitig über den Traefik-Alias `auth.appsfab.org` im Netz `edge-plane`.

Einrichten (einmalig):

1. 1Password `homelab-plane`: Feld `oidc-client-secret` anlegen (`openssl rand -hex 32`).
2. Arcane → **keycloak** → Environment: `PLANE_OIDC_CLIENT_SECRET` ergänzen (`scripts/render-env.sh keycloak`),
   deployen. keycloak-config-cli legt den Client `plane` an (`KCC_REALM_REV` 20).
3. **plane** neu deployen (Bind-Mount für `plane-api`). Prüfen:
   `docker exec plane-plane-api-1 grep -c openid-connect /code/plane/authentication/provider/oauth/gitea.py` ⇒ `2`.
4. God Mode → **Authentication → Gitea**: Host `https://auth.appsfab.org/realms/AppsFab`, Client-ID `plane`,
   Secret aus Schritt 1, aktivieren. (Plane liest die Werte aus seiner DB, nicht aus der Env.)
5. In Keycloak bei allen Plane-Nutzern „Email verified“ prüfen, dann abmelden und „Continue with Gitea“ testen.
6. Wenn es klappt: God Mode → Authentication → **„Passwort“ aus**. Dann bleibt nur der Keycloak-Login.
   Notfall (Keycloak kaputt): Passwort-Login dort wieder einschalten; Konten, die sich nur per Keycloak angemeldet
   haben, haben kein Passwort und brauchen „Passwort vergessen“ (SMTP) oder `manage.py changepassword`.

**Plane-Updates:** Renovate mergt Plane-Patches automatisch. `scripts/check-plane-patch.sh` (CI-Schritt in
`validate`) vergleicht die Upstream-Dateien, auf denen der Patch aufbaut (`patches/upstream.sha256`), mit der Version
in `compose.yaml`. Ändert Plane sie, bleibt der Update-PR rot: Upstream-Diff lesen, `patches/gitea.py` anpassen,
`scripts/check-plane-patch.sh --update`, committen. Arcane erstellt `plane-api` nicht neu, wenn sich nur
`patches/gitea.py` ändert: danach den Container von Hand neu starten.

## Betrieb

- **Updates:** Renovate hält alle `makeplane/*`-Images als Gruppe `plane` gleich (Patches automatisch). Migrationen
  laufen bei jedem Deploy über `plane-migrator`. Vor einem Minor-Sprung die Release-Notes lesen.
- **Backup:** Datasets `fast/appdata` = Snapshots + Replika auf `backup`. Offsite (restic → B2) nimmt
  `pg_dump` der DB und `/mnt/fast/appdata/plane/uploads` mit (`docs/nas-backup/backup-offsite.sh`, nach Änderungen
  nach `/mnt/backup/scripts/nas-backup/` kopieren).
- **Secrets:** `secret-key` nicht wechseln, ohne zu wissen, dass das alle Sitzungen beendet und in der DB
  gespeicherte Login-Secrets (God Mode) unlesbar machen kann.
- **API für Automationen** (z. B. n8n): `/api/v1/` mit `X-API-Key` liegt derzeit hinter `sso@docker`. Für Zugriff
  aus n8n bräuchte es einen eigenen Router ohne SSO oder n8n im Netz `edge-plane`.
