# Registry Pull-Through Cache — Redesign als SEPARATE Instanz — Design

> Stand: 2026-06-06 · Repo: **homelab-gitops** (TrueNAS, Arcane-driven GitOps)
> Goal: eine **eigenständige** Pull-Through-Cache für die vier öffentlichen Registries
> (docker.io, ghcr.io, quay.io, registry.k8s.io), **getrennt** von der privaten Registry
> (`registryzot`). Erstes Pull zieht einmal extern + cached auf dem NAS; jedes weitere Pull
> kommt mit LAN-Speed. Authentifiziert gegen Docker Hub → höheres Pull-Budget.

---

## 0. Warum (und warum NEU, nicht der alte Ansatz)

Die 100-Mbit-Uplink + das **docker.io Anon-Pull-Budget** (100 Pulls / 6h / IP) sind ein
wiederkehrender Schmerz: der Mac-Forgejo-Runner ist daran schon verhungert ("Error obtaining
docker token", [[forgejo-mac-runner-dood]]), und der k3s-Cluster zieht bei jedem Rollout/Reboot
dieselben Public-Images neu.

**Der erste Versuch (2026-06-05, PR #26/#27) wurde revertiert.** Er hatte die `sync`-Extension
in den **bestehenden, load-bearing** Zot (`registryzot`, serviert `registry.lab.appsfab.org` +
netboot-console + `lab-status`) eingebaut. Probleme: (a) **keine Docker-Hub-Credentials** → als
Cache funktionslos; (b) `prefix: "**"` über die Private-Repos → bei jedem Private-Pull ein
nutzloser Upstream-Sync-Versuch (Log-Noise + Latenz); (c) Retention musste die Private-Repos
mühsam per Protect-Policy ausnehmen. **Lehre: die Cache gehört in eine SEPARATE Instanz, nie
in die private Registry gemischt.** Diese Spec setzt genau das um.

**Engine: ein einzelner cache-only Zot.** Dieselbe Engine, die wir ohnehin betreiben (Zot
v2.1.x), aber als **neue, isolierte** App mit eigenem Datenverzeichnis. Multi-Upstream via
`extensions.sync` (onDemand). Kein Harbor (Overkill: ~2–3 GB RAM, Multi-Container — für reines
Caching unnötig).

## 1. Scope

Das Gesamtfeature zerfällt weiterhin in **drei** Teile. **Diese Spec = Teil 1: die Cache-Instanz.**

**In scope (Teil 1 — homelab-gitops):**
- Neuer Stack `stacks/23-registry-cache/` (compose.yaml + config/zot.json) als **eigene
  Arcane-Gitsync-App**, eigenes Datenverzeichnis, eigener Loopback-Port, eigener Traefik-Host.
- `extensions.sync` (onDemand) für docker.io (Root) + ghcr.io / quay.io / registry.k8s.io
  (Host-namespaced), authentifiziert gegen Docker Hub.
- `storage.retention` + GC, damit `/mnt/data/registry-cache` den data-Pool nicht vollläuft.

**Out of scope (eigene Folge-Specs, Teil 2/3):**
- **Teil 2 (cluster-Repo):** `/etc/rancher/k3s/registries.yaml` — containerd-Mirrors auf den
  k3s-Nodes (alle vier Upstreams, Host-namespaced gegen diese Cache).
- **Teil 3 (Host-Config):** Docker-Clients (Mac-Forgejo-Runner + NAS-Host-Daemon) —
  `registry-mirrors` in `daemon.json`, **nur docker.io** (Docker-Daemon-Limit; ghcr/quay/k8s
  gehen dort nicht transparent). docker.io ist genau der Ratelimit-Schmerz → deckt den realen Fall ab.

## 2. Architektur / Platzierung

```
  Docker-Daemon-Client (Mac-Runner, NAS-Host)        k3s containerd (alle 4 Upstreams)
        │ registry-mirrors: nur docker.io                  │ registries.yaml: pro Upstream ein
        │ → Root-Pfad  /v2/library/nginx/...               │   Mirror-Endpoint, Host im Pfad
        ▼                                                   ▼  /v2/ghcr.io/owner/img/...
        └──────────────►  mirror.lab.appsfab.org  ◄─────────┘
                          (= cache-only Zot, anonymous read,
                           127.0.0.1:5001 lokal)
                                │
                  ┌─────────────┴───────────── Cache-Hit? ── ja ──► aus /mnt/data/registry-cache (LAN)
                  │
                  └─ nein ──► sync onDemand pullt EINMAL vom passenden Upstream
                              (Docker Hub authentifiziert), cached lokal, serviert danach lokal
```

- **Neuer Stack / eigene Arcane-App.** Damit das Compose-Projekt eine eigene Identität hat,
  **getrennt** von `registryzot`. Wegen [[nas-homelab-gitops]] (Arcane setzt den Projektnamen per
  `-p <slug>`, überschreibt `name:`): compose `name: registry-cache` setzen **und die
  Arcane-Gitsync-App gleich benennen** (Slug `registry-cache`), damit Live-Projekt == `name:`.
- **Netz `edge`** (bridge), wie die übrigen web-exponierten Stacks.
- **Traefik-Host `mirror.lab.appsfab.org`** (Split-Horizon → `192.168.80.50`), TLS über den
  bestehenden Wildcard-Resolver `le` (`*.lab.appsfab.org` deckt den Host ab — kein neues Zert).
- **Loopback `127.0.0.1:5001`** (5000 ist `registryzot`). Für NAS-lokale Pulls + den
  NAS-Host-Docker-Daemon-Mirror. Docker behandelt loopback automatisch als insecure.
- **Storage `/mnt/data/registry-cache`** (data-Pool, HDD-Mirror — Cache-Blobs sind groß).
  Vollständig getrennt von `registryzot`s `/mnt/data/harbor/zot`.
- **Isolation:** eigener Container, eigenes Datenverzeichnis, eigener Port/Host → `registryzot`
  wird nicht angefasst (Regression-Sicherheit).

## 3. Komponenten / Änderungen (Teil 1)

### 3.1 `stacks/23-registry-cache/compose.yaml`

```yaml
# 23-registry-cache — Pull-Through-Cache fuer oeffentliche Registries (docker.io/ghcr.io/quay.io/
# registry.k8s.io). SEPARAT von der privaten Registry (registryzot) — niemals mischen.
# Arcane-Gitsync-App ebenfalls "registry-cache" benennen (Slug ueberschreibt name:, s. README).
name: registry-cache

services:
  zot:
    image: ghcr.io/project-zot/zot:v2.1.17     # gleiche Linie wie die private Registry
    ports:
      - "127.0.0.1:5001:5000"                  # NAS-lokal + Docker-Daemon-Mirror; 5000 ist registryzot
    volumes:
      - /mnt/data/registry-cache:/var/lib/registry            # Cache-Blobs -> data-Pool
      - ./config/zot.json:/etc/zot/config.json:ro
      - /mnt/fast/appdata/registry-cache/sync-credentials.json:/etc/zot/sync-credentials.json:ro  # Docker-Hub-Token, NICHT in Git
    labels:
      - traefik.enable=true
      - traefik.http.routers.regcache.rule=Host(`mirror.${LAB_DOMAIN}`)
      - traefik.http.routers.regcache.entrypoints=websecure
      - traefik.http.routers.regcache.tls.certresolver=le
      - traefik.http.services.regcache.loadbalancer.server.port=5000
    networks: [edge]
    mem_limit: 512m
    restart: unless-stopped

networks:
  edge:
    external: true
```

### 3.2 `stacks/23-registry-cache/config/zot.json`

Kernpunkte (exakte `content`-Semantik wird im **Plan** gegen Zot v2.1.x verifiziert, nicht geraten):

```json
{
  "storage": {
    "rootDirectory": "/var/lib/registry",
    "gc": true,
    "retention": {
      "policies": [
        {
          "repositories": ["**"],
          "deleteReferrers": true,
          "keepTags": [{ "patterns": ["**"], "pulledWithin": "720h" }]
        }
      ]
    }
  },
  "http": {
    "address": "0.0.0.0",
    "port": "5000",
    "compat": ["docker2s2"],
    "accessControl": {
      "repositories": { "**": { "anonymousPolicy": ["read"] } }
    }
  },
  "log": { "level": "info" },
  "extensions": {
    "sync": {
      "enable": true,
      "credentialsFile": "/etc/zot/sync-credentials.json",
      "registries": [
        { "urls": ["https://ghcr.io"],          "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "ghcr.io/**",         "stripPrefix": true, "destination": "/" }] },
        { "urls": ["https://quay.io"],          "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "quay.io/**",         "stripPrefix": true, "destination": "/" }] },
        { "urls": ["https://registry.k8s.io"],  "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "registry.k8s.io/**", "stripPrefix": true, "destination": "/" }] },
        { "urls": ["https://registry-1.docker.io"], "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] }
      ]
    }
  }
}
```

- **docker.io am Root** (`prefix: "**"`, als **letzter** Eintrag = Catch-all) → der
  Docker-Daemon-`registry-mirrors`-Pfad (`/v2/library/nginx/...`) funktioniert transparent.
- **ghcr/quay/k8s Host-namespaced** (`<host>/**`, `stripPrefix → upstream-Root`) → containerd
  adressiert sie über `mirror.lab.appsfab.org/<host>/<repo>`, eindeutig auflösbar.
- **`accessControl` anonymous read**, keine `htpasswd`, kein `ci`-User (reine Public-Cache; kein Push).
- **UI/Trivy/scrub bewusst NICHT aktiviert** (YAGNI — die private Registry hat das; eine Cache
  braucht weder CVE-Scan ihrer Wegwerf-Blobs noch UI).

### 3.3 Secrets — `sync-credentials.json` (off-git)

Zot liest Sync-Credentials aus einer **Datei** (nicht ENV). Analog zur htpasswd der privaten
Registry liegt sie **auf dem NAS, nicht in Git**, read-only gemountet:

`/mnt/fast/appdata/registry-cache/sync-credentials.json`:
```json
{ "registry-1.docker.io": { "username": "<dockerhub-user>", "password": "<dockerhub-access-token>" } }
```
- **Operator-Prerequisite:** freien Docker-Hub-Account + **Access-Token** (kein Passwort) anlegen,
  Datei mit `chmod 600`, Owner `apps` ablegen. Token in 1Password hinterlegen.
- ghcr/quay/k8s laufen **anonym** (kein Eintrag nötig) — nur docker.io ratelimitet.

### 3.4 Retention / GC

Reine Cache → **kein Protect-List** (anders als der alte gemischte Ansatz). `gc:true` +
`retention` evictet Tags, die seit `pulledWithin` (Startwert **720h = 30 Tage**) nicht mehr
gepullt wurden. **`dryRun` NICHT gesetzt** (= aktiv) — es gibt keine load-bearing Repos zu
schützen. Konkrete Schwellen (Alter, ggf. Gesamtgröße) im Plan datengetrieben.

## 4. Verifikation (Definition of Done, Teil 1)

1. **Cold-Pull docker.io (Root):** auf dem NAS `docker pull 127.0.0.1:5001/library/hello-world`
   (oder via `mirror.lab.appsfab.org`) → Erfolg; **zweites** Pull lokal serviert (Zot-Log: sync-hit,
   kein externer Traffic).
2. **Cold-Pull Host-namespaced:** `…/ghcr.io/<owner>/<img>` → Erfolg, zweites Pull lokal.
   (Beweist die Prefix-Disambiguierung aus 3.2.)
3. **Docker-Hub-Auth aktiv:** Sync-Pull nutzt Credentials (authentifiziertes Budget, nicht anon) —
   Zot-Log / Docker-Hub-Rate-Header bestätigen.
4. **Retention/GC greift:** ein abgelaufener Cache-Tag wird beim GC-Lauf entfernt.
5. **Regression:** private `registryzot` unverändert pull-/pushbar (eigener Container/Daten —
   wird nicht berührt). `127.0.0.1:5000` weiter durch registryzot bedient.

## 5. Risiken / offene Punkte

- **Prefix-Präzedenz (Haupt-Risiko):** Zot muss einen Host-Pfad (`ghcr.io/x`) gegen die
  **spezifische** Registry auflösen statt gegen das docker.io-`**`-Catch-all. Mitigation:
  spezifische Hosts **vor** dem Catch-all listen (s. 3.2) und das Verhalten im Plan **gegen
  v2.1.x verifizieren** (nicht raten). **Fallback, falls fragil:** docker.io auf einen
  dedizierten `registry:2`-Proxy auslagern (Approach C) — bewahrt den kritischen
  docker.io-am-Root-Pfad; ghcr/quay/k8s bleiben im Zot.
- **Docker-Daemon-Mirror nur docker.io:** by-design (Daemon-Limit). ghcr/quay/k8s profitieren
  nur über containerd (Teil 2). Daher docker.io-am-Root als nicht verhandelbarer Kernpfad.
- **Cache-Wachstum** → Retention (3.4) ist Pflicht, nicht optional.
- **Token-Rotation:** Docker-Hub-Access-Token läuft ggf. ab → in 1Password vermerken; Rotation =
  Datei ersetzen + Container-Restart (Arcane recreate'd config-file-only-Änderungen NICHT von
  allein, [[nas-registry-cache]]).
- **Arcane-Projektname:** App-Slug == `name: registry-cache` benennen, sonst dieselbe Drift wie
  garage→garages3 (harmlos, aber wir vermeiden sie diesmal von Anfang an).

## 6. Folge-Specs (nicht hier umgesetzt)

- **Teil 2:** cluster-Repo `registries.yaml` (containerd, alle 4 Upstreams, Host-namespaced gegen `mirror.lab.appsfab.org`).
- **Teil 3:** Docker-Clients (Mac-Runner + NAS-Host) `daemon.json` `registry-mirrors` (docker.io → `mirror.lab.appsfab.org`).
