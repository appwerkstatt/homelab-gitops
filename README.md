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
         └─> 00-traefik         (legt die Netze "edge-<stack>" an, TLS via DNS-01)
               └─> 01-forgejo + 02-keycloak   (Identity/Infra-Fundament)
                     └─> Rest:  03-oauth2-proxy · 11-paperless · 12-cloudflared · 13-n8n · 20-observability
                                21-garage · 22-harbor (= Zot) · 23-registry-cache · 30-netboot · 40-homepage
```

1. **Arcane** als TrueNAS-App installieren (App-Pool = `fast`), dieses Repo als GitOps-Quelle hinterlegen.
2. **00-traefik** zuerst — erstellt die Docker-Netze `edge-<stack>` und holt das Wildcard-Zertifikat.
3. **01-forgejo** + **02-keycloak** — danach kann GitHub optional nach Forgejo gespiegelt werden (GitHub bleibt die Wahrheit).
   - Realm-Änderungen reconcilen über `keycloak-config-cli` bei jedem Redeploy — siehe `stacks/02-keycloak/RECONCILE.md` (inkl. einmaliger Secret-Migration).
4. Restliche Stacks. Daten vorher gemäß Runbook Phase 3 migrieren (Keycloak/Paperless = PG 17, Forgejo/Grafana/paperless-ai = Dateien/SQLite).

## Stacks

Versionen stehen bewusst **nicht** hier, sondern nur im jeweiligen `compose.yaml` (Renovate hält sie aktuell).

| Stack | Dienste | Erreichbar | Daten-Dataset |
|-------|---------|------------|---------------|
| `00-traefik` | Traefik (macvlan `.48`, ACME DNS-01) + docker-socket-proxy (read-only) | LAN; Dashboard hinter SSO | `fast/appdata/traefik` |
| `01-forgejo` | Forgejo (SQLite); Web-Login nur per Keycloak-SSO, Git-SSH über Traefik `.48:22` | **Internet** (`git.appsfab.org`, Tunnel) | `fast/appdata/forgejo` |
| `02-keycloak` | Keycloak + Postgres 17 + keycloak-config-cli (Realm-as-Code, Passkeys) | **Internet** (`auth.appsfab.org`, Login); Admin nur LAN (`auth.lab.appsfab.org`) | `fast/appdata/keycloak` |
| `03-oauth2-proxy` | oauth2-proxy — Traefik-ForwardAuth (`sso@docker`) gegen Keycloak | intern | – (zustandslos) |
| `11-paperless` | Paperless-ngx + Postgres 17 + Redis + paperless-ai (Ollama auf `192.168.80.30`) | LAN (`docs`; `docs-ai` hinter SSO) | `fast/appdata/paperless`, `data/paperless` |
| `12-cloudflared` | Cloudflare-Tunnel (nur Hosts aus `config.yml`, Rest 404) | – | `fast/appdata/cloudflared` |
| `13-n8n` | n8n + Postgres 17; LLMs über Ollama auf dem Mac Studio (`192.168.80.30`, nur vom NAS erreichbar, `docs/mac-studio-llm.md`) | LAN (`n8n`, Editor hinter SSO; `/webhook*` ohne SSO); **Internet** nur `hooks.appsfab.org/webhook/` + `/webhook-test/` (Tunnel) | `fast/appdata/n8n` |
| `20-observability` | VictoriaMetrics + Loki (Dateisystem, Container-Logs via Alloy) + Grafana + node-exporter + cadvisor + vmalert + Alertmanager (→ Telegram) + blackbox-exporter | LAN (`grafana`, Keycloak-OIDC) | `fast/appdata/{vm,loki,grafana}` |
| `21-garage` | Garage (S3; Buckets: velero, artifacts, k3s-etcd-backups, longhorn-backup; `loki` ungenutzt) | LAN (`s3`) | `fast/appdata/garage/meta`, `data/garage/data` |
| `22-harbor` | **Zot** (OCI-Registry). Ordnername historisch (Arcane-Pfad), Harbor wird nicht genutzt | LAN (`registry`); UI per Keycloak-SSO, Pull nur mit Login | `data/harbor/zot` |
| `23-registry-cache` | registry (proxy) — Pull-Through-Cache für Docker Hub, getrennt von Zot | LAN (`mirror`, nur VLAN 80 + 10) | `data/registry-cache` |
| `30-netboot` | dnsmasq (macvlan `.49`) + nginx (`.47`) + Go-Konsole — **Custom-App** | LAN (`netboot`, Keycloak-OIDC) | `data/provisioning` |
| `40-homepage` | Homepage-Dashboard (Config-as-Code) | LAN (`home`, hinter SSO) | – (Config im Repo) |

**Außerhalb von Arcane:** `vms/n8n-sandbox` — Code-Sandbox des n8n-Assistenten in einer eigenen VM
(privilegierter Docker-in-Docker-Runner, deshalb nicht auf dem NAS). Von Hand nach `vms/n8n-sandbox/README.md`.

> **Neuer Stack ⇒ neue Arcane-Gitsync-App**, gleich wie das `name:`-Feld im compose benannt
> (z. B. `registry-cache`), sonst entsteht Drift wie garage→garages3 (s. `## Konventionen`).

## Konventionen

- **Netze `edge-<stack>`:** von `00-traefik` angelegt, im Stack als `external`. Jeder web-exponierte Stack hängt
  nur an seinem eigenen Netz, Traefik an allen → Backends erreichen sich nicht gegenseitig (kein Umgehen von
  `sso@docker`). Geroutete Dienste setzen `traefik.docker.network=edge-<stack>`. Ausnahmen, bewusst:
  blackbox (Probes, mehrere Netze), Forgejo zusätzlich in `edge-netboot` (Konsole klont direkt).
  Server-seitige Aufrufe an `auth.appsfab.org`/`auth.lab.appsfab.org` laufen über Traefiks Netz-Aliase.
  Neuer Stack ⇒ Netz in `00-traefik` ergänzen (Netz + Traefik-Attachment), Traefik zuerst deployen.
- **Domains:** `*.lab.appsfab.org` = nur intern (Split-Horizon → Traefik `192.168.80.48`, macvlan `vlan80`;
  der NAS-Host `.50` erreicht `.48` wegen Hairpin nicht → NAS-lokal `127.0.0.1:<port>`).
  `*.appsfab.org` = öffentlich über den Cloudflare-Tunnel, **nur** `git.appsfab.org`, `auth.appsfab.org` und `hooks.appsfab.org` (nur `/webhook/` + `/webhook-test/` von n8n)
  (`stacks/12-cloudflared/config.yml`; Cloudflares Gratis-Zertifikat deckt nur eine Ebene ab).
  TLS: Let's-Encrypt-Wildcard via Cloudflare-DNS-01.
- **SSO:** Keycloak-OIDC nativ, wo die App es kann; sonst Traefik-ForwardAuth; Login unter `auth.appsfab.org` (Admin-Konsole nur LAN: `auth.lab.appsfab.org`).
- **Image-Versionen** sind gepinnt (kein `latest`). Renovate (nächtlich) mergt Patches automatisch, wenn
  `validate` grün ist (Compose streng, Images existieren für `linux/amd64`); Minor/Major per Hand.
- **Alerting:** vmalert → Alertmanager → Telegram (`stacks/20-observability/config/alerts.yml`), blackbox-Probes
  für alle Dienste, Offsite-Backup-Alter über node-exporter-Textfile.
- **Registry:** Zot verlangt Login. Menschen: Keycloak-SSO in der UI, CLI per Zot-API-Key; Robots im htpasswd
  (`ci` = Push, `pull` = NAS/Cluster). Details `stacks/22-harbor/README.md`.
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
