# Registry Pull-Through Cache (Zot sync) — Design

> Stand: 2026-06-05 · Repo: **homelab-gitops** (TrueNAS, Arcane-driven GitOps)
> Goal: den bereits laufenden Zot zur **On-Demand Pull-Through-Cache** für öffentliche
> Registries machen, damit wiederholte externe Pulls über LAN statt über die 100-Mbit-Leitung
> laufen — und die docker.io-Anon-Ratelimits nicht mehr greifen. **Kein neuer Container.**

---

## 0. Why this exists (and why now)

Die 100-Mbit-Uplink + der **docker.io Anon-Pull-Budget** (100 Pulls / 6h / IP) sind ein
wiederkehrender Schmerz: der Mac-Forgejo-Runner ist daran schon verhungert ("Error obtaining
docker token", siehe [[forgejo-mac-runner-dood]]), und der k3s-Cluster zieht bei jedem
Rollout/Reboot dieselben Public-Images neu. Eine lokale Pull-Through-Cache löst beides: erstes
Pull zieht einmal von extern + cached auf dem NAS, jedes weitere Pull kommt mit LAN-Speed.

**Kein Harbor.** Der Stack heißt zwar `22-harbor`, deployt aber **Zot** (`name: registry`,
`ghcr.io/project-zot/zot:v2.1.17`) — und der ist bereits **load-bearing**: er serviert
`registry.lab.appsfab.org` + `127.0.0.1:5000` und beherbergt **netboot-console** (von
`30-netboot` gepullt) **und** das Cluster-M5-Image `registry.lab.appsfab.org/lab-status`.
Zot hat hier schon **UI + Trivy-CVE-Scanning + scrub** aktiv und **anonymous read** erlaubt —
Harbors Headline-Features sind also längst da. Für reines Caching wäre Harbor (~2–3 GB RAM,
Multi-Container) Overkill. Wir erweitern stattdessen den vorhandenen Zot um die
**`sync`-Extension** (onDemand = Pull-Through).

## 1. Scope

Dieses Feature zerfällt in **drei** Teile (verschiedene Repos/Hosts). **Diese Spec = Teil 1.**

**In scope (Teil 1 — homelab-gitops):**
- `stacks/22-harbor/config/zot.json`: `sync`-Block (onDemand) für **docker.io, ghcr.io,
  quay.io, registry.k8s.io**.
- `stacks/22-harbor/compose.yaml`: `mem_limit` 256m → **512m**; Kommentar, dass dieser Zot jetzt
  Private-Registry **und** Public-Cache ist.
- **Retention/GC** für die Cache-Blobs, damit `/mnt/data/harbor/zot` den data-Pool nicht vollläuft.

**Out of scope (eigene Folge-Specs):**
- **Teil 2 (cluster-Repo):** `/etc/rancher/k3s/registries.yaml` — containerd-Mirrors auf den
  k3s-Nodes. containerd kann **alle vier** Upstreams transparent spiegeln.
- **Teil 3 (Host-Config):** Docker-Clients (Mac-Forgejo-Runner + NAS-Host-Daemon) — `registry-mirrors`
  in `daemon.json`, **nur docker.io** (Docker-Daemon-Limit; ghcr/quay/k8s gehen dort nicht
  transparent). docker.io ist aber genau der Ratelimit-Schmerz → deckt den realen Fall ab.

## 2. Architektur / Datenfluss

```
  Client will  docker.io/library/nginx:1.27
        │  (Client-Mirror-Config: containerd registries.yaml  ODER  docker registry-mirrors)
        ▼
  registry.lab.appsfab.org   (= Zot, anonymous read)
        │
        ├─ Cache-Hit?  ── ja ──►  serviert aus /mnt/data/harbor/zot   (LAN-Speed)
        │
        └─ nein  ──►  Zot sync (onDemand) pullt EINMAL vom Upstream,
                      cached lokal, serviert danach lokal
```

Der **containerd**-Pfad (k3s) ist transparent für alle vier Upstreams; der **Docker-Daemon**-Pfad
ist auf docker.io beschränkt (Daemon-Limit). Anonymous read ist bereits aktiv → Clients brauchen
zum Pullen der Cache-Inhalte **keine** Credentials (der `ci`-User bleibt nur für Push).

## 3. Komponenten / Änderungen (Teil 1)

### 3.1 `stacks/22-harbor/config/zot.json` — `sync`-Extension
Unter `extensions` ergänzen (Startpunkt; exakte `content`/Endpoint-Disambiguierung wird im Plan
gegen Zot-v2.1.x-Verhalten validiert):

```json
"sync": {
  "enable": true,
  "registries": [
    { "urls": ["https://registry-1.docker.io"], "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] },
    { "urls": ["https://ghcr.io"],              "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] },
    { "urls": ["https://quay.io"],              "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] },
    { "urls": ["https://registry.k8s.io"],      "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] }
  ]
}
```

**Disambiguierungs-Hinweis (Plan-Detail):** mit `prefix: "**"` matcht jeder Block alle Repos —
welche Upstream-Registry ein eingehender Pull trifft, muss eindeutig sein. Auflösung im Plan:
entweder containerd-`mirrors` mappen jeden Upstream-Host auf einen distinkten Zot-Mirror-Endpoint,
oder die Reihenfolge/`content`-Prefixe werden je Upstream-Namespace geschärft. Gegen die echte
Zot-Version verifizieren, nicht raten.

### 3.2 `stacks/22-harbor/compose.yaml`
- `mem_limit: 256m` → **`512m`** (sync zusätzlich zu UI/Trivy/scrub im selben Container).
- Kommentar: "Zot = Private-Registry **und** Public-Pull-Through-Cache (sync onDemand)".

### 3.3 Retention / GC (der einzige echt neue Betriebspunkt)
Gecachte Public-Images wachsen `/mnt/data/harbor/zot` unbegrenzt. Zot-`storage.retention`
(Tag-/Alter-basierte Policies + GC) konfigurieren, damit der data-Pool nicht vollläuft —
z.B. ungenutzte Cache-Tags nach N Tagen entfernen, **die Private-Repos (netboot-console,
lab-status) aber ausnehmen**. Exakte Policy-Werte im Plan (datengetrieben).

## 4. Verifikation (Definition of Done, Teil 1)
- Auf dem NAS ein **noch nicht gecachtes** Public-Image über `registry.lab.appsfab.org` ziehen →
  Erfolg; **zweites** Pull wird lokal serviert (kein externer Traffic; Zot-Log zeigt sync-hit).
- Die **bestehenden Private-Images** (netboot-console, lab-status) lassen sich weiterhin
  pullen/pushen (Regression-Check; `ci`-Push unverändert).
- Retention greift (GC-Lauf entfernt einen abgelaufenen Cache-Tag, lässt Private-Repos in Ruhe).
- **Live-Container-/Projektname zuerst bestätigen** (`sudo docker ps | grep -i zot|registry`):
  wegen der `garage`→`garages3`-Namensdrift ([[nas-homelab-gitops]]) ist nicht garantiert, dass
  das Arcane-Projekt `registry` heißt.

## 5. Risiken / offene Punkte
- **Cache-Wachstum** → Retention-Policy (3.3) ist Pflicht, nicht optional.
- **Doppelrolle** (Private + Cache in einem Zot): akzeptiert — anonymous-read trennt Pull vom
  `ci`-Push; Storage geteilt (Retention nimmt Private-Repos aus).
- **Upstream-Disambiguierung** (3.1): muss gegen Zot v2.1.x verifiziert werden; ggf. distinkte
  Mirror-Endpoints je Upstream.
- **Branch/Worktree-Hygiene:** Arbeit in Worktree `…worktrees/registry-cache` ab `main`
  (nicht im Haupt-Checkout).

## 6. Folge-Specs (nicht hier umgesetzt)
- **Teil 2:** cluster-Repo `registries.yaml` (containerd, alle 4 Upstreams).
- **Teil 3:** Docker-Clients (Mac-Runner + NAS-Host) `daemon.json` registry-mirrors (docker.io).
