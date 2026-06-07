# NAS Backup — Phase 2 (Local Cross-Disk Replication) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the irreplaceable data on the `fast`/`data` mirrors a second on-site copy on a **separate physical disk** (the 6 TB `backup` pool) via native TrueNAS **Replication Tasks** — the "2 copies / 2 media" of 3-2-1 (offsite B2 = Phase 3). Defined as re-runnable, idempotent `midclt`-as-code, consistent with Phase 1.

**Architecture:** A new `docs/nas-backup/replication-tasks.py` creates one LOCAL PUSH replication task per Tier 1+2 source dataset (`data/paperless`, `data/homes`, `data/makerlab`, `fast/appdata`) → `backup/replica/<source>`, replicating the Phase-1 `auto-%Y-%m-%d_%H-%M` snapshots daily at 04:00. `deploy.sh` gains a step that runs it. Idempotent against `replication.query`.

**Tech Stack:** TrueNAS SCALE 25.10 `replication` middleware (`midclt`), ZFS LOCAL replication, Python 3.

**Spec:** [docs/specs/2026-06-05-nas-backup-strategy-design.md](../specs/2026-06-05-nas-backup-strategy-design.md) (Phase 2 = §8 step 2; §5.2)

---

## Verified-live facts (spiked before writing — no guessing)

The exact `replication.create` payload was proven on the box against `data/makerlab`:
- **PUSH replication rejects `naming_schema`** → must use **`also_include_naming_schema`** to select which snapshots to send.
- **The `backup` pool is encrypted (aes-256-gcm); `data`/`fast` are not.** ZFS refuses to recv an unencrypted source into an encrypted parent unless replication encryption is configured. Fix: **`encryption: true, encryption_inherit: true`** → the replica inherits the backup-pool key (no separate key to manage; the key is already in the TrueNAS config, which Phase-1 config-export backs up).
- Result of the spike: `backup/replica/data/makerlab` created, `encryption=aes-256-gcm` (encryptionroot `backup`), `readonly=on`, snapshots replicated, task state `FINISHED`. **That first task already exists (name `replica-data-makerlab`) and is skipped by the idempotent script.**

**Sources (Tier 1+2 on the redundant mirrors).** Deliberately excludes `backup/HomeFolders` + `backup/dumps` (already on the `backup` disk — replicating within the same single disk adds no resilience; their offsite copy is Phase-3 B2) and Tier-3 `data/provisioning`/`data/media` (snapshot-only per spec).

| Source | → Target |
|---|---|
| `data/paperless` | `backup/replica/data/paperless` |
| `data/homes` | `backup/replica/data/homes` |
| `data/makerlab` | `backup/replica/data/makerlab` *(done in spike)* |
| `fast/appdata` | `backup/replica/fast/appdata` |

---

## File Structure

- `docs/nas-backup/replication-tasks.py` — **create**: idempotent LOCAL-replication-task creator (mirrors `snapshot-tasks.py`). Skips existing tasks (by name) and missing source datasets.
- `docs/nas-backup/deploy.sh` — **modify**: add a step 4 that runs `replication-tasks.py`; update the final echo.
- `docs/nas-backup/README.md` — **modify**: add a Phase-2 section (what it does, the encryption-inherit note, restore caveat).

**Branch:** `feat/nas-backup-phase2-replication` in worktree `…/homelab-gitops.worktrees/nas-backup-phase2`.
**Verification is empirical** — `midclt`/`zfs` queries. Execution needs root SSH to `192.168.80.50` (flaky — retry with `ServerAliveInterval`).

---

## Task 1: `replication-tasks.py` — idempotent replication-task creator

**Files:**
- Create: `docs/nas-backup/replication-tasks.py`

- [ ] **Step 1: Write the script**

Create `docs/nas-backup/replication-tasks.py` with exactly this content:

```python
#!/usr/bin/env python3
"""Idempotent creator for TrueNAS LOCAL Replication Tasks (NAS backup, Phase 2).

Replicates the Phase-1 'auto-' snapshots of the Tier 1+2 datasets on the fast/data
mirrors to backup/replica/<source> on the separate (encrypted) 6 TB backup disk =
Copy 2 of 3-2-1. Re-runnable: skips tasks that already exist and missing sources.

Verified-live notes (TrueNAS SCALE 25.10):
- PUSH replication rejects 'naming_schema'; use 'also_include_naming_schema'.
- The backup pool is encrypted, data/fast are not. ZFS refuses unencrypted->encrypted
  parent, so the replica must be encrypted: encryption + encryption_inherit make it
  inherit the backup-pool key (already stored in the TrueNAS config / config-export).
"""
import json
import subprocess
import sys

NAMING = "auto-%Y-%m-%d_%H-%M"
SCHEDULE = {"minute": "0", "hour": "4", "dom": "*", "month": "*", "dow": "*"}  # daily 04:00, after snapshots

# Tier 1+2 sources on the fast/data mirrors. backup-pool-resident datasets are excluded
# (same single disk = no resilience gain); Tier 3 is snapshot-only (spec §3).
SOURCES = [
    "data/paperless",
    "data/homes",
    "data/makerlab",
    "fast/appdata",
]


def midclt(method, *args):
    cmd = ["midclt", "call", method]
    cmd += [a if isinstance(a, str) else json.dumps(a) for a in args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        sys.exit(f"midclt {method} timed out (middleware wedged?)")
    if res.returncode != 0:
        sys.exit(f"midclt {method} failed: {res.stderr.strip()}")
    return json.loads(res.stdout) if res.stdout.strip() else None


def main():
    existing = midclt("replication.query")
    have = {t["name"] for t in existing}
    datasets = {d["id"] for d in midclt("pool.dataset.query", [], {"select": ["id"]})}

    created = missing = 0
    for src in SOURCES:
        if src not in datasets:
            print(f"WARN  {src:22} source dataset missing — skipped")
            missing += 1
            continue
        name = "replica-" + src.replace("/", "-")
        if name in have:
            print(f"skip  {name} (exists)")
            continue
        target = f"backup/replica/{src}"
        midclt("replication.create", {
            "name": name, "direction": "PUSH", "transport": "LOCAL",
            "source_datasets": [src], "target_dataset": target,
            "recursive": True, "also_include_naming_schema": [NAMING],
            "auto": True, "schedule": SCHEDULE,
            "retention_policy": "SOURCE",
            "readonly": "SET",
            "encryption": True, "encryption_inherit": True,
            "allow_from_scratch": True, "enabled": True,
        })
        print(f"CREATE {name:28} -> {target}")
        created += 1

    print(f"\nDone. created={created} pre-existing={len(existing)} missing-sources={missing}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax-check locally**

Run:
```bash
python3 -m py_compile docs/nas-backup/replication-tasks.py && echo OK
```
Expected: `OK`, exit 0. (Remove any `__pycache__/` it creates.)

- [ ] **Step 3: Commit** (controller/main agent only — subagents must not run git)

```bash
git add docs/nas-backup/replication-tasks.py
git commit -m "feat(backup): idempotent local replication-task creator (Phase 2)"
```

---

## Task 2: `deploy.sh` — run the replication creator

**Files:**
- Modify: `docs/nas-backup/deploy.sh`

- [ ] **Step 1: Append the replication step**

Replace the final block of `docs/nas-backup/deploy.sh`:

```bash
# 3) create the periodic snapshot tasks (idempotent)
python3 "$SELF/snapshot-tasks.py"

echo "Phase-1 deploy complete."
```

with:

```bash
# 3) create the periodic snapshot tasks (idempotent)
python3 "$SELF/snapshot-tasks.py"

# 4) create the local replication tasks (idempotent)
python3 "$SELF/replication-tasks.py"

echo "Backup deploy complete (Phase 1 + 2)."
```

- [ ] **Step 2: Syntax-check**

Run:
```bash
bash -n docs/nas-backup/deploy.sh && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add docs/nas-backup/deploy.sh
git commit -m "feat(backup): deploy.sh runs replication-tasks.py (Phase 2)"
```

---

## Task 3: `README.md` — document Phase 2

**Files:**
- Modify: `docs/nas-backup/README.md`

- [ ] **Step 1: Add a Phase-2 section**

Append this section to `docs/nas-backup/README.md` (after the Phase-1 section, before "Later phases"):

```markdown
## Phase 2 — local cross-disk replication

`replication-tasks.py` (run by `deploy.sh`) creates one LOCAL PUSH replication task per
Tier 1+2 source on the `fast`/`data` mirrors → `backup/replica/<source>` on the separate
6 TB `backup` disk (Copy 2 of 3-2-1), daily at 04:00, replicating the Phase-1 `auto-`
snapshots, destination `readonly`.

**Encryption:** the `backup` pool is encrypted and `data`/`fast` are not, so each replica
is created encrypted, **inheriting the backup-pool key** (`encryption_inherit`). The key
lives in the TrueNAS config (and is captured by the nightly config-export), so the replicas
unlock automatically with the pool. Restore note: a replica is only readable while the
`backup` pool is unlocked.

Verify:
```bash
midclt call replication.query | python3 -c "import sys,json;[print(t['name'],t['state']['state']) for t in json.load(sys.stdin)]"
zfs list -r -o name,used,readonly,encryptionroot backup/replica
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/nas-backup/README.md
git commit -m "docs(backup): document Phase-2 replication"
```

---

## Task 4: Deploy to the NAS and verify

**Files:** none (operational). Requires root SSH to `192.168.80.50` (retry on timeout).

- [ ] **Step 1: Copy the updated scripts to the NAS**

```bash
scp -o ConnectTimeout=20 -r docs/nas-backup root@192.168.80.50:/mnt/backup/scripts/
```

- [ ] **Step 2: Run the deploy (idempotent — Phase 1 tasks skip, Phase 2 creates the new replication tasks)**

```bash
ssh -o ConnectTimeout=20 -o ServerAliveInterval=5 root@192.168.80.50 'bash /mnt/backup/scripts/nas-backup/deploy.sh'
```
Expected tail: `CREATE replica-data-paperless -> …`, `replica-data-homes`, `replica-fast-docker-appdata` created; `skip replica-data-makerlab (exists)` (from the spike); `Backup deploy complete (Phase 1 + 2).`

- [ ] **Step 3: Run each new replication task once and confirm it finishes**

```bash
ssh -o ConnectTimeout=20 root@192.168.80.50 '
for n in replica-data-paperless replica-data-homes replica-fast-docker-appdata; do
  id=$(midclt call replication.query "[[\"name\",\"=\",\"$n\"]]" | python3 -c "import sys,json;print(json.load(sys.stdin)[0][\"id\"])")
  midclt call replication.run "$id" >/dev/null 2>&1; echo "ran $n (id=$id)"
done
sleep 45
midclt call replication.query | python3 -c "import sys,json;[print(t[\"name\"], t[\"state\"][\"state\"], str(t[\"state\"].get(\"error\"))[:120]) for t in json.load(sys.stdin)]"
'
```
Expected: all four tasks `FINISHED`, error `None`. (Large `fast/appdata` ~61 G may still be `RUNNING` on first pass — re-query until `FINISHED`.)

- [ ] **Step 4: Confirm the replicas exist (encrypted, readonly) with snapshots**

```bash
ssh -o ConnectTimeout=20 root@192.168.80.50 '
zfs list -r -o name,used,readonly,encryptionroot backup/replica
echo "--- snapshot counts on replicas ---"
for d in data/paperless data/homes data/makerlab fast/appdata; do
  echo "  backup/replica/$d : $(zfs list -t snapshot -o name 2>/dev/null | grep -c "^backup/replica/$d@")"
done
'
```
Expected: `backup/replica/{data/paperless,data/homes,data/makerlab,fast/appdata}` present, `readonly=on`, `encryptionroot=backup`, each with ≥1 `auto-` snapshot.

---

## Task 5: Push branch and open PR

**Files:** none (git — main agent only).

- [ ] **Step 1: Push + PR**

```bash
git -C /Users/christian/Workspace/appsfab/NAS/homelab-gitops.worktrees/nas-backup-phase2 push -u origin feat/nas-backup-phase2-replication
gh pr create --repo appwerkstatt/homelab-gitops --base main --head feat/nas-backup-phase2-replication \
  --title "NAS backup Phase 2: local cross-disk replication" \
  --body "Adds docs/nas-backup/replication-tasks.py (idempotent LOCAL replication of Tier 1+2 fast/data datasets -> backup/replica/<src>, encrypted via encryption_inherit, readonly, daily 04:00) and wires it into deploy.sh. Verified live (4 tasks FINISHED, replicas present). Spec/plan: docs/specs + docs/plans."
```

- [ ] **Step 2: Report the PR URL.** After merge: clean up the worktree + branch (and **confirm the commits actually landed in main** — a merge can race ahead of later pushes).

---

## Self-Review notes (planning)

- **Spec coverage (§5.2 / §8 step 2):** native LOCAL replication tasks (Task 1) for the Tier 1+2 mirror datasets → `backup/replica` (Copy 2); excludes backup-pool-resident + Tier 3 per spec; daily after snapshots; readonly; based on the Phase-1 `auto-` schema. ✓
- **No placeholders:** the `replication.create` payload was spiked live (PUSH→`also_include_naming_schema`; encrypted pool→`encryption_inherit`) — exact, not guessed.
- **Idempotency:** keyed on task `name` (`replica-<dotted-source>`); skips existing (incl. the spike's `replica-data-makerlab`) + missing sources; re-runnable for fresh-NAS recovery.
- **Type/name consistency:** task names generated as `"replica-" + src.replace("/","-")` match the verify commands in Task 4 (`replica-data-paperless`, etc.).
- **Known risk:** first replication of `fast/appdata` (~61 G) may take a while — Task 4 Step 3 notes re-querying until `FINISHED`.
