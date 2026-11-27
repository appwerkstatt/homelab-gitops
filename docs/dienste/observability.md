# 20-observability

| | |
|---|---|
| **Zweck** | Metriken, Logs, Dashboards, Alarmierung |
| **Adresse** | `https://grafana.lab.appsfab.org` |
| **Login** | Grafana per Keycloak-OIDC, nur `lab-admins` (= Admin); springt direkt zu Keycloak, lokales Admin-Formular unter `/login?disableAutoLogin` |
| **Daten** | `fast/appdata/{vm,loki,grafana,alertmanager}` |
| **Backup** | Tier 2 |
| **Quelle** | [`stacks/20-observability/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/20-observability) |

## Bausteine

| Dienst | Aufgabe |
|---|---|
| VictoriaMetrics | Metrikspeicher (PromQL-kompatibel), 12 Monate Aufbewahrung |
| node-exporter | Host-Metriken des NAS, dazu Textfile-Metriken der Backup-Skripte |
| cadvisor | Container-Metriken, mit Compose-Projekt als Label (Gruppierung nach Stack); Docker-API nur über `socket-proxy-logs` |
| blackbox-exporter | Health-Probes aller Dienste direkt über deren `edge`-Netze, TLS-Check, Mac-Studio-Probes |
| Loki | Logspeicher auf dem Dateisystem, 31 Tage Aufbewahrung (Compactor) |
| Alloy (+ socket-proxy-logs) | schickt alle Container-Logs des NAS nach Loki |
| Grafana | Dashboards und Explore |
| vmalert | wertet `config/alerts.yml` aus |
| Loki-Ruler | wertet Log-Regeln aus (`config/loki-rules/fake/`) |
| Alertmanager | gruppiert und schickt an Telegram und an den n8n-Alert-Erklärer |

Mehr dazu unter [Monitoring](../monitoring/index.md) und [Alarme](../monitoring/alerts.md).

## Stolperfallen

- Dashboards im Ordner *Homelab* erzeugt `build-dashboards.py`. **Das Skript ändern, nicht das JSON**; die CI
  prüft, dass beide zusammenpassen.
- Grafana liest Provisioning-Dateien nur beim Start. Nach Änderungen an Datasources oder Providern Grafana von
  Hand neu starten (Arcane erkennt reine Dateiänderungen nicht).
- Alertmanager kann keine Env-Variablen; die Config wird beim Start aus `alertmanager.tmpl.yml` gerendert.
