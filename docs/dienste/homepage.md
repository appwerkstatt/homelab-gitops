# 40-homepage

| | |
|---|---|
| **Zweck** | Start-Dashboard mit Links, Status und Widgets |
| **Adresse** | `https://home.lab.appsfab.org` |
| **Login** | `sso@docker` |
| **Daten** | keine; Config in [`stacks/40-homepage/config/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/40-homepage/config) |
| **Quelle** | [`stacks/40-homepage/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/40-homepage/compose.yaml) |

Neue Kacheln in `config/services.yaml`. Ruft Homepage einen Host serverseitig ab (siteMonitor, Widget), muss
der Host als Alias an Traefik im Netz `edge-home` stehen (`00-traefik`). Widget-Tokens kommen aus
1Password-Item `homelab-homepage` (Grafana-Service-Account, Paperless-Lesekonto).

Das Arcane-Widget wurde entfernt, weil Arcane 3.1.1 die API-Pfade des Widgets nicht hat.
