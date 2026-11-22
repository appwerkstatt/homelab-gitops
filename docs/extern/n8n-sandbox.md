# n8n-Sandbox-VM

Der n8n-Assistent führt Code in einer Sandbox aus. Die selbst gehostete Variante braucht einen **privilegierten
Docker-in-Docker-Runner**, laut n8n „equivalent to root on the host“. Deshalb läuft sie nicht auf dem NAS, sondern in
einer eigenen, wegwerfbaren VM ohne Daten.

```
NAS (TrueNAS)                                      VM n8n-sandbox (Debian 13)
 n8n-Container ──NAT──> br88 10.88.88.1 ───── ens3 10.88.88.2 :8080 sandbox-api ── runner (DinD)
                                                   ens4 (enp6s0, VLAN 40, DHCP) ── Internet
```

| | |
|---|---|
| **VM** | TrueNAS-VM `n8nsandbox`, 2 vCPU, 4 GiB RAM, Zvol `fast/vm/n8n-sandbox` (40 GiB) |
| **Netz** | `ens3` an der Host-Bridge `br88` (nur NAS ↔ VM), `ens4` im Server-VLAN nur fürs Internet; Firewall sperrt private Netze |
| **API** | `sandbox-api` auf `:8080`, Zugriff per API-Key (1Password `homelab-n8n-sandbox`), mTLS-Zertifikate bis 2029-02-24 |
| **Zugang** | vom Mac `ssh n8n-sandbox` (ProxyJump über das NAS), sonst TrueNAS-Shell → `ssh christian@10.88.88.2` |
| **Backup** | keins, wegwerfbar |

Einrichtung Schritt für Schritt: [`vms/n8n-sandbox/README.md`](https://github.com/appwerkstatt/homelab-gitops/blob/main/vms/n8n-sandbox/README.md).

!!! warning "Restrisiko"
    Bricht Code bis auf die VM aus, steht sie im Server-VLAN. Sauberer wäre ein eigenes UniFi-VLAN „Sandbox“ nur mit
    Internet ([Roadmap](../roadmap.md)). Die VNC-Konsole von TrueNAS verschluckt `-` und `/`; besser SSH nehmen.
