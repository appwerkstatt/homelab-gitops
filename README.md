# homelab-gitops

Infrastruktur-als-Code für das TrueNAS-Homelab (UGREEN DXP4800 Plus, TrueNAS 25.10).
**Dies ist die externe Wahrheit** — das NAS ist nur die austauschbare Ausführungsumgebung.
Verwaltet von **Arcane** (TrueNAS-App), das dieses Repo überwacht und Stacks per GitOps deployt.

> Entstanden nach einer Update-Katastrophe (Custom-Docker am System vorbei → vom Update zerlegt).
> Lehre: kein Docker am TrueNAS-System vorbei, alles als Code, Daten getrennt von Definition.

## Prinzipien

1. **Kein Custom-Docker.** Container laufen über die TrueNAS-App-Engine; Arcane verwaltet die Stacks, ohne den Daemon umzukonfigurieren.
2. **Alles als Code.** Jeder Stack ist ein `stacks/<n>-<name>/compose.yaml`. Was nicht hier steht, existiert nicht.
3. **Daten getrennt.** Persistente Daten liegen auf eigenen Datasets (`/mnt/fast/appdata/<dienst>`, `/mnt/data/...`), niemals im Repo.
4. **Secrets in 1Password.** Niemals Klartext-Secrets committen. Das Repo enthält nur die Liste (`.env.example` mit `op://`-Referenzen), die Werte liegen in 1Password.

## Bootstrap-Reihenfolge

```
GitHub (dieses Repo)
   └─> Arcane (TrueNAS-App, manuell installiert)
         └─> 00-traefik         (legt das externe Netz "edge" an, TLS via DNS-01)
               └─> 01-forgejo + 02-keycloak   (Identity/Infra-Fundament)
                     └─> Rest:  11-paperless · 12-cloudflared · 20-observability
                                03-oauth2-proxy · 21-garage · 22-harbor · 30-netboot · 40-homepage
```

1. **Arcane** als TrueNAS-App installieren (App-Pool = `fast`), dieses Repo als GitOps-Quelle hinterlegen.
2. **00-traefik** zuerst — erstellt das gemeinsame Docker-Netz `edge` und holt das Wildcard-Zertifikat.
3. **01-forgejo** + **02-keycloak** — danach kann GitHub optional nach Forgejo gespiegelt werden (GitHub bleibt die Wahrheit).
   - Realm-Änderungen reconcilen über `keycloak-config-cli` bei jedem Redeploy — siehe `stacks/02-keycloak/RECONCILE.md` (inkl. einmaliger Secret-Migration).
4. Restliche Stacks. Daten vorher gemäß Runbook Phase 3 migrieren (Keycloak/Paperless = PG 17, Forgejo/Grafana/paperless-ai = Dateien/SQLite).

## Stacks

| Stack | Dienste | Daten-Dataset |
|-------|---------|---------------|
| `00-traefik` | Traefik 3.6.8 (Reverse Proxy, ACME DNS-01) | `fast/appdata/traefik` |
| `01-forgejo` | Forgejo 14.0.2 (SQLite) | `fast/appdata/forgejo` |
| `02-keycloak` | Keycloak 26.5.4 + Postgres 17.8 (Realm-as-Code via keycloak-config-cli, Passkeys) | `fast/appdata/keycloak` |
| `03-oauth2-proxy` | oauth2-proxy — Traefik-ForwardAuth gegen Keycloak | – (zustandslos) |
| `11-paperless` | Paperless-ngx 2.20.7 + Postgres 17.8 + Redis + paperless-ai 3.0.9 | `fast/appdata/paperless`, `data/paperless` |
| `12-cloudflared` | Cloudflared 2026.2.0 (Tunnel) | `fast/appdata/cloudflared` |
| `20-observability` | VictoriaMetrics + Loki + Grafana 12.3.3 + node-exporter + cadvisor + alertmanager + otel-collector | `fast/appdata/{vm,loki,grafana}` |
| `21-garage` | Garage v2.3.0 (S3: loki, velero, artifacts) — schlank, aktiv gepflegt | `fast/appdata/garage/meta`, `data/garage/data` |
| `22-harbor` | Harbor (Registry + Trivy) — via offiziellem Installer | `data/harbor` |
| `23-registry-cache` | registry:2 (proxy) — Pull-Through-Cache für Docker Hub (docker.io), getrennt von der privaten Registry | `data/registry-cache` |
| `30-netboot` | dnsmasq (macvlan `.49`) + nginx + Go-Konsole — **Custom-App** | `data/provisioning` |
| `40-homepage` | Homepage-Dashboard (Config-as-Code, zentrale Einstiegsseite) | – (Config im Repo) |

> **Neuer Stack ⇒ neue Arcane-Gitsync-App**, gleich wie das `name:`-Feld im compose benannt
> (z. B. `registry-cache`), sonst entsteht Drift wie garage→garages3 (s. `## Konventionen`).

## Konventionen

- **Netz `edge`:** extern, von `00-traefik` angelegt; alle web-exponierten Stacks hängen sich daran und werden per Traefik-Labels geroutet.
- **Domain:** `*.lab.appsfab.org` (Split-Horizon → `192.168.80.50`), Wildcard-TLS via Cloudflare-DNS-01.
- **SSO:** Keycloak-OIDC nativ, wo die App es kann; sonst Traefik-ForwardAuth; Login unter `auth.appsfab.org` (Admin-Konsole nur LAN: `auth.lab.appsfab.org`).
- **Image-Versionen** sind gepinnt (kein `latest`) — Updates bewusst per PR/Commit (Renovate optional).
- **Arcane setzt den Compose-Projektnamen, nicht `name:`.** Arcane startet jeden Stack als
  `docker compose -p <slug> …`, wobei `<slug>` aus dem Anzeigenamen der Gitsync-App stammt
  (z. B. „Garage S3" → `garages3`, „Registry ZOT" → `registryzot`). `-p` hat Vorrang vor dem
  `name:`-Feld im `compose.yaml`, das damit unter Arcane rein kosmetisch ist. Dass die Live-Projekte
  (Container `garages3-garage-1`, `registryzot-zot-1`) **nicht** zu `name: garage` bzw.
  `name: registry` passen, ist deshalb **erwartet — kein Fehler**, sondern ein Artefakt der
  Arcane-Projektbenennung. **Konsequenz:** Stacks niemals von Hand mit `docker compose up` **ohne**
  `-p <slug>` starten. Sonst legt Compose ein zweites Projekt (Name aus `name:` bzw. dem
  Verzeichnis-Basename) auf **denselben** Bind-Mounts an; bei zustandsbehafteten Stores
  (Garage-LMDB unter `/mnt/data/garage`, Zot-Storage unter `/mnt/data/harbor/zot`) droht
  Datenkorruption durch zwei Prozesse auf demselben Datenverzeichnis. Deployen läuft immer über Arcane.

## Secrets

**1Password (Vault `AppsFab`) ist die einzige Quelle der Wahrheit.** Im Repo steht nur, *welche*
Secrets es gibt und *wo* sie in 1Password liegen; die Werte selbst nie.

- **`.env.example`** listet **jede** Variable, die ein `compose.yaml` per `${VAR}` liest — Secrets
  als `op://AppsFab/<item>/<feld>`-Referenz, unkritische Konfiguration als Klartext.
  CI (`validate` → `scripts/check-env.sh`) schlägt fehl, wenn ein Stack eine Variable nutzt, die
  dort fehlt.
- **Arcane-Environment** ist nur die Laufzeit-Kopie. Befüllen bzw. nach einer Änderung neu setzen:
  ```bash
  scripts/render-env.sh keycloak      # braucht die 1Password CLI (`op`), angemeldet
  ```
  gibt genau die Variablen des Stacks aus → in **Arcane → Stack → Environment** einfügen →
  Redeploy. Nie in eine Datei im Repo umleiten.
- **Secret ändern/rotieren:** zuerst in 1Password, dann `render-env.sh` und in Arcane setzen.
  Nie nur in Arcane ändern — sonst driftet die Quelle.
- **Neue Variable:** in `compose.yaml` verwenden, in `.env.example` mit `op://`-Referenz eintragen,
  Item/Feld in 1Password anlegen.
- **Datei-Secrets** (cloudflared `credentials.json`, Zot-`htpasswd`, Netboot-Wipe-Key,
  Forgejo `jwt/private.pem`, `restic-b2.env`) liegen auf dem NAS unter `fast/appdata/…` (`chmod 600`)
  und als **1Password-Dokument**; die Zuordnung steht unten in `.env.example`.
- **Realm-Client-Secrets** (`*_OIDC_CLIENT_SECRET`) gehören in die Env des `keycloak`-Stacks **und**
  des jeweiligen Consumers — `keycloak-config-cli` substituiert sie beim Reconcile in den Realm
  (`$(env:...)`). Fehlt eins, setzt kcc es auf leer. Siehe `stacks/02-keycloak/RECONCILE.md`.

SOPS/age wurde 2026-11 entfernt: `secrets.enc.env` war unvollständig und wurde von Arcane nie
gelesen (zwei Quellen → Drift). Der alte age-Key in 1Password kann archiviert werden.
