# Neuen Stack anlegen

Checkliste für einen neuen Dienst `<name>` mit Web-Oberfläche. Vorbilder: `14-plane` (groß, mit DB) und
`40-homepage` (klein, ohne Daten).

## Im Repo (ein PR)

- [ ] **Netz** `edge-<name>` in `stacks/00-traefik/compose.yaml` anlegen **und** Traefik daran hängen
      (mit den Aliasen `traefik`, `auth.${LAB_DOMAIN}`, `auth.appsfab.org`).
- [ ] **`stacks/<nn>-<name>/compose.yaml`**: `name: <name>`, gepinnte Images, `mem_limit` überall,
      `restart: unless-stopped`, Datenbank nur im internen Netz, `edge-<name>` als `external`.
- [ ] **Traefik-Labels**: `traefik.enable=true`, `traefik.docker.network=edge-<name>`, Router auf
      `<name>.${LAB_DOMAIN}`, `entrypoints=websecure`, `tls.certresolver=le`.
- [ ] **Login**: OIDC-Client im Realm **oder** `sso@docker` + Callback beim Client `oauth2-proxy`;
      `KCC_REALM_REV` hochzählen ([Login & SSO](../sicherheit/sso.md#neuen-dienst-anbinden)).
- [ ] **Secrets**: jede Variable in `.env.example`, Secrets als `op://AppsFab/homelab-<name>/<feld>`.
- [ ] **Monitoring**: Health-Probe in `stacks/20-observability/config/scrape.yml` und blackbox im
      `compose.yaml` von observability an `edge-<name>` hängen.
- [ ] **Backup**: Daten auf `fast/appdata/<name>` liegen automatisch in Tier 2. Hat der Dienst Postgres, einen
      `dump_pg`-Aufruf in `docs/nas-backup/backup-offsite.sh` ergänzen; unersetzliche Dateien in die restic-Quellen.
- [ ] **Homepage**: Kachel in `stacks/40-homepage/config/services.yaml`; für siteMonitor den Host als Alias in
      `edge-home` (00-traefik).
- [ ] **Doku**: Seite `docs/dienste/<name>.md` nach dem Schema der anderen, Eintrag in `mkdocs.yml`,
      Zeile in [Dienste](../dienste/index.md) und in der Tabelle im `README.md`.

## Auf dem NAS und in den Werkzeugen (nach dem Merge)

1. 1Password-Item `homelab-<name>` anlegen (auf dem Mac).
2. Dataset bzw. Ordner anlegen, z. B. `zfs create fast/appdata/<name>`, Rechte passend zum Container-User.
3. Arcane: **traefik** deployen (neues Netz).
4. Arcane: **keycloak** deployen (neuer Client / Callback).
5. Arcane: neue **Gitsync-App** auf `stacks/<nn>-<name>`, Name exakt `<name>`;
   Env mit `scripts/render-env.sh <name>` setzen; deployen.
6. Arcane: **observability** und **homepage** deployen.
7. Backup-Skript aufs NAS kopieren, falls geändert.
8. Prüfen: Seite lädt mit Login, Probe in *Homelab · Dienste & Erreichbarkeit* grün.

!!! tip "Öffentlich machen?"
    Nur wenn nötig, und dann nach [Cloudflare-Tunnel](../dienste/cloudflared.md#einen-host-veroffentlichen).
