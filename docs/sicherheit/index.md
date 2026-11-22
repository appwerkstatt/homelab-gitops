# Sicherheit

## Zugriffsmodell

| Ebene | Maßnahme |
|---|---|
| Internet | nur drei Hosts über den Cloudflare-Tunnel (`git`, `auth`, `hooks`), keine Port-Freigaben am Router |
| Keycloak öffentlich | Brute-Force-Schutz, Passwort-Policy, Passkey/2FA Pflicht, ROPC aus, Admin-Konsole + `master`-Realm nur aus dem LAN |
| LAN | `*.lab` nur intern; Web-Dienste nur über Traefik, mit OIDC oder `sso@docker` (Gruppe `lab-users`) |
| Container | ein `edge`-Netz pro Stack, Datenbanken nur in internen Netzen, Docker-Socket nur read-only über socket-proxy, `mem_limit` überall |
| Registry | kein anonymer Zugriff, Trivy-CVE-Scan |
| LLM-Host | Ollama und LM Studio haben keine Auth; pf auf dem Mac Studio lässt nur das NAS zu |
| Sandbox | Code des n8n-Assistenten läuft in einer eigenen VM, nicht auf dem NAS |
| Secrets | nur in 1Password, CI prüft die Vollständigkeit der Liste |
| Updates | Renovate nachts, Patches automatisch nach grüner CI, Minor/Major per Hand |

## Erkennen

- Fehlgeschlagene Logins und Brute-Force-Sperren in Keycloak lösen Alarme aus (`KeycloakLoginFailures`,
  `KeycloakUserLockedOut`).
- Alle Container-Logs landen in Loki (31 Tage).
- `ServiceDown` und `CertProbeFailing` melden Ausfälle und TLS-Probleme.

## Review

Das laufende Security-Review mit allen behobenen und offenen Befunden steht in
[`SECURITY.md`](https://github.com/appwerkstatt/homelab-gitops/blob/main/SECURITY.md). Offen sind dort vor allem: Garage ohne Backup (bewusst) und die
Single-Disk `backup`.
