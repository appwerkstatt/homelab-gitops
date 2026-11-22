# Kubernetes-Cluster

Ein Kubernetes-Cluster aus Raspberry Pis (bisher k3s, für den Neuaufbau ist Talos im Gespräch), gedacht als **Spielwiese zum Lernen, nicht als Produktion**. Er wird
seit 2026-11-21 neu aufgebaut und läuft derzeit nicht. Sein Code liegt im Forgejo-Repo `christian/cluster`.

| Nodes | Adresse |
|---|---|
| 4 × Raspberry Pi 4 | `192.168.80.41–.44` |
| 4 × Raspberry Pi 5 | `192.168.80.51–.54` |

## Was der Cluster vom NAS nutzt

| Dienst | Wofür |
|---|---|
| Keycloak (`auth.appsfab.org`) | SSO für ArgoCD, Grafana, Longhorn, Demo-Apps |
| Zot (`registry.lab`) | eigene Images, Login mit Robot `pull` |
| Registry-Cache (`mirror.lab`) | Docker-Hub-Images |
| Garage (`s3.lab`) | etcd- und Longhorn-Backups, Velero |
| Netboot (`netboot.lab`) | Provisioning der Pis, Inventar, Wipe |
| NFS | Node-Exporte, auf die Node-IPs beschränkt |

## Vor dem Neuaufbau offen

- Branch `feat/zot-pull-auth` im Cluster-Repo (lokal auf dem Mac, noch nicht gepusht): `registries.yaml` mit
  Auth für den Zot-Benutzer `pull`.
- `zot-pull-password` muss auf die NAS-Freigabe `/mnt/data/provisioning/control`.

Ohne beides können die Nodes nicht aus Zot ziehen.

## Talos auf dem Pi 5

Das Image-Factory-Profil `rpi_5` funktioniert ab Talos 1.12.4. Vorher das EEPROM aktualisieren und zuerst von SD
booten; NVMe-Boot ist noch wackelig.
