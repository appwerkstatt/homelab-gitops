# Registry Pull-Through Cache — SEPARATE Instanz (registry:2, docker.io) — Design

> Stand: 2026-06-06 · Repo: **homelab-gitops** (TrueNAS, Arcane-driven GitOps)
> Goal: eine **eigenständige** Pull-Through-Cache für **Docker Hub** (docker.io), **getrennt** von
> der privaten Registry (`registryzot`), gegen Docker Hub authentifiziert → höheres Pull-Budget +
> LAN-Speed-Re-Pulls. Engine: **`registry:2` im `proxy`-Modus** (die Referenz-Docker-Hub-Mirror).
> ghcr.io/quay.io/registry.k8s.io = **validierte Folge-Specs**, je eigener Endpoint.

---

## 0. Warum (und warum registry:2 statt Zot-sync)

Die 100-Mbit-Uplink + das **docker.io Anon-Pull-Budget** (100 Pulls / 6h / IP) sind der
wiederkehrende Schmerz: der Mac-Forgejo-Runner ist daran verhungert ("Error obtaining docker
token", [[forgejo-mac-runner-dood]]). docker.io ist **der** Schmerz und der **einzige** Upstream,
den der Docker-Daemon transparent spiegeln kann.

**Pivot dokumentiert (2026-06-06, Spike-getrieben):** Der erste Redesign-Entwurf war *ein*
cache-only Zot mit `extensions.sync` (onDemand) für alle 4 Upstreams, Host-namespaced
(`mirror/ghcr.io/…`). **Der Spike hat das widerlegt:** Zot-onDemand-sync **honoriert kein
Host-Namespacing** — es probiert den *wörtlichen* Repo-Pfad gegen jeden Upstream der Reihe nach
(Logs zeigten Prefix-Doppelung `quay.io/quay.io/quay.io/…` und einen
`registry-1.docker.io/quay.io/…`-Versuch). Funktioniert nur, wenn ein Name auf genau einem
Upstream existiert (docker.io am Root ✓), aber **nicht** sauber pro-Registry steuerbar. Damit
fällt jede *einzelne* Multi-Upstream-Instanz (auch der frühere C-Fallback mit geteiltem Zot). Das
robuste Modell ist **ein Cache-Endpoint pro Upstream** — und das Referenz-Werkzeug dafür ist
**`registry:2` im `proxy`-Modus** (genau ein Upstream pro Instanz, transparenter Root-Pfad,
`proxy.username/password` für die Hub-Auth). **Spike bestätigt** (registry:2 v2.8.3, NAS, echtes
Token): Cold-Pull über den Proxy ✓, zweiter Pull aus dem lokalen Cache (~5 ms, Scheduler-TTL
168h) ✓, **keine** Auth-Fehler. Harbor (one-instance, proxy-cache-Projekte) wurde erwogen, aber
**verworfen**: ~1–3 GB RAM **und** als path-namespaced KEIN transparenter docker.io-Daemon-Mirror.

## 1. Scope

**In scope (diese Spec — homelab-gitops):**
- Neuer Stack `stacks/23-registry-cache/` (nur `compose.yaml`, kein Config-File) als **eigene
  Arcane-Gitsync-App**: ein `registry:2`-Service im `proxy`-Modus für **docker.io**.
- Auth gegen Docker Hub via **Arcane-ENV** (`REGISTRY_PROXY_USERNAME`/`PASSWORD`) — Repo-Secret-Modell.
- Eigenes Datenverzeichnis `/mnt/data/registry-cache`, Loopback `127.0.0.1:5001`, Traefik-Host
  `mirror.lab.appsfab.org`.

**Out of scope (eigene Folge-Specs):**
- **ghcr.io / quay.io** — je ein weiterer `registry:2`-proxy-Service (eigener Port/Host); normale
  Registries, proxy funktioniert. Lower priority (kein vergleichbares Ratelimit).
- **registry.k8s.io** — **eigener Spike nötig**: redirect-lastig (Blobs von umgeleiteten CDNs),
  notorisch zickig für Pull-Through-Caches; ggf. nicht sauber cachebar.
- **Teil 2 (cluster-Repo):** containerd `registries.yaml` — pro Upstream ein Mirror-Endpoint.
- **Teil 3 (Host-Config):** Docker-Clients (Mac-Runner + NAS-Host) `daemon.json` `registry-mirrors`
  (docker.io → `mirror.lab.appsfab.org`).

## 2. Architektur / Datenfluss

```
  Docker-Daemon-Client (Mac-Runner, NAS-Host)          k3s containerd (Teil 2)
      │ registry-mirrors: https://mirror.lab.appsfab.org    │ registries.yaml: docker.io ->
      │ → Root-Pfad /v2/library/nginx/…  (transparent!)     │   mirror.lab.appsfab.org
      ▼                                                      ▼
      └──────────────►  mirror.lab.appsfab.org  ◄────────────┘
                        (= registry:2 proxy, docker.io,
                         anonymous read, 127.0.0.1:5001 lokal)
                              │
                ┌─────────────┴──── Cache-Hit? ── ja ──► aus /mnt/data/registry-cache (LAN, ~ms)
                │
                └─ nein ──► proxy pullt EINMAL von registry-1.docker.io (Hub-authentifiziert),
                            cached lokal (Scheduler-TTL), serviert danach lokal
```

- **registry:2 `proxy`-Modus** serviert docker.io am **Root** (`/v2/library/nginx`) → der
  Docker-Daemon-`registry-mirrors`-Pfad ist **transparent** (kein Ref-Rewrite in CI nötig).
- **Eigene Identität:** neue Arcane-App, eigener Container/Port/Datenpfad → `registryzot`
  unberührt (Regression-Sicherheit).
- **Netz `edge`**, Traefik-Host via Wildcard-Cert `le` (`*.lab.appsfab.org` deckt `mirror` ab).
- **Loopback `127.0.0.1:5001`** (5000 = `registryzot`) für NAS-lokal + NAS-Host-Daemon.

## 3. Komponenten / Änderungen

### 3.1 `stacks/23-registry-cache/compose.yaml`

```yaml
# 23-registry-cache — Pull-Through-Cache fuer Docker Hub (docker.io). registry:2 im proxy-Modus.
# SEPARAT von der privaten Registry (registryzot) — niemals mischen. Auth via Arcane-ENV
# (DOCKERHUB_USERNAME/DOCKERHUB_TOKEN), NICHT in Git. Arcane-App ebenfalls "registry-cache" benennen
# (Slug ueberschreibt name:, s. README Konventionen). Erweiterbar: ghcr/quay/k8s spaeter als eigene
# registry:2-Services + Traefik-Hosts (Folge-Specs).
name: registry-cache

services:
  dockerhub:
    image: registry:2.8.3                      # Distribution registry, proxy/pull-through
    environment:
      REGISTRY_PROXY_REMOTEURL: https://registry-1.docker.io
      REGISTRY_PROXY_USERNAME: ${DOCKERHUB_USERNAME}   # aus Arcane-ENV
      REGISTRY_PROXY_PASSWORD: ${DOCKERHUB_TOKEN}      # Docker-Hub Access-Token, aus Arcane-ENV
      REGISTRY_PROXY_TTL: 168h                         # Cache-Frische + Purge-Fenster (7 Tage)
      REGISTRY_STORAGE_DELETE_ENABLED: "true"          # Proxy-Scheduler darf abgelaufene Blobs purgen
    ports:
      - "127.0.0.1:5001:5000"                  # NAS-lokal + Docker-Daemon-Mirror; 5000 ist registryzot
    volumes:
      - /mnt/data/registry-cache:/var/lib/registry     # Cache-Blobs -> data-Pool
    labels:
      - traefik.enable=true
      - traefik.http.routers.regcache.rule=Host(`mirror.${LAB_DOMAIN}`)
      - traefik.http.routers.regcache.entrypoints=websecure
      - traefik.http.routers.regcache.tls.certresolver=le
      - traefik.http.services.regcache.loadbalancer.server.port=5000
    networks: [edge]
    mem_limit: 256m
    restart: unless-stopped

networks:
  edge:
    external: true
```

### 3.2 Secrets — Arcane-ENV (kein File)

registry:2 liest die Upstream-Credentials aus der **Container-ENV** → passt exakt zum
Repo-Secret-Modell ("Variablen in der Arcane-Env pro Stack", [[nas-homelab-gitops]]).
- **Operator setzt in der Arcane-`registry-cache`-App-Env:** `DOCKERHUB_USERNAME` +
  `DOCKERHUB_TOKEN` (freier Docker-Hub-Account, Access-Token Public-Read; in 1Password ablegen).
- Die in Task 1 angelegte `/mnt/fast/appdata/registry-cache/sync-credentials.json` (Zot-Format)
  ist damit **obsolet** und kann entfernt werden.
- **anonymous read** für LAN-Clients: registry:2 proxy ist per Default ohne Client-Auth → Clients
  pullen ohne Credentials (die Hub-Creds nutzt nur der Proxy upstream).

### 3.3 Retention / Cache-Größe

**Kein separates Retention-Regelwerk** (anders als Zot): registry:2 `proxy`-Modus hat einen
**eingebauten TTL-Scheduler** — gecachte Manifeste/Blobs werden nach `REGISTRY_PROXY_TTL`
(Startwert **168h = 7 Tage**) revalidiert bzw. gepurgt; `REGISTRY_STORAGE_DELETE_ENABLED=true`
erlaubt das Löschen. Damit ist `/mnt/data/registry-cache` durch das TTL-Fenster begrenzt.
TTL-Wert tunebar (längere TTL = höhere Hit-Rate, mehr Disk).

## 4. Verifikation (Definition of Done)

1. **Container live:** `registry-cache-dockerhub-1` Up; `/v2/` (loopback 5001 **und**
   `mirror.lab.appsfab.org`) → `200`. Live-Projektname == `name:` (keine Drift).
2. **Cold-Pull über den Proxy:** `docker pull 127.0.0.1:5001/library/hello-world` → Erfolg.
3. **Cache-Hit:** zweites Pull aus dem lokalen Cache (Log: schnelle 200er, kein erneuter
   Upstream-Roundtrip; Scheduler-Entry mit TTL).
4. **Hub-Auth aktiv:** keine 401/unauthorized im Log (authentifiziertes Budget, nicht anon).
5. **Regression:** private `registryzot` (Port 5000) + `garages3` unverändert pull-/pushbar.

## 5. Risiken / offene Punkte

- **Token-Rotation:** Docker-Hub-Access-Token läuft ggf. ab → 1Password; Rotation = Arcane-ENV
  aktualisieren + Container-Recreate (Arcane recreate'd ENV-Änderungen via compose-up).
- **Cache-Größe:** durch TTL begrenzt; bei Bedarf TTL senken oder periodisch `registry
  garbage-collect` (Distribution-GC) als Folge-Maßnahme.
- **registry-mirrors-Reichweite:** Docker-Daemon spiegelt **nur** docker.io — by-design; ghcr/quay/k8s
  nur über containerd (Teil 2) bzw. eigene Proxies (Folge-Specs).
- **Arcane-Projektname:** App-Slug == `name: registry-cache`, sonst Drift wie garage→garages3
  (harmlos, aber von Anfang an vermieden).

## 6. Folge-Specs (nicht hier umgesetzt)

- **ghcr.io / quay.io Proxies:** je ein `registry:2`-Service (eigener Port + Traefik-Host).
- **registry.k8s.io:** eigener Spike (redirect-lastig) → ggf. eigener Proxy oder Verzicht.
- **Teil 2:** cluster-Repo `registries.yaml` (containerd, docker.io → `mirror.lab.appsfab.org`; weitere Upstreams sobald deren Proxies stehen).
- **Teil 3:** Docker-Clients (Mac-Runner + NAS-Host) `daemon.json` `registry-mirrors` (docker.io).
