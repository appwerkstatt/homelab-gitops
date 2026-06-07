# Registry-Cache Teil 3 — Docker-Daemon registry-mirrors — Design

> Stand: 2026-06-06 · Repo: **homelab-gitops** (Doku der Host-Config; die Änderungen selbst
> liegen auf den Hosts, NICHT als Arcane-Stack).
> Goal: die beiden **Docker-Daemons** (Mac-Forgejo-Runner + TrueNAS-Host) auf die docker.io-
> Pull-Through-Cache (`23-registry-cache`, registry:2) zeigen lassen — damit docker.io-Pulls über
> die LAN-Cache statt über die 100-Mbit-Leitung + Anon-Ratelimit laufen.

---

## 0. Kontext

Die Cache selbst läuft (Teil 1, [[nas-registry-cache]]): `registry:2`-Proxy für docker.io,
Container `registry-cache-dockerhub-1`, erreichbar als **`https://mirror.lab.appsfab.org`** (Traefik,
LAN) **und** **`http://127.0.0.1:5001`** (NAS-lokal). **Teil 3** verdrahtet die Docker-**Daemons**
als Clients. **Teil 2** (k3s containerd via `registries.yaml`) bleibt separat (cluster-Repo).

**Warum Daemon-Mirror (nicht pro-Build):** `registry-mirrors` ist eine **Daemon-Einstellung** —
gilt transparent für ALLE docker.io-Pulls dieses Daemons, ohne Image-Refs umzuschreiben. Docker
spiegelt nur **docker.io** (Daemon-Limit) — genau der Ratelimit-Schmerz. **Fallback eingebaut:**
ist der Mirror nicht erreichbar, zieht Docker direkt von docker.io → kann nie Pulls *brechen*,
nur beschleunigen.

## 1. Scope

- **Mac-Forgejo-Runner** (OrbStack-Docker) — DER Schmerzpunkt ([[forgejo-mac-runner-dood]]); der
  Runner baut/pullt via DooD über den OrbStack-Daemon.
- **TrueNAS-Host-Docker** — die eigenen Stack-Image-Pulls (Arcane-Deploys) über die Cache.
- **docker.io only** (Daemon-Limit; ghcr/quay/k8s gehen über containerd/Teil 2 bzw. eigene Proxies).

Out of scope: Teil 2 (cluster containerd), weitere Upstream-Proxies (eigene Specs).

## 2. Architektur — zwei Daemons, je passender Endpoint + Mechanismus

| Daemon | Mirror-Endpoint | Warum | Mechanismus |
|--------|-----------------|-------|-------------|
| Mac (OrbStack) | `https://mirror.lab.appsfab.org` | LAN, Traefik, gültiges Wildcard-Cert (verifiziert: `/v2/`=200) | `~/.orbstack/config/docker.json` + Engine-Restart |
| TrueNAS-Host | `http://127.0.0.1:5001` | Host erreicht Traefik `.48` **NICHT** (Hairpin, verifiziert: 443 connect fail; loopback 5001 = 200) | **midclt** `docker.update` (supported, persistent) |

**Kein daemon.json-Handedit auf dem NAS:** `/etc/docker/daemon.json` ist **middleware-generiert**
(enthält `data-root /mnt/.ix-apps/docker`, leere `registry-mirrors`/`insecure-registries`). Ein
Handedit würde beim nächsten Apps-Service-Start/Reboot/Update **überschrieben**. Die Middleware
hat dafür echte Felder: `docker.config` zeigt **`secure_registry_mirrors`** / **`insecure_registry_mirrors`**
→ via `docker.update` gesetzt, persistiert es (Middleware regeneriert daemon.json daraus).

## 3. Komponenten / Änderungen

### 3.1 Mac-Runner (OrbStack)

`~/.orbstack/config/docker.json` — bestehenden `dns`-Key behalten, `registry-mirrors` ergänzen:
```json
{
  "dns": ["192.168.10.1"],
  "registry-mirrors": ["https://mirror.lab.appsfab.org"]
}
```
Danach OrbStack-Docker-Engine neu starten (`orb restart docker` bzw. OrbStack-Neustart) → bounced
**nur** den Mac-Docker (inkl. Forgejo-Runner-Container, der via `--restart unless-stopped`
wiederkommt).

### 3.2 TrueNAS-Host (Middleware)

`http://127.0.0.1:5001` ist HTTP-Loopback → gehört in **`insecure_registry_mirrors`** (Docker
behandelt 127.0.0.1 ohnehin als insecure):
```bash
sudo -n midclt call docker.update '{"insecure_registry_mirrors": ["http://127.0.0.1:5001"]}'
```
(Exaktes Format — URL vs. `host:port` — im Plan gegen die Middleware verifizieren.) Die Middleware
schreibt den Wert nach `/etc/docker/daemon.json` (`registry-mirrors` + ggf. `insecure-registries`)
und lädt/restartet den Docker-Daemon.

**HAZARD — Daemon-Bounce:** `registry-mirrors` ist in dockerd's **live-reloadbarer** Config-Menge
(SIGHUP-Reload reicht theoretisch, ohne Container-Neustart). Ob die TrueNAS-Middleware **reload**
oder **full restart** macht, ist offen → **im Plan zuerst klären** (z.B. `docker events`/Uptime
beobachten). Worst case: ein Docker-Restart **bounced ALLE NAS-Apps** (Keycloak/Paperless/Garage/
Cache/…) kurz → **in einem ruhigen Fenster** ausführen.

## 4. Verifikation (Definition of Done)

Pro Daemon:
1. `docker info` → unter **Registry Mirrors** steht der erwartete Endpoint.
2. **Cache-Routing live:** ein noch-nicht-gecachtes docker.io-Image pullen → Pull erscheint im
   **`registry-cache-dockerhub-1`-Log** (beweist: lief über die Cache, nicht direkt docker.io).
   - Mac: `docker pull <neues image>` → NAS-Cache-Log zeigt den Pull.
   - NAS-Host: `sudo -n docker pull <neues image>` → Cache-Log zeigt den Pull.
3. **Fallback-Sanity:** Pull funktioniert weiterhin (kein Bruch), auch wenn die Cache mal weg wäre.
4. **NAS-Apps gesund** nach dem midclt-Apply (alle Container Up; speziell Keycloak/Paperless/Cache).

## 5. Risiken / offene Punkte

- **NAS-Daemon-Bounce** (3.2) → reload-vs-restart im Plan klären; ruhiges Fenster.
- **Mac off-LAN:** Mirror unerreichbar → pro Pull ein kurzer Timeout vor dem Fallback auf docker.io.
  Für einen LAN-residenten Runner ok; bei Roaming ggf. Mirror temporär entfernen.
- **Selbstreferenz NAS:** der Host spiegelt auf die Cache, die selbst auf dem Host läuft. Beim
  `registry:2`-Image-Pull während eines Cache-Recreate → Fallback auf docker.io greift. Kein Deadlock.
- **Host-Config außerhalb Git:** beide Änderungen sind Host-State (kein Arcane-Stack) → in
  [[nas-registry-cache]] + diesem Spec dokumentiert, damit reproduzierbar.

## 6. Bezug

Schließt die Cache-Decomposition für die **Docker-Daemons** ab. Offen bleiben: **Teil 2**
(cluster `registries.yaml`, containerd — alle 4 Upstreams, cluster-Repo) sowie ghcr/quay-Proxies +
registry.k8s.io-Spike (eigene Specs).
