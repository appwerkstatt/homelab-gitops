# Registry Pull-Through Cache (separate Instanz) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine eigenständige, gegen Docker Hub authentifizierte Pull-Through-Cache (cache-only Zot) für docker.io/ghcr.io/quay.io/registry.k8s.io aufsetzen — strikt getrennt von der privaten Registry `registryzot`.

**Architecture:** Neuer Stack `stacks/23-registry-cache/` als eigene Arcane-Gitsync-App (eigener Container, Datenverzeichnis `/mnt/data/registry-cache`, Loopback `127.0.0.1:5001`, Traefik-Host `mirror.lab.appsfab.org`). Zot `extensions.sync` (onDemand): docker.io am Root (Docker-Daemon-Mirror-Kompatibilität) + ghcr/quay/k8s Host-namespaced (containerd). Auth gegen Docker Hub via off-git Credentials-Datei.

**Tech Stack:** Zot v2.1.17, Docker Compose (Arcane-driven GitOps), TrueNAS, Traefik.

**Spec:** `docs/specs/2026-06-06-registry-cache-redesign-design.md`

**Zugang:** SSH `truenas.server` (192.168.80.50); `christian` ist NICHT in der docker-Gruppe → Docker braucht `sudo -n docker …` (passwortlos via builtin_administrators). GitHub-SSH:22 war zeitweise flaky → Branch-/PR-Operationen ggf. über `gh` (HTTPS).

**Hinweis Worktree:** Wegen des wiederkehrenden Shared-Checkout-Kollisions-Risikos ([[loki-chart-fork-and-promtail-eol]]) bei Bedarf in einem Worktree ausführen. Branch `feat/registry-cache-redesign` existiert bereits (Spec liegt darauf).

---

## Task 1: Operator-Prerequisite — Docker-Hub-Token + Credentials-Datei

**Wer:** Operator (Agent kann keinen Docker-Hub-Account anlegen). Muss VOR Task 2 (Spike) fertig sein.

**Files:**
- Create (auf dem NAS, NICHT in Git): `/mnt/fast/appdata/registry-cache/sync-credentials.json`

- [ ] **Step 1: Docker-Hub-Account + Access-Token**

Falls kein Account: freien Docker-Hub-Account anlegen. Dann unter *Account Settings → Personal access tokens* ein Token mit Scope **Public Repo Read-only** erzeugen. Token + Username in 1Password ablegen.

- [ ] **Step 2: Verzeichnis + Credentials-Datei anlegen**

```bash
ssh truenas.server
sudo install -d -o apps -g apps -m 750 /mnt/fast/appdata/registry-cache
sudo tee /mnt/fast/appdata/registry-cache/sync-credentials.json >/dev/null <<'JSON'
{ "registry-1.docker.io": { "username": "DOCKERHUB_USER", "password": "DOCKERHUB_TOKEN" } }
JSON
sudo chown apps:apps /mnt/fast/appdata/registry-cache/sync-credentials.json
sudo chmod 600 /mnt/fast/appdata/registry-cache/sync-credentials.json
```
(`DOCKERHUB_USER`/`DOCKERHUB_TOKEN` durch die echten Werte ersetzen.)

- [ ] **Step 3: Token verifizieren (beweist, dass das Token gültig ist)**

```bash
echo 'DOCKERHUB_TOKEN' | sudo -n docker login docker.io -u DOCKERHUB_USER --password-stdin
```
Expected: `Login Succeeded`. Danach `sudo -n docker logout docker.io` (der Cache nutzt die Datei, nicht das Daemon-Login).

- [ ] **Step 4: JSON-Gültigkeit prüfen**

Run: `sudo -n cat /mnt/fast/appdata/registry-cache/sync-credentials.json | python3 -m json.tool`
Expected: pretty-printed JSON, kein Fehler.

---

## Task 2: Spike — Prefix-Präzedenz gegen Zot v2.1.x verifizieren (DECISION GATE)

**Ziel:** Beweisen, dass ein Host-namespaced Pull (`ghcr.io/…`) NICHT fälschlich gegen das docker.io-`**`-Catch-all aufgelöst wird — BEVOR wir den GitOps-Deploy bauen. Wegwerf-Container, kein Arcane, kein Traefik, eigener Port/Datenverzeichnis.

**Files:**
- Create (temporär auf dem NAS): `/tmp/zot-cache-spike/config.json`

- [ ] **Step 1: Spike-Config schreiben** (= die spätere `zot.json`, s. Task 3.2)

```bash
ssh truenas.server
mkdir -p /tmp/zot-cache-spike/data
cat > /tmp/zot-cache-spike/config.json <<'JSON'
{
  "storage": { "rootDirectory": "/var/lib/registry", "gc": true,
    "retention": { "policies": [ { "repositories": ["**"], "deleteReferrers": true,
      "keepTags": [{ "patterns": ["**"], "pulledWithin": "720h" }] } ] } },
  "http": { "address": "0.0.0.0", "port": "5000", "compat": ["docker2s2"],
    "accessControl": { "repositories": { "**": { "anonymousPolicy": ["read"] } } } },
  "log": { "level": "debug" },
  "extensions": { "sync": { "enable": true, "credentialsFile": "/etc/zot/sync-credentials.json",
    "registries": [
      { "urls": ["https://ghcr.io"],          "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "ghcr.io/**",         "stripPrefix": true, "destination": "/" }] },
      { "urls": ["https://quay.io"],          "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "quay.io/**",         "stripPrefix": true, "destination": "/" }] },
      { "urls": ["https://registry.k8s.io"],  "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "registry.k8s.io/**", "stripPrefix": true, "destination": "/" }] },
      { "urls": ["https://registry-1.docker.io"], "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] }
    ] } }
}
JSON
```

- [ ] **Step 2: Config formal verifizieren**

Run:
```bash
sudo -n docker run --rm -v /tmp/zot-cache-spike/config.json:/etc/zot/config.json:ro \
  ghcr.io/project-zot/zot:v2.1.17 verify /etc/zot/config.json
```
Expected: `... config file is valid`. (Overlap-Warnungen zu Sync-Content sind erwartbar/ok.)

- [ ] **Step 3: Wegwerf-Zot starten**

```bash
sudo -n docker run -d --name zot-cache-spike -p 127.0.0.1:5099:5000 \
  -v /tmp/zot-cache-spike/data:/var/lib/registry \
  -v /tmp/zot-cache-spike/config.json:/etc/zot/config.json:ro \
  -v /mnt/fast/appdata/registry-cache/sync-credentials.json:/etc/zot/sync-credentials.json:ro \
  ghcr.io/project-zot/zot:v2.1.17
sleep 3 && sudo -n docker ps --filter name=zot-cache-spike
```
Expected: Container `Up`.

- [ ] **Step 4: docker.io am Root pullen (Auth-Pfad)**

Run: `sudo -n docker pull 127.0.0.1:5099/library/hello-world:latest`
Expected: `Pull complete` / `Status: Downloaded`.

- [ ] **Step 5: Host-namespaced pullen — der eigentliche Disambiguierungs-Test**

```bash
sudo -n docker pull 127.0.0.1:5099/ghcr.io/project-zot/zot:v2.1.17
sudo -n docker pull 127.0.0.1:5099/registry.k8s.io/pause:3.9
sudo -n docker pull 127.0.0.1:5099/quay.io/prometheus/busybox:latest
```
Expected: alle drei `Downloaded`. **Kritisch:** wenn ein Host-namespaced Pull stattdessen über docker.io aufgelöst würde, käme `not found`/`manifest unknown` → DESIGN-RISIKO bestätigt.

- [ ] **Step 6: Logs prüfen — korrekter Upstream + Auth**

Run: `sudo -n docker logs zot-cache-spike 2>&1 | grep -iE "sync|upstream|registry-1.docker.io|ghcr.io" | tail -30`
Expected: docker.io-Pull zeigt `registry-1.docker.io` (authentifiziert, kein 401/anon-ratelimit); ghcr/k8s/quay-Pulls zeigen den jeweils RICHTIGEN Upstream-Host.

- [ ] **Step 7: DECISION GATE festhalten**

- **PASS** (alle Pulls korrekt aufgelöst) → Approach A bestätigt, weiter mit Task 3 (Config aus Step 1 ist die finale).
- **FAIL** (Host-namespaced misroutet / Catch-all schluckt sie) → STOP. Fallback C: docker.io auf dedizierten `registry:2`-Proxy auslagern, Zot nur für ghcr/quay/k8s. Plan dann anpassen (Spec §5). Dem Operator melden, nicht raten.

- [ ] **Step 8: Spike abräumen**

```bash
sudo -n docker rm -f zot-cache-spike
sudo -n rm -rf /tmp/zot-cache-spike
sudo -n docker rmi 127.0.0.1:5099/library/hello-world:latest 127.0.0.1:5099/ghcr.io/project-zot/zot:v2.1.17 127.0.0.1:5099/registry.k8s.io/pause:3.9 127.0.0.1:5099/quay.io/prometheus/busybox:latest 2>/dev/null || true
```
Expected: Container weg (`docker ps` zeigt ihn nicht mehr), temp-Dir weg. **registryzot/garages3 unberührt** (eigener Port 5099, eigenes /tmp-Dir).

---

## Task 3: Stack-Dateien anlegen

**Files:**
- Create: `stacks/23-registry-cache/compose.yaml`
- Create: `stacks/23-registry-cache/config/zot.json`

- [ ] **Step 1: `compose.yaml` schreiben**

```yaml
# 23-registry-cache — Pull-Through-Cache fuer oeffentliche Registries (docker.io/ghcr.io/quay.io/
# registry.k8s.io). SEPARAT von der privaten Registry (registryzot) — niemals mischen.
# WICHTIG: die Arcane-Gitsync-App ebenfalls "registry-cache" benennen — der Arcane-Slug
# ueberschreibt das name:-Feld (s. README Konventionen / nas-homelab-gitops).
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

- [ ] **Step 2: `config/zot.json` schreiben** (identisch zur Spike-Config aus Task 2.1, aber `log.level` = `info`)

```json
{
  "storage": {
    "rootDirectory": "/var/lib/registry",
    "gc": true,
    "retention": {
      "policies": [
        { "repositories": ["**"], "deleteReferrers": true,
          "keepTags": [{ "patterns": ["**"], "pulledWithin": "720h" }] }
      ]
    }
  },
  "http": {
    "address": "0.0.0.0",
    "port": "5000",
    "compat": ["docker2s2"],
    "accessControl": { "repositories": { "**": { "anonymousPolicy": ["read"] } } }
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

- [ ] **Step 3: Commit**

```bash
git add stacks/23-registry-cache/
git commit -m "feat(registry-cache): separate cache-only Zot stack (sync onDemand, 4 upstreams)"
```

---

## Task 4: Lokale Validierung

**Files:** keine (nur Checks).

- [ ] **Step 1: zot.json formal verifizieren** (lokal auf dem Mac via OrbStack-Docker — die Datei liegt im Checkout)

Run (im Repo-Root):
```bash
docker run --rm -v "$PWD/stacks/23-registry-cache/config/zot.json":/etc/zot/config.json:ro \
  ghcr.io/project-zot/zot:v2.1.17 verify /etc/zot/config.json
```
Expected: `config file is valid`. (Sync-Content-Overlap-Warnungen sind erwartbar/ok.)

- [ ] **Step 2: compose lint (wie der `validate`-Check)**

Run: `LAB_DOMAIN=lab.appsfab.org docker compose -f stacks/23-registry-cache/compose.yaml config -q`
Expected: exit 0, keine Ausgabe. (Bei fehlendem lokalem Docker: auf dem NAS via `sudo -n docker compose … config -q`.)

- [ ] **Step 3: bestätigen, dass der Repo-`validate`-Workflow den neuen Stack mit abdeckt**

Run: `grep -n "stacks" .github/workflows/validate.yml`
Expected: der Glob über `stacks/*/compose.yaml` erfasst den neuen Stack automatisch (kein Workflow-Edit nötig). Falls Stacks einzeln gelistet sind: `23-registry-cache` ergänzen.

---

## Task 5: README aktualisieren

**Files:**
- Modify: `README.md` (Abschnitt `## Stacks`)

- [ ] **Step 1: Stacks-Tabelle ergänzen** (nach der `22-harbor`-Zeile einfügen)

```markdown
| `23-registry-cache` | Zot v2.1.17 — Pull-Through-Cache (docker.io/ghcr.io/quay.io/registry.k8s.io), getrennt von der privaten Registry | `data/registry-cache` |
```

- [ ] **Step 2: Hinweis auf Arcane-App-Benennung** (am Ende der Stacks-Tabelle oder als Fußnote)

```markdown
> **Neuer Stack ⇒ neue Arcane-Gitsync-App.** Die App **gleich wie `name:`** im compose benennen
> (hier `registry-cache`), sonst Drift wie garage→garages3 (s. `## Konventionen`).
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(registry-cache): list 23-registry-cache stack + Arcane naming note"
```

---

## Task 6: Push, PR, validate-grün

**Files:** keine.

- [ ] **Step 1: Push**

Run: `GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=15' git push -u origin feat/registry-cache-redesign`
Expected: Branch gepusht. (Bei SSH:22-Timeout: später erneut oder via `gh`.)

- [ ] **Step 2: PR öffnen**

Run: `gh pr create --fill --base main --head feat/registry-cache-redesign`
Expected: PR-URL. Body sollte Spec/Plan referenzieren + Task-1/Task-7 Operator-Schritte nennen.

- [ ] **Step 3: validate abwarten**

Run: `gh pr checks <PR#> --watch`
Expected: `validate` = pass. Bei Fehler → Task 4 erneut, Ursache fixen.

---

## Task 7: Arcane-App anlegen + Deploy (Operator-gated)

**Wer:** Operator für Step 1–2 (Arcane-UI), Agent für die Verifikation danach.

- [ ] **Step 1: Arcane-Gitsync-App `registry-cache` anlegen**

In der Arcane-UI eine neue Compose-/Gitsync-App erstellen: Quelle = dieses Repo, Pfad = `stacks/23-registry-cache`, **App-Name = `registry-cache`** (Slug muss `registry-cache` ergeben → Live-Projekt == compose `name:`). Keine Stack-Env nötig (Secrets sind die file-basierte `sync-credentials.json`; `LAB_DOMAIN` kommt aus `.env.global`).

- [ ] **Step 2: PR mergen → Arcane deployt**

```bash
gh pr merge <PR#> --squash --delete-branch
```
Arcane synchronisiert den Stack und startet `docker compose -p registry-cache up -d`.

- [ ] **Step 3: Container live + korrekt benannt**

Run: `ssh truenas.server 'sudo -n docker ps --format "{{.Names}}\t{{.Status}}\t{{.Image}}" | grep registry-cache'`
Expected: `registry-cache-zot-1   Up …   ghcr.io/project-zot/zot:v2.1.17`. **Beweist auch:** Live-Projektname == `name:` (keine Drift).

- [ ] **Step 4: Loopback erreichbar**

Run: `ssh truenas.server 'curl -fsS http://127.0.0.1:5001/v2/ -o /dev/null -w "%{http_code}\n"'`
Expected: `200`.

---

## Task 8: Live-Verifikation (Definition of Done)

**Files:** keine.

- [ ] **Step 1: Cold-Pull docker.io (Root)**

```bash
ssh truenas.server 'sudo -n docker pull 127.0.0.1:5001/library/hello-world:latest'
```
Expected: `Downloaded`. (Cache-Miss → sync onDemand zieht einmal von docker.io.)

- [ ] **Step 2: Zweites Pull = lokal (Cache-Hit)**

```bash
ssh truenas.server 'sudo -n docker rmi 127.0.0.1:5001/library/hello-world:latest >/dev/null 2>&1; sudo -n docker pull 127.0.0.1:5001/library/hello-world:latest; sudo -n docker logs registry-cache-zot-1 2>&1 | grep -iE "hello-world|sync" | tail -5'
```
Expected: schnelles Pull; Log zeigt lokale Auslieferung (kein erneuter Upstream-Sync).

- [ ] **Step 3: Cold-Pull Host-namespaced (ghcr)**

```bash
ssh truenas.server 'sudo -n docker pull 127.0.0.1:5001/ghcr.io/project-zot/zot:v2.1.17'
```
Expected: `Downloaded` (beweist die Prefix-Disambiguierung live).

- [ ] **Step 4: Docker-Hub-Auth aktiv (kein Anon-Ratelimit)**

Run: `ssh truenas.server 'sudo -n docker logs registry-cache-zot-1 2>&1 | grep -iE "registry-1.docker.io|401|unauthorized|rate" | tail -10'`
Expected: Upstream-Pull authentifiziert; keine 401/anon-ratelimit-Meldungen.

- [ ] **Step 5: Regression — private Registry unberührt**

```bash
ssh truenas.server 'sudo -n docker ps --format "{{.Names}}\t{{.Status}}" | grep -E "registryzot-zot-1|garages3-garage-1"; curl -fsS http://127.0.0.1:5000/v2/_catalog -o /dev/null -w "registryzot %{http_code}\n"'
```
Expected: `registryzot-zot-1 Up` (unverändert), `garages3-garage-1 Up`, `registryzot 200`. Der Cache hat eigenen Port/Daten → keine Berührung.

---

## Task 9: Retention/GC bestätigen + Memory

**Files:** keine (Repo); Memory-Update.

- [ ] **Step 1: GC/Retention geladen**

Run: `ssh truenas.server 'sudo -n docker logs registry-cache-zot-1 2>&1 | grep -iE "gc|retention|scrub" | tail -10'`
Expected: GC aktiv/eingeplant; Retention-Policy geladen (kein Konfig-Fehler). Vollständige Eviction ist zeitabhängig (720h) → hier nur "aktiv & geladen" bestätigen, nicht erzwingen.

- [ ] **Step 2: Memory aktualisieren**

`nas-registry-cache.md` updaten: Redesign DEPLOYED als separate Instanz `registry-cache` (Port 5001, Host `mirror.lab.appsfab.org`, alle 4 Upstreams, Docker-Hub-auth), Prefix-Präzedenz live bestätigt (oder Fallback C, falls Task 2 FAIL), Parts 2/3 noch offen. Index-Zeile in `MEMORY.md` anpassen.

- [ ] **Step 3: Folge-Specs vormerken (nicht hier umsetzen)**

Teil 2 (cluster-Repo `registries.yaml`, containerd, alle 4 Upstreams Host-namespaced gegen `mirror.lab.appsfab.org`) und Teil 3 (Mac-Runner + NAS-Host `daemon.json` registry-mirrors docker.io) als separate Specs/Sessions.

---

## Self-Review Coverage

- Spec §2 (Platzierung) → Task 3 (compose: Port/Host/Storage/edge) + Task 7 (Arcane-App, Live-Name).
- Spec §3.2 (sync 4 Upstreams, docker.io-Root + namespaced) → Task 2 (Spike) + Task 3.2 (Config) + Task 8.1/8.3 (live).
- Spec §3.3 (Docker-Hub-Creds off-git) → Task 1 + Task 8.4 (Auth live).
- Spec §3.4 (Retention/GC) → Task 3.2 (Config) + Task 9.1.
- Spec §4 (DoD) → Task 8 (alle Punkte) + Task 9.1.
- Spec §5 (Prefix-Risiko + Fallback C) → Task 2.7 (Decision Gate).
- Spec §6 (Folge-Specs) → Task 9.3.
