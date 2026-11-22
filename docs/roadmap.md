# Roadmap und offene Punkte

Stand: 2026-11-22. Was hier steht, ist **nicht** umgesetzt. Erledigtes wandert in die jeweilige Seite.

## Geplant oder angeboten

| Thema | Worum es geht | Nächster Schritt |
|---|---|---|
| Cluster-Neuaufbau | Pi-Cluster als Lern-Spielwiese neu aufsetzen | Branch `feat/zot-pull-auth` pushen, `zot-pull-password` auf die Control-Freigabe ([Cluster](extern/cluster.md)) |
| Plane-Login über Forgejo | Plane-Passwort durch „Gitea“-OAuth gegen Forgejo ersetzen | Forgejo-OAuth-App anlegen, in God Mode eintragen (`stacks/14-plane/README.md`, Schritt 6) |
| Passkeys neu registrieren | alte Passkeys von `auth.lab` gelten nicht mehr | in der Account-Konsole löschen und neu anlegen; SSO von ArgoCD/Grafana/Longhorn testen, sobald der Cluster läuft |

## Ideen

| Idee | Wann wieder anschauen |
|---|---|
| [RustFS statt Garage](ideas/2026-11-21-rustfs-statt-garage.md) | beim Cluster-Neuaufbau, oder wenn Object Lock/Versionierung oder eine Web-Konsole gebraucht werden |
| Eigenes UniFi-VLAN „Sandbox“ | NIC 2 der Sandbox-VM aus dem Server-VLAN holen, nur Internet erlauben |
| Echte Client-IP bei Tunnel-Logins | Traefik `CF-Connecting-IP` vertrauen, damit Keycloak und Alarme die Angreifer-IP zeigen |
| Source-Routing auf dem NAS | Antworten für `192.168.40.168` über `enp6s0` statt `enp3s0` schicken |
| Restore-Drill | einmal im Quartal Dump und Datei aus B2 zurückholen und das Ergebnis hier festhalten |
| kcc-Update | `webAuthnPolicyPasswordlessResidentKey` statt des veralteten Felds, sobald keycloak-config-cli es kennt |
| Zensical statt MkDocs Material | Material for MkDocs wird ab 2027-05-05 nicht mehr gepflegt; Nachfolger Zensical liest dieselbe `mkdocs.yml` |
| OpenTelemetry-Collector | ist im Observability-Stack vorbereitet, aber aus (Config fehlt) |

## Bewusst nicht

| Thema | Grund |
|---|---|
| Backup für Garage (`data/garage`) | Cluster wird neu aufgebaut, alte Cluster-Backups sind wertlos (Entscheidung 2026-11-21) |
| Backup für Zot | Images sind aus Forgejo neu baubar |
| Cloud-LLM für n8n | alles lokal auf dem Mac Studio |
| Karakeep, Lern-Dienste (Anki, Open WebUI fürs Studium) | kein Bedarf |
