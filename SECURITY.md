# Security- & Best-Practice-Review

Stand: 2026-11-22 (Erstreview 2026-05-25, Security-Check 2026-11-22). Review der `homelab-gitops`-Stacks + `cluster-integration`.
Schweregrade: 🔴 hoch · 🟡 mittel · 🟢 niedrig/Hinweis.

## Behoben

| # | Befund | Schwere | Fix |
|---|--------|:-------:|-----|
| 1 | Traefik mountete `docker.sock` direkt (Host-Root-Risiko) | 🔴 | **docker-socket-proxy** (read-only, `POST=0`); Traefik via `tcp://socket-proxy:2375` |
| 2 | Traefik-Dashboard ohne Auth | 🔴 | Router hinter `sso@docker` (Keycloak) |
| 3 | Ungepinnte Images (`dnsmasq:latest`, `nginx:alpine`, `netboot-console:latest`) | 🔴 | gepinnt (`dnsmasq:2.91`, `nginx:1.27-alpine`, `console:v1`) |
| 4 | oauth2-proxy ließ jeden Realm-User durch | 🟡 | `--allowed-group=lab-users` + `cookie-secure`/`samesite` |
| 5 | Grafana ohne Rollen-Mapping | 🟡 | `ROLE_ATTRIBUTE_PATH` (Gruppe `lab-admins`→Admin), Self-Signup aus |
| 6 | Keine RAM-Limits (24-GB-System) | 🟡 | `mem_limit` auf **allen** Services gesetzt |
| 7 | Paperless-DB ohne Healthcheck | 🟡 | `pg_isready`-Healthcheck |
| 8 | Forgejo-SSH Port-Mismatch (`SSH_LISTEN_PORT` vs. Mapping) | 🟡 | SSH nur über Traefik-Entrypoint `ssh` (`.48:22`, TCP-Passthrough), kein Host-Port; `SSH_PORT=22` in Klon-URLs |
| 9 | NFS `no_root_squash` auf ganzem VLAN | 🟡 | Runbook 1.5: auf Node-IPs `.41–.54` eingeschränkt |
| 10 | Cloudflared exponierte unkontrolliert | 🟡 | explizite `ingress`-Regeln + Catch-all `404` (`config.yml`) |
| 11 | Velero sprach S3 über `http` | 🟢 | auf `https://s3.lab.appsfab.org` (Traefik-TLS, Garage-Backend) umgestellt |
| 12 | Keine kontrollierte Update-Strategie | 🟢 | **Renovate** (`renovate.json`): Major nur nach Freigabe |
| 13 | Registry ohne Vuln-Scanning | 🟢 | Zot **Trivy-CVE-Scanning** + scrub aktiviert (`zot.json`) |
| 14 | Entschlüsselte Secrets-Datei ungeschützt | 🟡 | README: eigenes Dataset `fast/appdata/_secrets`, `chmod 600`, aus Backups ausschließen |
| 15 | Zwei Secret-Quellen (SOPS-Datei unvollständig vs. Arcane-Env) → Drift, kein Rebuild aus Git möglich | 🟡 | 2026-11: SOPS entfernt; 1Password = einzige Quelle, `.env.example` = vollständige `op://`-Liste, CI-Check `scripts/check-env.sh` |
| 16 | Keycloak öffentlich (Tunnel) ohne Brute-Force-Schutz; Admin-Konsole + master-Realm aus dem Internet erreichbar | 🔴 | 2026-11: `bruteForceProtected` + Passwort-Policy im Realm-JSON; Traefik-Router `keycloak-admin` mit `ipallowlist` (nur LAN) für `/admin` und `/realms/master`. Öffentlicher Login auf `auth.appsfab.org` (Realm-`frontendUrl` = Issuer für alle Clients), `auth.lab.appsfab.org` nur noch intern |
| 17 | Kein Alerting | 🔴 | 2026-11: vmalert + Alertmanager → Telegram, blackbox-Probes, Offsite-Backup-Alter als Metrik |
| 18 | Anonymer LAN-Zugriff: Zot lesbar ohne Login, `mirror.lab` offener Docker-Hub-Proxy, `docs-ai`/`home` ohne SSO | 🟡 | 2026-11: Zot `anonymousPolicy: []` (UI per Keycloak-OIDC, Robots `ci`/`pull`), `mirror.lab` nur VLAN 80 + 10 (`MIRROR_ALLOWED_CIDRS`), `docs-ai` + `home` hinter `sso@docker` |
| 19 | Forgejo mit lokalem Passwort-Login aus dem Internet | 🟡 | 2026-11: Web-Login nur per Keycloak-SSO (`ENABLE_INTERNAL_SIGNIN=false`, `/user/login` → Keycloak) |
| 20 | Renovate-Automerge ohne echte Prüfung | 🟡 | 2026-11: `validate` prüft Compose streng (Warnung = Fehler) und dass jedes geänderte Image für `linux/amd64` existiert |
| 21 | Gemeinsames Docker-Netz `edge`: jeder Web-Container erreichte jeden anderen direkt (an `sso@docker` vorbei) | 🟡 | 2026-11: Netze `edge-<stack>`, nur Traefik (und blackbox für Probes) in mehreren; `edge-tunnel` fest `172.31.253.0/24` außerhalb der LAN-Allowlist |
| 22 | Forgejo nahm aus dem Internet Passwörter per Basic Auth an (API, Git-over-HTTPS) → an Keycloak/Passkey/2FA vorbei | 🔴 | 2026-11-22: `ENABLE_BASIC_AUTHENTICATION=false`; nur noch Tokens und SSH |
| 23 | Patches blieben liegen (Renovate-Fenster 2–6 Uhr, GitHub-Cron Stunden zu spät): Forgejo, n8n, cloudflared | 🔴 | 2026-11-22: Automerge „at any time“; dazu `minimumReleaseAge` 3 Tage gegen manipulierte Releases, Actions per Digest |
| 24 | Tunnel und LAN auf demselben Traefik-Entrypoint; oauth2-proxy-Router (`PathPrefix(/oauth2)`) auf jedem Host, also auch öffentlich | 🟡 | 2026-11-22: Entrypoint `tunnel` (:8443) nur für öffentliche Router, cloudflared zeigt darauf; oauth2-proxy nur `*.lab` |
| 25 | Sandbox-VM erreichte das NAS (SSH, SMB, NFS, UI, Arcane) — Filter nur in der VM, die ein Ausbruch übernimmt | 🔴 | 2026-11-22: [NAS-Firewall](docs/nas-firewall/README.md) auf `br88` (nur Antworten); Weg über VLAN 40 siehe I |
| 26 | Arcane (Docker = Root) und VM-VNC aus allen Netzen erreichbar | 🔴 | 2026-11-22: NAS-Firewall, nur VLAN 10; Arcane kann nicht hinter Traefik (startet Traefik selbst) |
| 27 | cadvisor mit `/var/run:ro` = voller Docker-Socket (ro schützt Sockets nicht) | 🟡 | 2026-11-22: cadvisor über `socket-proxy-logs` (`POST=0`) |

## Verbleibend — beim Deploy / bewusst akzeptiert

| # | Punkt | Schwere | Status |
|---|-------|:-------:|--------|
| A | **Realm-Client-Secrets** (`*_OIDC_CLIENT_SECRET`) | 🟡 | **beim Deploy**: einmalig erzeugen, in der Arcane-Env setzen; `keycloak-config-cli` substituiert sie in den Realm (`$(env:...)`). Einmal-Migration: `stacks/02-keycloak/RECONCILE.md` |
| B | **Laufzeit-Semantik** (oauth2-proxy-Group-Claim, Grafana-JMESPath, Flow-IDs) | 🟡 | **beim ersten Deploy verifizieren** — YAML/Logik stimmt, finale Bestätigung nur am laufenden System |
| C | ~~Loki↔Garage intern über `http`~~ | – | entfallen: Loki speichert auf dem Dateisystem (`fast/appdata/loki`, Retention per Compactor), nicht in Garage |
| D | democratic-csi `allowInsecure: true` (selbstsigniertes TrueNAS-Cert) | 🟢 | akzeptiert intern; optional interne CA + Pinning |
| E | `backup`-Pool ohne Redundanz (Single-Disk) | 🟢 | bekannt; keine Live-RWX-Daten drauf (Phase 4 verschiebt k8s-NFS auf `data`) |
| F | Version-Pins von VictoriaMetrics/Garage/Zot/dnsmasq | 🟢 | Renovate hält sie aktuell (auch das restic-Image in `docs/nas-backup/backup-offsite.sh`, Regex-Manager) |
| H | Garage (`data/garage`: etcd- + Longhorn-Backups des Clusters) ohne Snapshot/Replikation/Offsite | 🟡 | offen |
| I | Sandbox-VM über VLAN 40 im übrigen LAN (Mac Studio, UniFi-UI); VLAN 40 → 80 in UniFi offen | 🔴 | offen: UniFi-Regel (VM-IP nur Internet), später VLAN „Sandbox“ |
| J | Mac Studio: Ollama/LM Studio ohne Auth, pf aus `docs/mac-studio-llm.md` noch nicht eingerichtet | 🔴 | zurückgestellt (Christian, 2026-11-22) |
| K | TrueNAS: 2FA aus, SSH mit Passwort, UI auch per HTTP ohne Umleitung | 🟡 | offen: in TrueNAS einschalten (2FA, HTTPS-Umleitung, `ssh.update passwordauth=false`) |
| L | Cluster-VLAN 80 = NAS-Management, Traefik, Mac Studio | 🟡 | vor dem Cluster-Neuaufbau UniFi-Regeln |
| M | Öffentliches Repo ohne Secret Scanning/Push Protection/Dependabot-Alerts; alte SOPS-Secrets in der Historie | 🟡 | offen: in GitHub einschalten; age-Key vernichten oder alte Secrets rotieren |
| N | VictoriaMetrics/Loki/Alertmanager ohne Auth im Netz `edge-n8n` (Silences/Löschen möglich) | 🟢 | offen: Alertmanager Basic Auth, vmauth read-only |

## Grundsätzlich gut (bestätigt)

- Keine Klartext-Secrets im Repo (`${VARS}` + `op://`-Referenzen), `.gitignore` greift; Werte nur in 1Password.
- Datenbanken nur in internen Netzen (kein Port-Mapping), Web-Dienste nur über Traefik.
- Image-Pinning durchgängig (Tag), Actions per Digest; Daten getrennt von Stack-Definition (eigene Datasets).
- IaC offsite bei GitHub → die Reproduzierbarkeit, die die Update-Katastrophe verhindert.
- Ressourcen-Limits auf allen Services → kein einzelner Container kann das 24-GB-NAS lahmlegen.
