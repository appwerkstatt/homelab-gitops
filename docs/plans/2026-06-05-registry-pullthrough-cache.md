# Registry Pull-Through Cache (Zot sync) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Subagents must NOT run git** (homelab process rule) — the controller commits.

**Goal:** Turn the existing load-bearing Zot (`stacks/22-harbor`) into an on-demand pull-through cache for docker.io/ghcr.io/quay.io/registry.k8s.io, with a retention policy that evicts cold cache entries but never the private images — no new container.

**Architecture:** Add `extensions.sync` (onDemand) + `storage.retention` to `zot.json`, bump the container's `mem_limit`. Deploy is GitOps: merging to `main` makes Arcane redeploy the `registry` stack (a brief Zot restart). Retention rolls out `dryRun:true` first (observe, confirm it never targets the private repos), then flips to `dryRun:false`.

**Tech Stack:** Zot v2.1.17 (OCI registry), Docker Compose / Arcane, TrueNAS.

**Spec:** [docs/specs/2026-06-05-registry-pullthrough-cache-design.md](../specs/2026-06-05-registry-pullthrough-cache-design.md)

---

## File Structure

- `stacks/22-harbor/config/zot.json` — **modify**: add `extensions.sync` (4 upstreams, onDemand) and `storage.retention` (protect private repos, evict cold cache).
- `stacks/22-harbor/compose.yaml` — **modify**: `mem_limit` 256m→512m + role comment.

Branch: `feat/registry-pullthrough-cache` (worktree off `main`). Verification is operational (no unit-test suite). Several steps run **on the NAS** (`ssh truenas.server`, then `sudo -n docker …`) — these need the operator's authorization at run time.

---

## Task 1: Capture current live state (read-only, on the NAS)

**Files:** none (discovery; informs the retention protect-list).

- [ ] **Step 1: Confirm the live registry container/project name**

> The `garage→garages3` naming drift ([[nas-homelab-gitops]]) means the live Arcane project may not match the compose `name: registry`. Find the real container name:

```bash
ssh truenas.server 'sudo -n docker ps --format "{{.Names}}\t{{.Image}}" | grep -iE "zot|registry"'
```
Expected: one line like `registry-zot-1   ghcr.io/project-zot/zot:v2.1.17` (note the actual name `<NAME>` for later steps).

- [ ] **Step 2: Enumerate the existing PRIVATE repos (so retention protects all of them)**

```bash
ssh truenas.server 'sudo -n docker exec <NAME> wget -qO- http://localhost:5000/v2/_catalog'
```
Expected: a JSON list, e.g. `{"repositories":["library/netboot-console","lab-status"]}`. **Record every repo here** — they all go into the retention protect-list in Task 2. If the list has more than `library/netboot-console` + `lab-status`, add them.

---

## Task 2: Add `sync` + `retention` to `zot.json`

**Files:**
- Modify: `stacks/22-harbor/config/zot.json`

- [ ] **Step 1: Replace `zot.json` with the cache-enabled config**

Write `stacks/22-harbor/config/zot.json` to exactly this (adds `storage.retention` + `extensions.sync`; everything else unchanged). **If Task 1 Step 2 found private repos beyond the two listed, add them to the first policy's `repositories` array.**

```json
{
  "storage": {
    "rootDirectory": "/var/lib/registry",
    "retention": {
      "dryRun": true,
      "delay": "168h",
      "policies": [
        {
          "repositories": ["library/netboot-console", "lab-status"],
          "deleteUntagged": false,
          "keepTags": [{ "patterns": [".*"] }]
        },
        {
          "repositories": ["**"],
          "deleteUntagged": true,
          "keepTags": [{ "patterns": [".*"], "pulledWithin": "720h" }]
        }
      ]
    }
  },
  "http": {
    "address": "0.0.0.0",
    "port": "5000",
    "compat": ["docker2s2"],
    "auth": { "htpasswd": { "path": "/etc/zot/htpasswd" } },
    "accessControl": {
      "repositories": {
        "**": {
          "anonymousPolicy": ["read"],
          "policies": [
            { "users": ["ci"], "actions": ["read", "create", "update"] }
          ]
        }
      }
    }
  },
  "log": { "level": "info" },
  "extensions": {
    "ui": { "enable": true },
    "search": {
      "enable": true,
      "cve": {
        "updateInterval": "24h",
        "trivy": { "dbRepository": "ghcr.io/project-zot/trivy-db" }
      }
    },
    "scrub": { "enable": true, "interval": "24h" },
    "sync": {
      "enable": true,
      "registries": [
        { "urls": ["https://registry-1.docker.io"], "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] },
        { "urls": ["https://ghcr.io"],              "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] },
        { "urls": ["https://quay.io"],              "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] },
        { "urls": ["https://registry.k8s.io"],      "onDemand": true, "tlsVerify": true, "content": [{ "prefix": "**" }] }
      ]
    }
  }
}
```

- [ ] **Step 2: Validate JSON syntax**

```bash
python3 -m json.tool stacks/22-harbor/config/zot.json >/dev/null && echo "JSON OK"
```
Expected: `JSON OK`.

- [ ] **Step 3: Validate against Zot's own config checker**

`zot verify` parses + schema-checks the config. Mount a dummy htpasswd so the auth-path check is satisfied:

```bash
tmp=$(mktemp -d); : > "$tmp/htpasswd"
docker run --rm \
  -v "$PWD/stacks/22-harbor/config/zot.json":/tmp/zot.json:ro \
  -v "$tmp/htpasswd":/etc/zot/htpasswd:ro \
  ghcr.io/project-zot/zot:v2.1.17 verify /tmp/zot.json
```
Expected: a line like `config file ... is valid` and exit 0. If it errors on the `sync`/`retention` schema, fix per the message before continuing.

- [ ] **Step 4: Commit** (controller only)

```bash
git add stacks/22-harbor/config/zot.json
git commit -m "feat(registry): zot pull-through cache (sync) + cache retention"
```

---

## Task 3: Bump `mem_limit` + document the dual role

**Files:**
- Modify: `stacks/22-harbor/compose.yaml`

- [ ] **Step 1: Edit the comment + mem_limit**

In `stacks/22-harbor/compose.yaml`, change the header comment line 1 and the `mem_limit`:

Replace line 1:
```
# 22-harbor — schlanke Sofort-Variante: Zot (OCI-Registry). Harbor via Installer siehe README.md.
```
with:
```
# 22-harbor — Zot (OCI-Registry): Private-Registry (netboot-console, lab-status) UND
# Public-Pull-Through-Cache (sync onDemand: docker.io/ghcr.io/quay.io/registry.k8s.io).
```

Replace:
```
    mem_limit: 256m
```
with:
```
    mem_limit: 512m   # sync-Cache + UI/Trivy/scrub im selben Container
```

- [ ] **Step 2: Validate compose still parses**

```bash
docker compose -f stacks/22-harbor/compose.yaml config -q && echo "compose OK"
```
Expected: `compose OK` (env-not-set warnings are fine).

- [ ] **Step 3: Commit** (controller only)

```bash
git add stacks/22-harbor/compose.yaml
git commit -m "chore(registry): bump zot mem_limit 256m->512m for sync cache"
```

---

## Task 4: Deploy (dryRun retention) + verify pull-through

**Files:** none (deploy + operational verification).

- [ ] **Step 1: Push branch + open PR**

```bash
git push -u origin feat/registry-pullthrough-cache
gh pr create --repo appwerkstatt/homelab-gitops --base main --head feat/registry-pullthrough-cache \
  --title "feat(registry): Zot pull-through cache (sync) + retention" \
  --body "Part 1/3. See docs/plans/2026-06-05-registry-pullthrough-cache.md. Retention ships dryRun:true."
```
Expected: PR URL. Confirm the `validate` check passes (`gh pr checks <n> --watch`).

- [ ] **Step 2: Merge → Arcane redeploys the registry stack**

Merge the PR (operator, or `gh pr merge --merge`). Arcane redeploys `22-harbor` → **brief Zot restart** (netboot/lab-status pulls blip for a few seconds; both are on-demand, so impact is minimal). Wait for the container to be `Up` again:

```bash
ssh truenas.server 'sudo -n docker ps --format "{{.Names}}\t{{.Status}}" | grep -iE "zot|registry"'
```
Expected: `<NAME>   Up <short> (healthy or running)`.

- [ ] **Step 3: Private-repo regression check (must still pull)**

```bash
ssh truenas.server 'sudo -n docker exec <NAME> wget -qO- http://localhost:5000/v2/library/netboot-console/tags/list'
```
Expected: JSON tag list for netboot-console (the private image is unaffected).

- [ ] **Step 4: Pull-through test (docker.io, the primary pain)**

Pull a small public image that is NOT yet cached, *through* Zot, from the NAS host:

```bash
ssh truenas.server 'sudo -n docker pull 127.0.0.1:5000/library/hello-world:latest && echo PULL_OK'
```
Expected: the image pulls (Zot sync fetched it once from docker.io) and prints `PULL_OK`. Then confirm it is now cached locally:

```bash
ssh truenas.server 'sudo -n docker exec <NAME> wget -qO- http://localhost:5000/v2/library/hello-world/tags/list'
```
Expected: `{"name":"library/hello-world","tags":["latest"]}` — served from local cache.

- [ ] **Step 5: Inspect what retention WOULD delete (dryRun still true)**

```bash
ssh truenas.server 'sudo -n docker logs <NAME> 2>&1 | grep -iE "retention|gc|dry" | tail -30'
```
Expected: dry-run GC log lines. **Confirm none of the private repos (`library/netboot-console`, `lab-status`, plus any from Task 1 Step 2) appear as deletion candidates.** If a private repo shows up, STOP — add it to the protect-list (Task 2 Step 1) and re-run from Task 2.

---

## Task 5: Flip retention to live (`dryRun:false`)

**Files:**
- Modify: `stacks/22-harbor/config/zot.json`

- [ ] **Step 1: Set `dryRun` false**

In `stacks/22-harbor/config/zot.json`, change:
```json
      "dryRun": true,
```
to:
```json
      "dryRun": false,
```

- [ ] **Step 2: Re-validate + commit** (controller only)

```bash
python3 -m json.tool stacks/22-harbor/config/zot.json >/dev/null && echo "JSON OK"
git add stacks/22-harbor/config/zot.json
git commit -m "feat(registry): enable retention GC (dryRun off) after verify"
```

- [ ] **Step 3: Deploy + verify GC runs cleanly**

Push to the branch / open+merge a follow-up PR; after Arcane redeploys, confirm a real GC pass leaves the private repos intact:

```bash
ssh truenas.server 'sudo -n docker exec <NAME> wget -qO- http://localhost:5000/v2/_catalog'
```
Expected: the catalog still lists every private repo from Task 1 Step 2 (cache entries may shrink over time per `pulledWithin: 720h`, private repos never).

---

## Self-Review notes (planner)

- **Spec coverage:** sync onDemand for the 4 upstreams (Task 2) ✓; mem bump + dual-role comment (Task 3) ✓; retention protecting private repos + evicting cold cache (Tasks 2/4/5) ✓; live-name-drift caution (Task 1) ✓; private-repo regression + pull-through verify (Task 4) ✓; decomposition note — client wiring is parts 2/3, untouched here ✓.
- **Safety:** retention rolls out `dryRun:true` first (Task 4 Step 5 confirms private repos are never deletion candidates) before `dryRun:false` (Task 5) — GC cannot silently eat the load-bearing netboot-console/lab-status images.
- **Schema source:** `sync`/`retention` JSON verified against Zot v2.1.x docs; Task 2 Step 3 `zot verify` is the hard gate that catches any schema mismatch before deploy.
- **No placeholders:** every config/command is concrete; the only runtime substitution is `<NAME>` (the live container name discovered in Task 1 Step 1, since it may differ from `registry` due to the documented naming drift).
- **Out of scope (own specs):** containerd `registries.yaml` (cluster), Docker `daemon.json` mirrors (Mac runner + NAS host).
