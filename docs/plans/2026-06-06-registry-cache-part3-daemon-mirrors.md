# Registry-Cache Teil 3 — Docker-Daemon registry-mirrors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Mac-Runner (OrbStack) + TrueNAS-Host Docker-Daemons auf die docker.io-Cache (`registry-cache`) zeigen lassen — transparent, fallback-sicher.

**Architecture:** Mac → `https://mirror.lab.appsfab.org` via `~/.orbstack/config/docker.json` + Engine-Restart. NAS-Host → `http://127.0.0.1:5001` (Hairpin → Loopback) via supported middleware `midclt docker.update`. docker.io-only; Fallback auf docker.io eingebaut.

**Tech Stack:** OrbStack (macOS), TrueNAS SCALE middleware (`midclt`), Docker `registry-mirrors`.

**Spec:** `docs/specs/2026-06-06-registry-cache-part3-daemon-mirrors-design.md`

**Reihenfolge-Logik:** Mac zuerst (Schmerzpunkt, low-risk, voll reversibel) → end-to-end verifizieren → DANN NAS-Host (Daemon-Bounce-Risiko, vorher messen). Host-Änderungen, **kein Repo-Deploy** (Spec/Plan werden trotzdem als Doku committed/PR'd).

---

## Task 1: Mac-Runner (OrbStack) — registry-mirror setzen

**Files:** Modify `~/.orbstack/config/docker.json`

- [ ] **Step 1: Backup der aktuellen Config**

Run: `cp ~/.orbstack/config/docker.json ~/.orbstack/config/docker.json.bak && cat ~/.orbstack/config/docker.json.bak`
Expected: zeigt `{ "dns": ["192.168.10.1"] }`.

- [ ] **Step 2: registry-mirror ergänzen** (den `dns`-Key behalten)

Datei `~/.orbstack/config/docker.json` exakt so schreiben:
```json
{
  "dns": ["192.168.10.1"],
  "registry-mirrors": ["https://mirror.lab.appsfab.org"]
}
```

- [ ] **Step 3: JSON valide?**

Run: `python3 -m json.tool ~/.orbstack/config/docker.json`
Expected: pretty-print ohne Fehler.

- [ ] **Step 4: OrbStack-Docker-Engine neu starten**

Run: `orb restart docker`
Expected: kehrt ohne Fehler zurück; danach `docker version` antwortet (Daemon oben).

- [ ] **Step 5: Mirror aktiv?**

Run: `docker info 2>/dev/null | grep -A1 "Registry Mirrors"`
Expected: zeigt `https://mirror.lab.appsfab.org`.

---

## Task 2: Mac — Cache-Routing live + Runner gesund

**Files:** keine.

- [ ] **Step 1: frisches (noch nicht gecachtes) docker.io-Image pullen**

Run: `docker pull alpine:3.20`
Expected: `Pull complete` / `Downloaded`.

- [ ] **Step 2: Pull lief über die Cache? (NAS-Cache-Log)**

Run:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=20 truenas.server 'sudo -n docker logs registry-cache-dockerhub-1 2>&1 | grep -iE "library/alpine" | tail -5'
```
Expected: GET-Einträge für `/v2/library/alpine/manifests|blobs/...` → beweist, dass der Mac-Pull über die Cache lief (nicht direkt docker.io).

- [ ] **Step 3: Forgejo-Runner-Container wieder oben** (kam via `--restart unless-stopped` zurück)

Run: `docker ps --format '{{.Names}}\t{{.Status}}' | grep -i runner`
Expected: der Forgejo-Runner-Container ist `Up`.

- [ ] **Step 4: Fallback-Sanity** (Mirror-Ausfall bricht Pulls nicht)

Run: `docker pull busybox:1.36 2>&1 | tail -2`
Expected: Erfolg. (Selbst bei Cache-Problemen fällt Docker auf docker.io zurück — kein Bruch.)

---

## Task 3: NAS-Host — Bounce messen + Mirror via Middleware setzen

**Files:** keine (Middleware-Config; sie schreibt `/etc/docker/daemon.json`).

> **HAZARD:** `docker.update` lädt/restartet den Docker-Daemon. Restart = ALLE NAS-Apps bouncen kurz. In einem ruhigen Fenster ausführen. Alles fällt bei Cache-Ausfall auf docker.io zurück.

- [ ] **Step 1: Baseline aufnehmen** (um Reload vs. Restart zu erkennen)

Run:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=20 truenas.server '
echo "dockerd PID:"; pgrep -x dockerd
echo "container uptimes:"; sudo -n docker ps --format "{{.Names}}\t{{.RunningFor}}\t{{.Status}}" | grep -E "registry-cache|keycloak-keycloak-1|paperless-webserver|garages3-garage-1" '
```
Expected: notiere dockerd-PID + die Uptimes (zum Nachher-Vergleich).

- [ ] **Step 2: Format prüfen + Mirror setzen** (Job-Methode → `-job`)

Run:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=25 truenas.server '
sudo -n midclt call -job docker.update '"'"'{"insecure_registry_mirrors": ["http://127.0.0.1:5001"]}'"'"' 2>&1 | tail -5'
```
Expected: Job endet `SUCCESS`. Falls das Format abgelehnt wird, alternativ `["127.0.0.1:5001"]` (host:port) testen — danach in daemon.json prüfen (Step 3), welche Form als `registry-mirrors` ankommt.

- [ ] **Step 3: daemon.json + docker info bestätigen**

Run:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=20 truenas.server '
echo "=== daemon.json mirror/insecure ==="; sudo -n cat /etc/docker/daemon.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(\"registry-mirrors=\",d.get(\"registry-mirrors\"));print(\"insecure-registries=\",d.get(\"insecure-registries\"))"
echo "=== docker info ==="; sudo -n docker info 2>/dev/null | grep -A2 "Registry Mirrors"'
```
Expected: `registry-mirrors` enthält `http://127.0.0.1:5001`; `docker info` listet den Mirror.

- [ ] **Step 4: Reload vs. Restart feststellen + Apps gesund**

Run:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=20 truenas.server '
echo "dockerd PID jetzt:"; pgrep -x dockerd
echo "container uptimes jetzt:"; sudo -n docker ps --format "{{.Names}}\t{{.RunningFor}}\t{{.Status}}" | grep -E "registry-cache|keycloak-keycloak-1|paperless-webserver|garages3-garage-1"
echo "alle Container Up?"; sudo -n docker ps --filter status=running --format "{{.Names}}" | wc -l'
```
Expected: gleiche dockerd-PID + unveränderte Uptimes ⇒ **Reload** (kein Bounce). Neue PID / frische Uptimes ⇒ **Restart** (Apps gebounced, aber wieder oben). In jedem Fall: alle erwarteten Apps `Up`; Befund notieren.

---

## Task 4: NAS-Host — Cache-Routing live

**Files:** keine.

- [ ] **Step 1: frisches docker.io-Image auf dem NAS-Host pullen**

Run:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=25 truenas.server 'sudo -n docker pull hello-world:linux 2>&1 | tail -3'
```
Expected: Erfolg (über `http://127.0.0.1:5001` → Cache → docker.io).

- [ ] **Step 2: lief über die Cache?**

Run:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=20 truenas.server 'sudo -n docker logs registry-cache-dockerhub-1 2>&1 | grep -iE "hello-world" | tail -5'
```
Expected: GET-Einträge für `/v2/library/hello-world/...` mit Client-IP des NAS-Host-Daemons → beweist Cache-Routing.

---

## Task 5: Abschluss

**Files:** keine (Repo); Memory + PR.

- [ ] **Step 1: Spec/Plan-PR** mergen (Doku; kein Deploy). PR über `gh` (HTTPS-Token, falls SSH:22 flaky).
- [ ] **Step 2: Memory** — `nas-registry-cache.md`: Teil 3 DONE (Mac OrbStack `https://mirror.lab.appsfab.org`; NAS-Host `http://127.0.0.1:5001` via `midclt docker.update insecure_registry_mirrors`); Hairpin→Loopback-Befund; Reload-vs-Restart-Ergebnis (aus Task 3.4); Cache-Routing beidseitig live. Teil 2 (cluster containerd) bleibt offen.
- [ ] **Step 3: Folge** — Teil 2 (cluster-Repo `registries.yaml`) als eigene Spec vormerken.

---

## Self-Review Coverage

- Spec §2/§3.1 (Mac OrbStack mirror) → Task 1 + Task 2.
- Spec §3.2 (NAS midclt, loopback, insecure) → Task 3 (+ Format-Check Step 2).
- Spec §3.2-HAZARD (reload vs restart, app-bounce) → Task 3.1 (Baseline) + 3.4 (Messung).
- Spec §4 (DoD: docker info mirror, cache-routing, fallback, apps gesund) → Task 1.5/2/3.3/3.4/4.
- Spec §5 (Risiken) → Task 2.4 (Fallback), Task 3 (Bounce).
- Spec §6 (Teil 2 offen) → Task 5.3.
