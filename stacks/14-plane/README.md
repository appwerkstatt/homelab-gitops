# 14-plane — Plane (Community Edition)

Projekt- und Aufgabenverwaltung als Jira-/Kanban-Ersatz: Issues, Zyklen (Sprints), Module, Kanban/Liste/Kalender/Gantt, Seiten.
Nur im LAN unter **https://plane.lab.appsfab.org**, komplett hinter Keycloak (`sso@docker`, Gruppe `lab-users`).

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

**Login:** Die Community-Edition kann kein OIDC/SAML (das ist Plane Pro). Deshalb zwei Stufen: Keycloak vor allem
(Passkey/2FA), danach Plane-eigenes Konto (E-Mail + Passwort). Optional ersetzt Schritt 6 das Plane-Passwort durch
einen Login über Forgejo, das selbst nur per Keycloak anmeldet.

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
  nach Belieben sperren; der Keycloak-Login davor lässt ohnehin nur `lab-users` durch.
- **SMTP** erst, wenn Mails gebraucht werden (Einladungen, Benachrichtigungen).

### 5. Workspace anlegen

https://plane.lab.appsfab.org/ → mit demselben Konto anmelden → Workspace anlegen, erstes Projekt.

### 6. Optional: Login über Forgejo statt Plane-Passwort

Plane spricht „Gitea"-OAuth, Forgejo ist dazu kompatibel. Die Plane-API holt Token und Benutzer serverseitig über den
Traefik-Alias `git.appsfab.org` im Netz `edge-plane` (00-traefik).

1. Forgejo → **Einstellungen → Anwendungen → OAuth2-Anwendung erstellen**: Name `Plane`,
   Redirect-URI `https://plane.lab.appsfab.org/auth/gitea/callback/`, vertraulicher Client.
2. Client-ID und -Secret in 1Password unter `homelab-plane` als `forgejo-client-id` / `forgejo-client-secret` ablegen
   (Plane liest sie nicht aus der Env, sondern aus seiner DB).
3. God Mode → **Authentication → Gitea**: Host `https://git.appsfab.org`, Client-ID, Secret, aktivieren.
4. Abmelden und „Mit Gitea anmelden" testen. Hat das Konto dieselbe E-Mail wie das bestehende Plane-Konto,
   landet man im selben Konto.

Ungetestet in diesem Setup; klappt es nicht, bleibt das Plane-Passwort.

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
