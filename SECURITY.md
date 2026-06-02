# Security- & Best-Practice-Review

Stand: 2026-05-25. Review der `homelab-gitops`-Stacks + `cluster-integration`.
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
| 8 | Forgejo-SSH Port-Mismatch (`SSH_LISTEN_PORT` vs. Mapping) | 🟡 | durchgängig `2222`, `SSH_LISTEN_PORT` explizit |
| 9 | NFS `no_root_squash` auf ganzem VLAN | 🟡 | Runbook 1.5: auf Node-IPs `.41–.54` eingeschränkt |
| 10 | Cloudflared exponierte unkontrolliert | 🟡 | explizite `ingress`-Regeln + Catch-all `404` (`config.yml`) |
| 11 | Velero sprach S3 über `http` | 🟢 | auf `https://s3.lab.appsfab.org` (Traefik-TLS, Garage-Backend) umgestellt |
| 12 | Keine kontrollierte Update-Strategie | 🟢 | **Renovate** (`renovate.json`): Major nur nach Freigabe |
| 13 | Registry ohne Vuln-Scanning | 🟢 | Zot **Trivy-CVE-Scanning** + scrub aktiviert (`zot.json`) |
| 14 | Entschlüsselte Secrets-Datei ungeschützt | 🟡 | README: eigenes Dataset `fast/appdata/_secrets`, `chmod 600`, aus Backups ausschließen |

## Verbleibend — beim Deploy / bewusst akzeptiert

| # | Punkt | Schwere | Status |
|---|-------|:-------:|--------|
| A | **Realm-Client-Secrets** (`*_OIDC_CLIENT_SECRET`) | 🟡 | **beim Deploy**: einmalig erzeugen, in der Arcane-Env setzen; `keycloak-config-cli` substituiert sie in den Realm (`$(env:...)`). Einmal-Migration: `stacks/02-keycloak/RECONCILE.md` |
| B | **Laufzeit-Semantik** (oauth2-proxy-Group-Claim, Grafana-JMESPath, Flow-IDs) | 🟡 | **beim ersten Deploy verifizieren** — YAML/Logik stimmt, finale Bestätigung nur am laufenden System |
| C | Loki↔Garage intern über `http` (`http://garage:3900`, gleicher Host) | 🟢 | akzeptiert (VLAN-intern); optional auf `https` heben |
| D | democratic-csi `allowInsecure: true` (selbstsigniertes TrueNAS-Cert) | 🟢 | akzeptiert intern; optional interne CA + Pinning |
| E | `backup`-Pool ohne Redundanz (Single-Disk) | 🟢 | bekannt; keine Live-RWX-Daten drauf (Phase 4 verschiebt k8s-NFS auf `data`) |
| F | Version-Pins von VictoriaMetrics/Garage/Zot/dnsmasq | 🟢 | „vor Deploy aktuelle Version prüfen"-Kommentare gesetzt; Renovate hält sie danach aktuell |

## Grundsätzlich gut (bestätigt)

- Keine Klartext-Secrets im Repo (`${VARS}`/Platzhalter), `.gitignore` + SOPS greifen.
- Datenbanken nur in internen Netzen (kein Port-Mapping), Web-Dienste nur über Traefik.
- Image-Pinning durchgängig; Daten getrennt von Stack-Definition (eigene Datasets).
- IaC offsite bei GitHub → die Reproduzierbarkeit, die die Update-Katastrophe verhindert.
- Ressourcen-Limits auf allen Services → kein einzelner Container kann das 24-GB-NAS lahmlegen.
