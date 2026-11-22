# homelab-gitops

Infrastruktur-als-Code für das TrueNAS-Homelab (UGREEN DXP4800 Plus, TrueNAS 25.10).
**Dies ist die externe Wahrheit** — das NAS ist nur die austauschbare Ausführungsumgebung.
Verwaltet von **Arcane** (TrueNAS-App), das dieses Repo überwacht und Stacks per GitOps deployt.

**Handbuch:** <https://doku.lab.appsfab.org> (LAN, hinter SSO) bzw. als Markdown unter [`docs/`](docs/index.md).
Architektur, alle Dienste, Backup/Restore, Alarme und Runbooks stehen dort.

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
                     └─> Rest:  03-oauth2-proxy · 11-paperless · 12-cloudflared · 13-n8n · 14-plane · 15-doku · 20-observability
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
| `14-plane` | Plane CE (Projekte/Issues/Kanban) + Postgres 17 + Valkey + RabbitMQ + MinIO (Silo); Login Keycloak davor + Plane-Konto (CE ohne OIDC), `stacks/14-plane/README.md` | LAN (`plane`, hinter SSO) | `fast/appdata/plane` |
| `15-doku` | Homelab-Handbuch (MkDocs Material, aus `docs/` dieses Repos, baut `main` alle 5 min neu) + nginx | LAN (`doku`, hinter SSO) | – (Build im Docker-Volume) |
| `20-observability` | VictoriaMetrics + Loki (Dateisystem, Container-Logs via Alloy) + Grafana + node-exporter + cadvisor + vmalert + Alertmanager (→ Telegram) + blackbox-exporter | LAN (`grafana`, Keycloak-OIDC) | `fast/appdata/{vm,loki,grafana}` |
| `21-garage` | Garage (S3; Buckets: velero, artifacts, k3s-etcd-backups, longhorn-backup; `loki` ungenutzt) | LAN (`s3`) | `fast/appdata/garage/meta`, `data/garage/data` |
| `22-harbor` | **Zot** (OCI-Registry). Ordnername historisch (Arcane-Pfad), Harbor wird nicht genutzt | LAN (`registry`); UI per Keycloak-SSO, Pull nur mit Login | `data/harbor/zot` |
| `23-registry-cache` | registry (proxy) — Pull-Through-Cache für Docker Hub, getrennt von Zot | LAN (`mirror`, nur VLAN 80 + 10) | `data/registry-cache` |
| `30-netboot` | dnsmasq (macvlan `.49`) + nginx (`.47`) + Go-Konsole — **Custom-App** | LAN (`netboot`, Keycloak-OIDC) | `data/provisioning` |
| `40-homepage` | Homepage-Dashboard (Config-as-Code) | LAN (`home`, hinter SSO) | – (Config im Repo) |

**Außerhalb von Arcane:** `vms/n8n-sandbox` — Code-Sandbox des n8n-Assistenten in einer eigenen VM
(privilegierter Docker-in-Docker-Runner, deshalb nicht auf dem NAS). Von Hand nach `vms/n8n-sandbox/README.md`.

> **Neuer Stack ⇒ neue Arcane-Gitsync-App**, gleich wie das `name:`-Feld im compose benannt
> (z. B. `registry-cache`), sonst entsteht Drift wie garage→garages3 (s. `## Konventionen

Die ausführlichen Regeln stehen im Handbuch unter
[Architektur → Konventionen](docs/architektur/konventionen.md) und [Netzwerk & Domains](docs/architektur/netzwerk.md).
Die wichtigsten in Kürze:

- **Netze `edge-<stack>`** legt `00-traefik` an; jeder Stack hängt nur an seinem eigenen. Neuer Stack ⇒ Netz zuerst in `00-traefik`.
- **Domains:** `*.lab.appsfab.org` nur intern (Traefik `192.168.80.48`), `*.appsfab.org` öffentlich über den Tunnel,
  und zwar **nur** `git`, `auth` und `hooks` (`stacks/12-cloudflared/config.yml`).
- **SSO:** Keycloak-OIDC, wo die App es kann, sonst `sso@docker` (oauth2-proxy). Login unter `auth.appsfab.org`.
- **Images gepinnt**, `mem_limit` überall, Renovate mergt Patches nach grünem `validate`.
- **Arcane setzt den Compose-Projektnamen** aus dem Namen der Gitsync-App, nicht aus `name:`
  (z. B. `garages3`, `registryzot`). Deshalb **nie** `docker compose up` ohne `-p <slug>`:
  ein zweites Projekt auf denselben Bind-Mounts kann Garage- oder Zot-Daten zerstören.
- **Revisionszähler:** Realm-Änderung ⇒ `KCC_REALM_REV`, Tunnel-Änderung ⇒ `CF_INGRESS_REV` hochzählen.

## Secrets

**1Password (Vault `AppsFab`) ist die einzige Quelle der Wahrheit.** `.env.example` listet jede Variable
(Secrets als `op://`-Referenz, CI prüft das), `scripts/render-env.sh <stack>` erzeugt daraus die Arcane-Env.
Ablauf, Datei-Secrets und Secrets, die man nie neu erzeugt: [Handbuch → Secrets](docs/sicherheit/secrets.md).
