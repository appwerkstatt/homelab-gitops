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
4. **Secrets verschlüsselt.** Niemals Klartext-Secrets committen — siehe `.sops.yaml` / `.env.example`.

## Bootstrap-Reihenfolge

```
GitHub (dieses Repo)
   └─> Arcane (TrueNAS-App, manuell installiert)
         └─> 00-traefik         (legt das externe Netz "edge" an, TLS via DNS-01)
               └─> 01-forgejo + 02-keycloak   (Identity/Infra-Fundament)
                     └─> Rest:  11-paperless · 12-cloudflared · 20-observability
                                03-oauth2-proxy · 21-minio · 22-harbor · 30-netboot · 40-homepage
```

1. **Arcane** als TrueNAS-App installieren (App-Pool = `fast`), dieses Repo als GitOps-Quelle hinterlegen.
2. **00-traefik** zuerst — erstellt das gemeinsame Docker-Netz `edge` und holt das Wildcard-Zertifikat.
3. **01-forgejo** + **02-keycloak** — danach kann GitHub optional nach Forgejo gespiegelt werden (GitHub bleibt die Wahrheit).
4. Restliche Stacks. Daten vorher gemäß Runbook Phase 3 migrieren (Keycloak/Paperless = PG 17, Forgejo/Grafana/paperless-ai = Dateien/SQLite).

## Stacks

| Stack | Dienste | Daten-Dataset |
|-------|---------|---------------|
| `00-traefik` | Traefik 3.6.8 (Reverse Proxy, ACME DNS-01) | `fast/appdata/traefik` |
| `01-forgejo` | Forgejo 14.0.2 (SQLite) | `fast/appdata/forgejo` |
| `02-keycloak` | Keycloak 26.5.4 + Postgres 17.8 (Realm-as-Code, Passkeys) | `fast/appdata/keycloak` |
| `03-oauth2-proxy` | oauth2-proxy — Traefik-ForwardAuth gegen Keycloak | – (zustandslos) |
| `11-paperless` | Paperless-ngx 2.20.7 + Postgres 17.8 + Redis + paperless-ai 3.0.9 | `fast/appdata/paperless`, `data/paperless` |
| `12-cloudflared` | Cloudflared 2026.2.0 (Tunnel) | `fast/appdata/cloudflared` |
| `20-observability` | VictoriaMetrics + Loki + Grafana 12.3.3 + node-exporter + cadvisor + alertmanager + otel-collector | `fast/appdata/{vm,loki,grafana}` |
| `21-minio` | MinIO (S3: loki, velero, artifacts) | `data/minio` |
| `22-harbor` | Harbor (Registry + Trivy) — via offiziellem Installer | `data/harbor` |
| `30-netboot` | dnsmasq (macvlan `.49`) + nginx + Go-Konsole — **Custom-App** | `data/provisioning` |
| `40-homepage` | Homepage-Dashboard (Config-as-Code, zentrale Einstiegsseite) | – (Config im Repo) |

## Konventionen

- **Netz `edge`:** extern, von `00-traefik` angelegt; alle web-exponierten Stacks hängen sich daran und werden per Traefik-Labels geroutet.
- **Domain:** `*.lab.appsfab.org` (Split-Horizon → `192.168.80.50`), Wildcard-TLS via Cloudflare-DNS-01.
- **SSO:** Keycloak-OIDC nativ, wo die App es kann; sonst Traefik-ForwardAuth (`auth.lab.appsfab.org`).
- **Image-Versionen** sind gepinnt (kein `latest`) — Updates bewusst per PR/Commit (Renovate optional).

## Secrets

Niemals Klartext committen. Zwei Wege (siehe `.env.example`):
- **SOPS + age** (empfohlen): `secrets.enc.env` verschlüsselt im Repo, age-Key auf dem NAS + in 1Password.
- **Arcane-Environment**: Variablen außerhalb des Repos in Arcane pflegen.

**Entschlüsselte Secrets auf dem NAS absichern:** Die zur Laufzeit entschlüsselte `secrets.env`
(bzw. der age-Key) gehört auf ein eigenes Dataset `fast/appdata/_secrets` mit `chmod 600` und
Owner `apps`. Dieses Dataset von Snapshot-Cloud-Syncs ausschließen, damit Secrets nicht
unbeabsichtigt in B2/Backups landen.

Aus dem alten System zu übernehmen (in 1Password, dann neu setzen): Forgejo `jwt/private.pem`,
`cloudflared/credentials.json`, `paperless-ai/.env`, DB-Passwörter. **Realm-Client-Secrets**
(`CHANGE_ME_*`) nach dem Keycloak-Import in der UI neu generieren — die Platzhalter nie produktiv lassen.
