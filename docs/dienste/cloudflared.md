# 12-cloudflared

| | |
|---|---|
| **Zweck** | Cloudflare-Tunnel: macht genau drei Hosts aus dem Internet erreichbar, ohne Port-Freigabe am Router |
| **Öffentliche Hosts** | `git.appsfab.org`, `auth.appsfab.org`, `hooks.appsfab.org` |
| **Daten** | `fast/appdata/cloudflared/credentials.json` (auch in 1Password) |
| **Quelle** | [`stacks/12-cloudflared/config.yml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/12-cloudflared/config.yml) |

Der Tunnel reicht jeden erlaubten Host an `https://traefik:443` weiter (SNI = Hostname). Alles andere
beantwortet die Catch-all-Regel mit 404. Weil der Verkehr aus `edge-tunnel` (`172.31.253.0/24`) kommt,
greifen die LAN-Allowlists nicht, z. B. für die Keycloak-Admin-Konsole.

## Einen Host veröffentlichen

1. Nur wenn es wirklich nötig ist. Der Name muss **einstufig** sein (`<name>.appsfab.org`).
2. In `config.yml` einen `ingress`-Eintrag vor dem Catch-all ergänzen.
3. **`CF_INGRESS_REV`** in `compose.yaml` hochzählen, sonst läuft der Tunnel mit den alten Regeln weiter.
4. DNS-Eintrag anlegen (auf dem Mac): `cloudflared tunnel route dns <tunnel> <name>.appsfab.org`.
5. Im Ziel-Stack einen Traefik-Router für den Host anlegen, möglichst nur für die nötigen Pfade.

## Stolperfallen

- Logins aus dem Internet zeigen in Keycloak die IP von cloudflared, weil Traefik den Forwarded-Headern nicht
  traut. Die echte IP stünde in `CF-Connecting-IP` ([Roadmap](../roadmap.md)).
