# Sicherheit

## Zugriffsmodell

| Ebene | Maßnahme |
|---|---|
| Internet | nur drei Hosts über den Cloudflare-Tunnel (`git`, `auth`, `hooks`), keine Port-Freigaben am Router. Der Tunnel landet auf einem eigenen Traefik-Entrypoint (`:8443`), auf dem nur deren Router hören |
| Forgejo öffentlich | Web nur per SSO, API und Git über HTTPS nur mit Token (kein Passwort per Basic Auth) |
| Keycloak öffentlich | Brute-Force-Schutz, Passwort-Policy, Passkey/2FA Pflicht, ROPC aus, Admin-Konsole + `master`-Realm nur aus dem LAN |
| LAN | `*.lab` nur intern; Web-Dienste nur über Traefik, mit OIDC oder `sso@docker` (Gruppe `lab-users`), Admin-Werkzeuge hinter `sso-admin@docker` (Gruppe `lab-admins`), siehe [Rechtekonzept](rechtekonzept.md) |
| Container | ein `edge`-Netz pro Stack, Datenbanken nur in internen Netzen, Docker-Socket nur über socket-proxy mit `POST=0` (Traefik, Alloy, cadvisor), `mem_limit` überall |
| Registry | kein anonymer Zugriff, Trivy-CVE-Scan |
| LLM-Host | Ollama und LM Studio haben keine Auth; pf auf dem Mac Studio lässt nur das NAS zu |
| Sandbox | Code des n8n-Assistenten läuft in einer eigenen VM, nicht auf dem NAS; die [NAS-Firewall](../nas-firewall/README.md) lässt von dort keine neuen Verbindungen zum NAS zu |
| NAS-Management | Arcane und VM-Konsole (VNC) nur aus VLAN 10 ([NAS-Firewall](../nas-firewall/README.md)) |
| Secrets | nur in 1Password, CI prüft die Vollständigkeit der Liste |
| Updates | Renovate, Patches automatisch nach grüner CI und 3 Tagen Wartezeit, Minor/Major per Hand, Actions per Digest gepinnt |

## Erkennen

- Fehlgeschlagene Logins und Brute-Force-Sperren in Keycloak lösen Alarme aus (`KeycloakLoginFailures`,
  `KeycloakUserLockedOut`).
- Alle Container-Logs landen in Loki (31 Tage).
- `ServiceDown` und `CertProbeFailing` melden Ausfälle und TLS-Probleme.

## Review

Das laufende Security-Review mit allen behobenen und offenen Befunden steht in
[`SECURITY.md`](https://github.com/appwerkstatt/homelab-gitops/blob/main/SECURITY.md). Offen sind dort vor allem: Mac-Studio-pf, UniFi-Regeln zwischen den VLANs,
TrueNAS-2FA, Garage ohne Backup (bewusst) und die Single-Disk `backup`.
