# 30-netboot

| | |
|---|---|
| **Zweck** | Netboot und Provisioning der Raspberry Pis (Custom-App) |
| **Adresse** | Konsole `https://netboot.lab.appsfab.org`; dnsmasq `192.168.80.49`, nginx `192.168.80.47` |
| **Login** | Konsole per Keycloak-OIDC (Client `netboot-console`) |
| **Daten** | `data/provisioning/{control,seed,http,tftpboot,repo}` |
| **Backup** | Tier 3 (tägliche Snapshots) |
| **Quelle** | [`stacks/30-netboot/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/30-netboot) |

## Bausteine

| Dienst | Aufgabe |
|---|---|
| dnsmasq | Proxy-DHCP + TFTP auf eigener macvlan-IP |
| nginx | liefert Golden-Images und Seeds je Host (`/seed/<host>/`) |
| console | Go-Web-App: Inventar, Image-Build, Wipe per SSH, Cluster-Ansicht. Image aus Zot (`127.0.0.1:5000`, Git-SHA-Tag) |

Die Konsole klont ihr Inventar-Repo direkt von Forgejo (`http://forgejo:3000`, Netz `edge-netboot`) und
pusht Änderungen dorthin. Das Feature-Set für den Cluster-Betrieb schalten `CONSOLE_*_ENABLED` frei.

## Stolperfallen

- `data/provisioning/control` enthält Cluster-Secrets (z. B. k3s-Token). Nicht über nginx ausliefern.
- Für den Cluster-Neuaufbau muss dort `zot-pull-password` liegen, sonst können die Nodes nicht aus Zot ziehen
  ([Cluster](../extern/cluster.md)).
