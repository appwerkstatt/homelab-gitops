# n8n-sandbox — VM für die Code-Sandbox des n8n-Assistenten

Der n8n-Assistent (Instance AI) braucht eine Sandbox, in der er Code ausführt. Die selbst gehostete
Variante besteht aus `sandbox-api` und einem **privilegierten Docker-in-Docker-Runner**, laut n8n
„equivalent to root on the host“. Deshalb läuft sie **nicht** auf dem NAS und nicht über Arcane,
sondern in einer eigenen, wegwerfbaren VM ohne Daten. Diese Anleitung ist von Hand abzuarbeiten.

```
NAS (TrueNAS)                                      VM n8n-sandbox (Debian)
 n8n-Container ──NAT──> br88 10.88.88.1 ───── NIC1 10.88.88.2 :8080 sandbox-api ── runner (DinD)
                                                   NIC2 (enp6s0, DHCP) ── Internet (Image-Pulls, Pakete)
```

- **NIC1** hängt an einer reinen Host-Bridge ohne physisches Interface. Darüber erreicht n8n die
  API. Ein direkt an `enp3s0` gehängtes VM-Interface (macvtap) wäre vom NAS selbst aus nicht
  erreichbar (gleiches Hairpin-Problem wie Traefik `.48`).
- **NIC2** hängt an `enp6s0` (VLAN 40 = Server-Netz) und ist nur für den Weg ins Internet. Container
  in der VM dürfen dort **nicht** in private Netze (Firewall in Schritt 5).
  Restrisiko: Bricht Code aus dem Runner bis auf die VM aus, steht die VM selbst im Server-VLAN.
  Sauberer wäre später ein eigenes UniFi-VLAN „Sandbox“ nur mit Internet-Zugang; dann NIC 2 dorthin.
- Die VM hat **keine** Secrets außer den drei Sandbox-Schlüsseln. Kein LLM-Key, keine n8n-Daten.

## 1. Host-Bridge auf dem NAS

TrueNAS → *Network → Interfaces → Add*:

- Type **Bridge**, Name `br88`, **keine** Bridge-Members
- IP-Adresse `10.88.88.1/30`, DHCP aus
- *Save* → *Test Changes* → *Save Changes* (an `enp3s0`/`enp6s0` ändert sich nichts)

## 2. VM anlegen

1. Debian-13-Netinst-ISO auf das NAS laden (z. B. nach `/mnt/fast/iso/`).
2. TrueNAS → *Virtual Machines → Add*:
   - Name `n8nsandbox`, Guest OS Linux, **Start on Boot** an
   - 2 vCPU, **4 GiB** RAM (Minimum laut n8n)
   - Disk: neues Zvol `fast/vm/n8n-sandbox`, 40 GiB
   - NIC 1: Attach to **`br88`**
   - NIC 2 (nach dem Anlegen unter *Devices → Add → NIC*): Attach to **`enp6s0`**
   - CD-ROM: das ISO
3. Debian minimal installieren (nur „SSH server“ + „standard system utilities“), Benutzer `christian`.
   Im Installer NIC 2 per DHCP konfigurieren, NIC 1 erstmal ignorieren.

## 3. Netzwerk in der VM

Interfacenamen prüfen (`ip -br link`): NIC 1 (br88) ist `ens3`, NIC 2 (enp6s0) `ens4` (so bei der ersten Installation 2026-11-22).

`/etc/network/interfaces.d/sandbox-link`:

```
auto ens3
iface ens3 inet static
    address 10.88.88.2/30
    # KEIN gateway: Default-Route bleibt auf NIC 2 (Internet)
```

```bash
sudo ifup ens3
ping -c1 10.88.88.1          # NAS antwortet
```

Vom NAS aus: `ping -c1 10.88.88.2`. SSH von deinem Mac über das NAS als Sprungrechner, in `~/.ssh/config`:

```
Host n8n-sandbox
    HostName 10.88.88.2
    User christian
    ProxyJump truenas.server
```

## 4. Docker installieren

Nach <https://docs.docker.com/engine/install/debian/> (offizielles apt-Repo), dann:

```bash
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin iptables-persistent
sudo usermod -aG docker christian
sudo install -d -o christian /opt/n8n-sandbox
```

## 5. Firewall (DOCKER-USER)

Docker umgeht ufw, deshalb Regeln in der Kette `DOCKER-USER`. Sie greift für alles, was Container
(auch der DinD-Runner und die Sandboxes darin) über die Interfaces der VM schicken oder empfangen.

```bash
# NIC 1 (zum NAS): nur das NAS darf auf 8080, Container dürfen dort nichts Neues aufmachen
sudo iptables -I DOCKER-USER 1 -i ens3 -p tcp ! -s 10.88.88.1 -j DROP
sudo iptables -I DOCKER-USER 2 -o ens3 -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP
# NIC 2 (Internet): von außen nichts rein, nach innen in keine privaten Netze (LAN, Docker-Netze des NAS)
sudo iptables -I DOCKER-USER 3 -i ens4 -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP
sudo iptables -I DOCKER-USER 4 -o ens4 -d 192.168.0.0/16 -j DROP
sudo iptables -I DOCKER-USER 5 -o ens4 -d 10.0.0.0/8 -j DROP
sudo iptables -I DOCKER-USER 6 -o ens4 -d 172.16.0.0/12 -j DROP
sudo iptables -I DOCKER-USER 7 -o ens4 -d 100.64.0.0/10 -j DROP
sudo netfilter-persistent save
sudo iptables -L DOCKER-USER -n -v --line-numbers
```

DNS: Docker übernimmt den Resolver der VM. Steht dort der UniFi-Router (`192.168.40.1`),
würde Regel 4 DNS aus den Containern blockieren. Deshalb in `/etc/docker/daemon.json`
öffentliche Resolver setzen und Docker neu starten:

```json
{ "dns": ["1.1.1.1", "9.9.9.9"] }
```

Zusätzlich für die VM selbst (nicht die Container) SSH nur vom NAS:

```bash
sudo iptables -I INPUT 1 -p tcp --dport 22 ! -s 10.88.88.1 -j DROP
sudo netfilter-persistent save
```

### Gegenstück auf dem NAS (Pflicht)

Die Regeln oben filtern nur Container. Kommt Code bis auf die VM selbst durch, kann er als root in der VM jede
Regel löschen; der Security-Check vom 22.11.2026 fand von der VM aus SSH, SMB, NFS, Web-UI und Arcane des NAS
offen (H5). Deshalb filtert das **NAS** die Bridge `br88`: nur Antworten auf NAS-Verbindungen, nichts Neues.
Skript und Einrichtung: [`docs/nas-firewall/`](../../docs/nas-firewall/README.md).

Noch offen: Über NIC 2 (VLAN 40) erreicht die VM das übrige LAN, z. B. den Mac Studio und die UniFi-Oberfläche.
Das schließt nur eine UniFi-Regel (VM-IP in VLAN 40 nur ins Internet) oder später ein eigenes VLAN „Sandbox“.

## 6. Secrets und Start

Auf dem **Mac** (einmalig das 1Password-Item anlegen, dann rendern und kopieren):

```bash
op item create --vault AppsFab --category login --title homelab-n8n-sandbox \
  "api-key[password]=$(openssl rand -hex 32)" \
  "runner-registration-token[password]=$(openssl rand -hex 32)" \
  "runner-api-key[password]=$(openssl rand -hex 32)"

scp vms/n8n-sandbox/compose.yaml n8n-sandbox:/opt/n8n-sandbox/compose.yaml
op inject -i vms/n8n-sandbox/sandbox.env.tpl -o /tmp/n8n-sandbox.env
scp /tmp/n8n-sandbox.env n8n-sandbox:/opt/n8n-sandbox/.env && rm /tmp/n8n-sandbox.env
```

Auf der **VM**:

```bash
cd /opt/n8n-sandbox && chmod 600 .env
docker compose up -d
docker compose ps                                  # sandbox-certs: exited (0), api: healthy, runner: up
docker compose logs sandbox-api | grep -i runner   # Runner hat sich registriert
```

Vom **NAS**: `curl -s http://10.88.88.2:8080/healthz` → `{"status":"ok"}`.
Gegenprobe vom Mac oder einem anderen Gerät: Port 8080 auf der VM-IP in VLAN 40 muss scheitern.

## 7. n8n anschalten

1. 1Password: im Item `homelab-n8n` das Feld `ai-model-api-key` anlegen (z. B. Anthropic-API-Key,
   passend zu `N8N_INSTANCE_AI_MODEL` in `.env.example`).
2. `.env.example`: `N8N_INSTANCE_AI_SANDBOX_ENABLED=true` (per PR), dann
   `scripts/render-env.sh n8n` → Arcane → n8n → Environment → **Recreate**.
3. In n8n: *Settings → Assistant* einschalten und eine Testfrage stellen, die Code ausführt.

## Betrieb

- **Updates:** `N8N_SANDBOX_VERSION` in `sandbox.env.tpl` hochsetzen (Releases unter
  `ghcr.io/n8n-io/n8n-sandbox-service-api`, nur Stable), neu rendern/kopieren, auf der VM
  `docker compose pull && docker compose up -d`. Renovate deckt das nicht ab (Variable statt Tag).
  Debian selbst: `unattended-upgrades` einschalten.
- **Zertifikate** (mTLS API ↔ Runner) erneuern sich nicht; die ersten (2026-11-22) gelten bis 2029-02-24. Läuft der Runner nicht mehr an:
  `docker compose down && docker volume rm n8n-sandbox_sandbox-tls && docker compose up -d`.
- **Schlüssel rotieren:** in 1Password neu erzeugen, neu rendern/kopieren, `docker compose up -d`,
  danach `render-env.sh n8n` + Recreate in Arcane (der API-Key steht auf beiden Seiten).
- **Kaputt oder verdächtig?** VM wegwerfen und nach dieser Anleitung neu bauen. Es liegen keine
  Daten darauf.
