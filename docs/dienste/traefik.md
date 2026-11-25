# 00-traefik

| | |
|---|---|
| **Zweck** | Reverse Proxy für alle Web-Dienste, TLS-Terminierung, Git-SSH-Passthrough; legt die Netze `edge-<stack>` an |
| **Adresse** | eigene IP `192.168.80.48` (macvlan `vlan80`), Dashboard `https://traefik.lab.appsfab.org` |
| **Login** | Dashboard hinter `sso-admin@docker` (nur `lab-admins`) |
| **Daten** | `fast/appdata/traefik` (nur `acme.json`) |
| **Backup** | Tier 2 (Snapshots + Replika); Zertifikate sind ohnehin neu holbar |
| **Abhängig von** | Cloudflare-API-Token (`CF_DNS_API_TOKEN`) für DNS-01 |
| **Quelle** | [`stacks/00-traefik/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/00-traefik/compose.yaml) |

## Aufbau

- **socket-proxy** (`tecnativa/docker-socket-proxy`): Traefik liest Docker-Labels nur über diesen
  read-only-Proxy (`POST=0`), nicht direkt vom Socket.
- **Entrypoints**: `:80` (leitet auf HTTPS um), `:443` (`websecure`), `:22` (TCP-Passthrough zu Forgejo) und
  `:8443` (`tunnel`). Auf `tunnel` landet nur cloudflared, und dort hören nur die öffentlichen Router
  (`entrypoints=websecure,tunnel`: Forgejo, Keycloak, n8n-Hooks). `*.lab`-Router stehen nur auf `websecure` und
  sind so aus dem Internet unerreichbar, selbst wenn `config.yml` einen Host zu viel durchließe.
- **Zertifikate**: Resolver `le`, Let's Encrypt per DNS-01 über Cloudflare. Wildcard `*.lab.appsfab.org`.
- **Netze**: Traefik hängt an jedem `edge-<stack>` und trägt dort die Aliase `auth.appsfab.org` und
  `auth.lab.appsfab.org` (gegen das [Hairpin-Problem](../architektur/netzwerk.md#traefik-auf-eigener-ip-macvlan)).
  In `edge-plane` zusätzlich `git.appsfab.org`, in `edge-home` die Hosts, die Homepage prüft.

## Betrieb

- **Neuer Stack** ⇒ hier zuerst Netz + Attachment ergänzen, Traefik deployen, dann den Stack
  ([Anleitung](../betrieb/neuer-stack.md)).
- Ein Traefik-Neustart unterbricht kurz alle Dienste; 502/„connection refused“ in den ersten Sekunden ist normal.
- Router eines Dienstes stehen als Labels in dessen `compose.yaml`, nicht hier.

## Stolperfallen

- Der NAS-Host selbst erreicht `.48` nicht (macvlan-Hairpin). Tests vom NAS aus über `127.0.0.1:<port>`
  oder aus einem Container im passenden `edge`-Netz.
- Zwei Container mit identischen Router-Labels (z. B. eine verwaiste Kopie aus einem alten Arcane-Projekt)
  teilt Traefik sich per Round-Robin auf. Symptom: Login klappt jedes zweite Mal. Siehe
  [Fehlersuche](../betrieb/fehlersuche.md#doppelte-container).
