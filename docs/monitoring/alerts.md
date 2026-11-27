# Alarme

Alle Alarme gehen über **Alertmanager an Telegram**. Für `warning` und `critical` ruft Alertmanager zusätzlich
den n8n-Workflow **Alert-Erklärer** auf: Er holt die passenden Logs aus Loki, lässt LM Studio auf dem Mac Studio
eine Erklärung schreiben und schickt sie als zweite Nachricht (🧠). Pro Alarm höchstens alle 12 h.

Regeln: [`config/alerts.yml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/20-observability/config/alerts.yml) (vmalert) und
[`config/loki-rules/fake/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/20-observability/config/loki-rules/fake) (Loki-Ruler: `keycloak.yml`, `n8n.yml`).
Gruppierung nach `alertname` + `instance`, Wiederholung alle 12 h.

## Übersicht und erste Schritte

| Alarm | Schwere | Bedeutung | Erste Schritte |
|---|---|---|---|
| `ServiceDown` | critical | Healthcheck eines Dienstes seit 5 min rot | Container in Arcane prüfen, Logs in Grafana *Homelab · Logs* |
| `TargetDown` | warning | Scrape-Ziel seit 5 min weg | Exporter-Container läuft? Netz `obs` / `edge-*`? |
| `LlmHostDown` | warning | Ollama oder LM Studio seit 10 min weg | Mac Studio an? Nach Neustart mit FileVault wartet er aufs Passwort ([Runbook](../mac-studio-llm.md)) |
| `CertExpiringSoon` | warning | TLS-Zertifikat läuft bald ab | Traefik-Log nach `acme` durchsuchen, Cloudflare-Token gültig? |
| `CertProbeFailing` | warning | TLS-Check seit 15 min fehlerhaft | Traefik läuft? Zertifikat in `acme.json`? |
| `ZpoolUnhealthy` | critical | ZFS-Pool nicht `ONLINE` | TrueNAS → Storage, `zpool status -v`, Disk tauschen |
| `PoolSpaceLow` / `PoolSpaceCritical` | warning / critical | Pool wird voll | großen Verbraucher finden (`zfs list -o space`), alte Snapshots |
| `HostMemoryLow` | warning | weniger als 10 % RAM frei | Dashboard *Container & Stacks*, wer frisst RAM? |
| `ContainerRestartLoop` | warning | Container startet ständig neu | Logs des Containers, meist Konfig oder fehlende Env |
| `ContainerOOMKilled` | warning | Container hat `mem_limit` gesprengt | Limit im `compose.yaml` anheben, wenn der Bedarf echt ist |
| `OffsiteBackupStale` | critical | seit 36 h kein erfolgreiches Offsite-Backup | Cron-Log in TrueNAS, `backup-offsite.sh` von Hand starten |
| `OffsiteBackupStatusMissing` | warning | Backup-Skript liefert keinen Status | Skript auf dem NAS aktuell? ([Backup](../backup/index.md#anderungen-ausrollen)) |
| `ReplicaBackupStale` | warning | lokale Replika zu alt | TrueNAS → Data Protection → Replication, Pool `backup` entsperrt? |
| `AlertmanagerNotificationsFailing` | warning | Telegram nicht erreichbar | Bot-Token und Chat-ID in 1Password `homelab-alerting` |
| `KeycloakLoginFailures` | warning | gehäufte Fehl-Logins in 15 min | in Loki bei `compose_service="keycloak"` nach `LOGIN_ERROR` suchen |
| `KeycloakUserLockedOut` | warning | Konto per Brute-Force-Schutz gesperrt (15 min) | Warst du es nicht, läuft ein Angriff. Quelle in Loki prüfen |
| `N8nSsoHookDisabled` | warning | n8n-Keycloak-Login nach Start abgeschaltet, nur noch n8n-Passwort | Grund in Loki (`compose_service="n8n"`, `keycloak-sso`), [n8n](../dienste/n8n.md#keycloak-login) |

!!! note "Quell-IP bei Internet-Logins"
    Logins über den Tunnel zeigen die IP von cloudflared, nicht die des Angreifers (siehe [Roadmap](../roadmap.md)).

## Stummschalten

Alertmanager-UI ist nicht veröffentlicht. Für eine Wartung vom NAS aus:

```bash
docker exec "$(docker ps -qf name=alertmanager)" amtool --alertmanager.url=http://localhost:9093 \
  silence add alertname=ServiceDown --duration=2h --comment="Wartung"
```

## Neue Regel

1. Regel in `config/alerts.yml` (Metrik) oder `config/loki-rules/fake/` (Log) ergänzen, mit `severity` und
   deutscher `summary`.
2. PR: die CI prüft die Regeln mit `vmalert -dryRun`.
3. Diese Tabelle ergänzen.
