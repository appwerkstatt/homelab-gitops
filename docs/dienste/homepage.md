# 40-homepage

| | |
|---|---|
| **Zweck** | Startseiten: Familie (nur Links) und Admin (Links, Status, Widgets) |
| **Adresse** | Familie `https://home.lab.appsfab.org`, Admin `https://admin.lab.appsfab.org` |
| **Login** | Familie `sso@docker`, Admin `sso-admin@docker` |
| **Daten** | keine; Config Familie in [`config-family/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/40-homepage/config-family), Admin in [`config/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/40-homepage/config) |
| **Quelle** | [`stacks/40-homepage/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/40-homepage/compose.yaml) |

Homepage kann nicht nach Gruppen filtern, deshalb laufen zwei Instanzen ([Rechtekonzept](../sicherheit/rechtekonzept.md)).
Die Familienseite hat bewusst keine Widgets und keinen Status (keine Tokens, keine NAS-Interna).

Neue Admin-Kacheln in `config/services.yaml`, Familien-Kacheln in `config-family/services.yaml`. Ruft Homepage einen Host serverseitig ab (siteMonitor, Widget), muss
der Host als Alias an Traefik im Netz `edge-home` stehen (`00-traefik`). Widget-Tokens kommen aus
1Password-Item `homelab-homepage` (Grafana-Service-Account, Paperless-Lesekonto).

Das Arcane-Widget wurde entfernt, weil Arcane 3.1.1 die API-Pfade des Widgets nicht hat.
