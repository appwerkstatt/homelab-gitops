# Registry Pull-Through Cache (registry:2, docker.io) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Eine eigenständige, gegen Docker Hub authentifizierte Pull-Through-Cache für docker.io aufsetzen — `registry:2` im proxy-Modus, getrennt von der privaten Registry `registryzot`.

**Architecture:** Neuer Stack `stacks/23-registry-cache/` als eigene Arcane-Gitsync-App: ein `registry:2`-proxy-Service für docker.io (Root-Pfad, transparenter Docker-Daemon-Mirror), Datenverzeichnis `/mnt/data/registry-cache`, Loopback `127.0.0.1:5001`, Traefik `mirror.lab.appsfab.org`. Auth via Arcane-ENV. ghcr/quay/k8s = Folge-Specs.

**Tech Stack:** registry:2 (Distribution v2.8.3) proxy mode, Docker Compose (Arcane GitOps), TrueNAS, Traefik.

**Spec:** `docs/specs/2026-06-06-registry-cache-redesign-design.md`

**Zugang:** SSH `truenas.server` (192.168.80.50); `sudo -n docker …` (christian nicht in docker-Gruppe). TrueNAS-SSH ist **flaky** → wenige, langlebige Sessions; GitHub-SSH:22 ebenfalls zeitweise flaky → `gh` (HTTPS) als Fallback.

---

## DONE (diese Session)

- **Task 1 (Operator):** Docker-Hub-Token erstellt; `sync-credentials.json` lag auf dem NAS.
  **Hinweis Pivot:** registry:2 nutzt **ENV**, nicht die Datei → Creds wandern in die Arcane-ENV
  (`DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`); die JSON-Datei ist obsolet.
- **Task 2 (Spike → DECISION GATE):** Zot-onDemand-Multi-Upstream **widerlegt** (kein
  Host-Namespacing) → Pivot auf `registry:2`. registry:2-docker.io-Spike **bestanden** (Cold-Pull
  ✓, Cache-Hit ~5 ms / TTL 168h ✓, Hub-Auth ✓). Throwaways abgeräumt, `registryzot`/`garages3`
  unberührt.

---

## Task 3: Stack-Datei anlegen

**Files:** Create `stacks/23-registry-cache/compose.yaml` (kein Config-File).

- [ ] **Step 1: `compose.yaml` schreiben** (Inhalt = Spec §3.1, registry:2 proxy, ENV-Creds, TTL 168h, Port 5001, Traefik `mirror.${LAB_DOMAIN}`, mem_limit 256m).

- [ ] **Step 2: Commit**

```bash
git add stacks/23-registry-cache/compose.yaml
git commit -m "feat(registry-cache): registry:2 pull-through proxy for docker.io"
```

## Task 4: Lokale Validierung

- [ ] **Step 1: compose lint** — `LAB_DOMAIN=lab.appsfab.org docker compose -f stacks/23-registry-cache/compose.yaml config -q` → exit 0 (unset `${DOCKERHUB_*}` = nur Warnung, ok).
- [ ] **Step 2: validate-Coverage** — `grep -n stacks .github/workflows/validate.yml`: Glob `stacks/*/compose.yaml` erfasst den neuen Stack automatisch.

## Task 5: README aktualisieren

**Files:** Modify `README.md` (`## Stacks`).

- [ ] **Step 1: Stacks-Tabelle ergänzen** (nach `22-harbor`):

```markdown
| `23-registry-cache` | registry:2 (proxy) — Pull-Through-Cache fuer Docker Hub (docker.io), getrennt von der privaten Registry | `data/registry-cache` |
```

- [ ] **Step 2: Arcane-Naming-Hinweis** (Fußnote der Tabelle):

```markdown
> **Neuer Stack ⇒ neue Arcane-Gitsync-App**, gleich wie `name:` benannt (hier `registry-cache`),
> sonst Drift wie garage→garages3 (s. `## Konventionen`).
```

- [ ] **Step 3: Commit** — `git add README.md && git commit -m "docs(registry-cache): list 23-registry-cache stack + Arcane naming note"`

## Task 6: Push + PR + validate-grün

- [ ] **Step 1: Push** — `GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=15' git push origin feat/registry-cache-redesign` (Fallback `gh`).
- [ ] **Step 2: PR** — `gh pr create --fill --base main` (Body: Spec/Plan + Operator-Schritte Task 7).
- [ ] **Step 3:** `gh pr checks <PR#> --watch` → `validate` pass.

## Task 7: Arcane-App + Deploy (Operator-gated)

- [ ] **Step 1 (Operator):** Arcane-Gitsync-App **`registry-cache`** anlegen (Quelle dieses Repo, Pfad `stacks/23-registry-cache`); in deren **Env** `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` setzen. (Optional: alte `sync-credentials.json` löschen.)
- [ ] **Step 2:** PR mergen → Arcane deployt (`docker compose -p registry-cache up -d`).
- [ ] **Step 3 (Agent):** `ssh truenas.server 'sudo -n docker ps | grep registry-cache'` → `registry-cache-dockerhub-1 Up` (Live-Name == `name:`).

## Task 8: Live-Verifikation (Definition of Done)

- [ ] **Step 1:** `/v2/` ping — `ssh truenas.server 'curl -fsS http://127.0.0.1:5001/v2/ -o /dev/null -w "%{http_code}\n"'` → 200.
- [ ] **Step 2: Cold-Pull** — `sudo -n docker pull 127.0.0.1:5001/library/hello-world:latest` → Downloaded.
- [ ] **Step 3: Cache-Hit** — `rmi` + erneut pullen; `sudo -n docker logs registry-cache-dockerhub-1 | grep -iE "scheduler|hello-world"` zeigt lokale Auslieferung + TTL-Entry.
- [ ] **Step 4: Auth** — Log ohne `401/unauthorized`.
- [ ] **Step 5: Regression** — `registryzot-zot-1` (Port 5000) + `garages3-garage-1` Up & unverändert; `curl 127.0.0.1:5000/v2/_catalog` → 200.

## Task 9: Abschluss

- [ ] **Step 1:** TTL/Cache bestätigt (Task 8.3 Scheduler-Entry).
- [ ] **Step 2: Memory** — `nas-registry-cache.md`: Redesign DEPLOYED als `registry-cache` (registry:2 proxy docker.io, Port 5001, `mirror.lab.appsfab.org`, ENV-auth); Zot-Multi-Upstream-Lehre festhalten; Folge-Specs offen. MEMORY.md-Zeile anpassen.
- [ ] **Step 3: Folge-Specs** vormerken: ghcr/quay (registry:2), registry.k8s.io (eigener Spike), Teil 2 (containerd registries.yaml), Teil 3 (daemon.json mirrors).

---

## Self-Review Coverage

- Spec §3.1 (registry:2 proxy) → Task 3.
- Spec §3.2 (ENV-Auth) → Task 7.1 + Task 8.4.
- Spec §3.3 (TTL-Retention) → Task 8.3 / 9.1.
- Spec §4 (DoD) → Task 8.
- Spec §5 (Risiken) → Task 7 (Token), Task 8.5 (Regression).
- Spec §6 (Folge-Specs) → Task 9.3.
