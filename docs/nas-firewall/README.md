# NAS-Firewall

TrueNAS hat keine eigene Host-Firewall. Ein Skript setzt deshalb ein paar `iptables`-Regeln, die zwei
Befunde aus dem Security-Check vom 22.11.2026 schließen:

| Regel | Schützt vor | Befund |
|---|---|---|
| `br88`: nur Antworten erlaubt, keine neuen Verbindungen (INPUT + FORWARD) | Ausbruch aus der [Sandbox-VM](https://github.com/appwerkstatt/homelab-gitops/blob/main/vms/n8n-sandbox/README.md) bis ans NAS (SSH, SMB, NFS, Web-UI, Arcane) | H5 |
| Arcane `:30258` nur aus `192.168.10.0/24` (Kette `DOCKER-USER`) | Docker-Steuerung (= Root) aus Cluster-, Server- oder Gast-Netz | H4 |
| VNC `:5900` (VM-Konsole) nur aus `192.168.10.0/24` | Fremdzugriff auf die VM-Konsole | H4 |
| IPv6 auf `:30258` und `:5900` nur lokal | dieselben Dienste über `[::]` | H4 |

n8n erreicht die Sandbox weiter (`NAS → 10.88.88.2:8080`), die Antworten laufen über `ESTABLISHED`.
TrueNAS-UI und SSH bleiben offen, weil der Cluster (democratic-csi) die TrueNAS-API aus VLAN 80 braucht.
Dort schützen HTTPS-Umleitung, 2FA und SSH nur mit Key (TrueNAS-Einstellungen).

Quelle: [`nas-firewall.sh`](https://github.com/appwerkstatt/homelab-gitops/blob/main/docs/nas-firewall/nas-firewall.sh).
Das Skript ist idempotent und läuft beim Booten (Init-Script) und alle 10 Minuten (Cron), damit die Regeln
nach einem Docker- oder Middleware-Neustart wieder da sind.

## Installation

Auf dem **Mac** (im Repo):

```bash
scp docs/nas-firewall/nas-firewall.sh truenas.server:/tmp/
```

In der **TrueNAS-Web-Shell** (zsh: Befehle ohne Kommentare einfügen):

```bash
sudo install -d -m 700 /mnt/fast/appdata/nas-firewall
sudo install -m 700 /tmp/nas-firewall.sh /mnt/fast/appdata/nas-firewall/nas-firewall.sh
sudo iptables -D INPUT -i br88 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -D INPUT -i br88 -j DROP
sudo iptables -D FORWARD -i br88 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -D FORWARD -i br88 -j DROP
sudo /mnt/fast/appdata/nas-firewall/nas-firewall.sh
sudo iptables -S | grep nas-firewall
```

Die vier `-D`-Zeilen entfernen die Test-Regeln von Hand (ohne Kommentar). Gibt es sie nicht mehr
(Neustart), melden sie nur einen Fehler. Dann dauerhaft einhängen:

```bash
sudo midclt call initshutdownscript.create '{"type": "SCRIPT", "script": "/mnt/fast/appdata/nas-firewall/nas-firewall.sh", "when": "POSTINIT", "enabled": true, "timeout": 30, "comment": "nas-firewall (homelab-gitops docs/nas-firewall)"}'
sudo midclt call cronjob.create '{"user": "root", "command": "/mnt/fast/appdata/nas-firewall/nas-firewall.sh", "description": "nas-firewall (homelab-gitops docs/nas-firewall)", "schedule": {"minute": "*/10", "hour": "*", "dom": "*", "month": "*", "dow": "*"}, "stdout": true, "stderr": true, "enabled": true}'
```

## Prüfen

- NAS: `curl -s http://10.88.88.2:8080/healthz` liefert `{"status":"ok"}`.
- Sandbox-VM (`ssh n8n-sandbox`): die Port-Schleife aus dem Security-Check zeigt für alle `10.88.88.1`-Ziele „zu“.
- Mac (VLAN 10): Arcane unter `http://truenas.server:30258` geht weiter.
- Ein Gerät aus VLAN 80 oder 40: `curl -m 5 http://192.168.80.50:30258` läuft in einen Timeout.
- Nach einem Neustart des NAS: `sudo iptables -S | grep -c nas-firewall` ist größer als 0.

## Ändern und Rückbau

- **Anderes Management-Netz:** `MGMT_CIDRS` oben im Skript (genau ein Netz), neu kopieren und ausführen.
  Die alte Regel vorher löschen, sonst bleiben beide stehen (`iptables -S | grep nas-firewall` zeigt sie).
- **Komplett aus:** Init-Script und Cronjob in TrueNAS (*System → Advanced*) löschen und neu starten,
  oder sofort jede Zeile aus `sudo iptables -S | grep nas-firewall` mit `-D` statt `-A` erneut ausführen.
- **Ausgesperrt aus Arcane:** Web-Shell der TrueNAS-UI geht weiter; dort die Arcane-Regel löschen:
  `sudo iptables -D DOCKER-USER -s` … (Zeile aus `iptables -S DOCKER-USER` kopieren, `-A` durch `-D` ersetzen).

Offen bleibt der Weg der Sandbox-VM über ihre zweite Netzwerkkarte in VLAN 40 (z. B. zum Mac Studio und zur
UniFi-Oberfläche). Den schließt nur eine UniFi-Regel: die VM-IP in VLAN 40 darf nur ins Internet.
