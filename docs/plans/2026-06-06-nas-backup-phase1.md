# NAS Backup — Phase 1 (Local Snapshots + Config Export) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End the current zero-backup state on the TrueNAS box by creating native ZFS **Periodic Snapshot Tasks** for all relevant datasets and a nightly **TrueNAS config-export** cron — all defined as re-runnable, idempotent `midclt`-as-code so a future reinstall can reproduce them.

**Architecture:** Three small artifacts live in the repo under `docs/nas-backup/`: a Python creator for the snapshot tasks (idempotent against `pool.snapshottask.query`), a bash config-export script (tars `/data/freenas-v1.db` + `pwenc_secret`), and an idempotent `deploy.sh` that installs the export script to a persistent path, registers the nightly cron, and runs the snapshot creator. Everything is applied by SSHing to the NAS as root and running `deploy.sh`. No external accounts/secrets are needed for Phase 1 (cloud/B2 is Phase 3).

**Tech Stack:** TrueNAS SCALE 25.10 middleware (`midclt`), ZFS periodic snapshot tasks, Python 3 (ships on TrueNAS), bash, `tar`/`find`, cron via `cronjob` middleware.

**Spec:** [docs/specs/2026-06-05-nas-backup-strategy-design.md](../specs/2026-06-05-nas-backup-strategy-design.md) (Phase 1 = §8 step 1; schedules = §5.1; tiers = §3)

---

## File Structure

- `docs/nas-backup/snapshot-tasks.py` — **create**: idempotent creator of Periodic Snapshot Tasks from a declarative `SPECS` table. Skips tasks that already exist and datasets that don't exist (robust on a partially-restored / fresh NAS).
- `docs/nas-backup/config-export.sh` — **create**: the script the nightly cron runs; tars the config DB + pw seed into `/mnt/backup/dumps/truenas-config/`, prunes >30 days.
- `docs/nas-backup/deploy.sh` — **create**: idempotent orchestrator (run on the NAS): install export script to `/mnt/backup/scripts/nas-backup/`, register the cron if absent, run `snapshot-tasks.py`.
- `docs/nas-backup/README.md` — **create**: deploy/recovery doc — how to re-apply on a fresh NAS after a reinstall, and the alert-channel note.

**Branch:** `docs/nas-backup-strategy`, checked out in an **isolated worktree** at `…/homelab-gitops.worktrees/nas-backup` (the main checkout is shared with another session — work here, not there). Spec + plan are already committed on it.
**Verification is empirical** — `midclt` queries + `zfs list`, no unit-test suite. Execution requires **root SSH to `192.168.80.50`** (flaky — retry with `ServerAliveInterval`).

**Tier → schedule (from spec §5.1, encoded in `SPECS`):**

| Tier | Datasets | Frequent task | Weekly task |
|------|----------|---------------|-------------|
| 1 | `data/paperless`, `data/homes`, `backup/HomeFolders`, `backup/dumps` | every 12 h, keep 2 wk | Sun, keep 8 wk |
| 2 | `fast/appdata`, `fast/ix-apps`, `data/makerlab` | daily 03:00, keep 1 wk | Sun, keep 4 wk |
| 3 | `data/provisioning`, `data/media` | daily 03:00, keep 1 wk | — |

`backup/timemachine` is deliberately **excluded** (TM self-versions; spec §3).

---

## Task 1: `snapshot-tasks.py` — idempotent snapshot-task creator

**Files:**
- Create: `docs/nas-backup/snapshot-tasks.py`

- [ ] **Step 1: Write the script**

Create `docs/nas-backup/snapshot-tasks.py` with exactly this content:

```python
#!/usr/bin/env python3
"""Idempotent creator for TrueNAS Periodic Snapshot Tasks (NAS backup, Phase 1).

Re-runnable 'midclt-as-code': safe to run repeatedly and on a fresh NAS after a
reinstall. Skips snapshot tasks that already exist and datasets that don't exist.
Schedules/retention follow docs/specs/2026-06-05-nas-backup-strategy-design.md §5.1.
"""
import json
import subprocess
import sys

NAMING = "auto-%Y-%m-%d_%H-%M"  # matches the pre-reinstall scheme

# (dataset, recursive, frequent-hour-field, frequent-lifetime, weekly-lifetime|None)
SPECS = [
    # Tier 1 — irreplaceable: every 12 h + weekly
    ("data/paperless",      True,  "0,12", (2, "WEEK"), (8, "WEEK")),
    ("data/homes",          True,  "0,12", (2, "WEEK"), (8, "WEEK")),
    ("backup/HomeFolders",  False, "0,12", (2, "WEEK"), (8, "WEEK")),
    ("backup/dumps",        True,  "0,12", (2, "WEEK"), (8, "WEEK")),
    # Tier 2 — important/large: daily + weekly
    ("fast/appdata", True,  "3",    (1, "WEEK"), (4, "WEEK")),
    ("fast/ix-apps",        True,  "3",    (1, "WEEK"), (4, "WEEK")),
    ("data/makerlab",       True,  "3",    (1, "WEEK"), (4, "WEEK")),
    # Tier 3 — reproducible: daily only
    ("data/provisioning",   True,  "3",    (1, "WEEK"), None),
    ("data/media",          True,  "3",    (1, "WEEK"), None),
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
    existing = midclt("pool.snapshottask.query")
    # Idempotency key: (dataset, schedule.hour, schedule.dow). Relies on the middleware
    # round-tripping the crontab strings verbatim (verified on this build) so a re-run
    # cleanly skips existing tasks. If a task is later edited in the TrueNAS UI its stored
    # hour string can diverge and a re-run could re-create it — re-check after manual edits.
    have = {(t["dataset"], t["schedule"]["hour"], t["schedule"]["dow"]) for t in existing}
    datasets = {d["id"] for d in midclt("pool.dataset.query", [], {"select": ["id"]})}

    created = missing = 0
    for dataset, recursive, fhour, flife, wlife in SPECS:
        if dataset not in datasets:
            print(f"WARN  {dataset:22} dataset missing — skipped")
            missing += 1
            continue
        plans = [({"minute": "0", "hour": fhour, "dom": "*", "month": "*", "dow": "*"}, flife)]
        if wlife:
            plans.append(({"minute": "0", "hour": "5", "dom": "*", "month": "*", "dow": "0"}, wlife))
        for sched, (lval, lunit) in plans:
            key = (dataset, sched["hour"], sched["dow"])
            if key in have:
                print(f"skip  {dataset:22} {sched['hour']:>4}h dow={sched['dow']} (exists)")
                continue
            midclt("pool.snapshottask.create", {
                "dataset": dataset, "recursive": recursive, "exclude": [],
                "lifetime_value": lval, "lifetime_unit": lunit,
                "naming_schema": NAMING, "schedule": sched,
                "allow_empty": True, "enabled": True,
            })
            print(f"CREATE {dataset:22} {sched['hour']:>4}h dow={sched['dow']} keep {lval}{lunit}")
            created += 1

    print(f"\nDone. created={created} pre-existing={len(existing)} missing-datasets={missing}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax-check locally**

Run:
```bash
python3 -m py_compile docs/nas-backup/snapshot-tasks.py && echo OK
```
Expected: `OK`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add docs/nas-backup/snapshot-tasks.py
git commit -m "feat(backup): idempotent ZFS snapshot-task creator (Phase 1)"
```

---

## Task 2: `config-export.sh` — nightly config DB backup

**Files:**
- Create: `docs/nas-backup/config-export.sh`

- [ ] **Step 1: Write the script**

Create `docs/nas-backup/config-export.sh` with exactly this content:

```bash
#!/usr/bin/env bash
# Nightly TrueNAS config export (NAS backup, Phase 1).
# Backs up the middleware config DB (SMB shares, snapshot/replication tasks, users,
# alert services, …) plus the pw-encryption seed, so a reinstall can be fully restored.
# Idempotent; safe to run repeatedly. Output is later swept offsite by restic (Phase 3).
set -euo pipefail

DEST=/mnt/backup/dumps/truenas-config
RETAIN_DAYS=30
ts="$(date +%Y-%m-%d_%H-%M)"

mkdir -p "$DEST"
# /data/freenas-v1.db = config DB; /data/pwenc_secret = seed to decrypt stored secrets.
for f in /data/freenas-v1.db /data/pwenc_secret; do
  if [ ! -f "$f" ]; then
    echo "ERROR: $f not found — not a TrueNAS host?" >&2
    exit 1
  fi
done
# write to a temp file then atomically move, so a killed run never leaves a truncated
# tarball that a later restic sweep would treat as a valid backup.
tmp="$DEST/.truenas-config-$ts.tar.gz.tmp"
tar -czf "$tmp" -C /data freenas-v1.db pwenc_secret
chmod 600 "$tmp"
mv "$tmp" "$DEST/truenas-config-$ts.tar.gz"

find "$DEST" -type f -name 'truenas-config-*.tar.gz' -mtime +"$RETAIN_DAYS" -delete
echo "wrote $DEST/truenas-config-$ts.tar.gz"
```

- [ ] **Step 2: Syntax-check locally**

Run:
```bash
bash -n docs/nas-backup/config-export.sh && echo OK
```
Expected: `OK`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add docs/nas-backup/config-export.sh
git commit -m "feat(backup): nightly TrueNAS config-export script (Phase 1)"
```

---

## Task 3: `deploy.sh` — idempotent on-NAS orchestrator

**Files:**
- Create: `docs/nas-backup/deploy.sh`

- [ ] **Step 1: Write the script**

Create `docs/nas-backup/deploy.sh` with exactly this content:

```bash
#!/usr/bin/env bash
# Idempotent Phase-1 deploy — run ON the NAS as root, from this directory.
#   ssh root@192.168.80.50 'bash /mnt/backup/scripts/nas-backup/deploy.sh'
# Installs the config-export script to a persistent (non-boot-pool) path, registers the
# nightly cron if absent, and creates the periodic snapshot tasks. Re-runnable.
set -euo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)"
INSTALL=/mnt/backup/scripts/nas-backup
CRON_DESC="NAS backup: nightly TrueNAS config export"

# 1) install the export script to a persistent path (survives an OS reinstall on boot-pool).
#    Skip the copy when deploy.sh is already running from the install dir (e.g. scp'd
#    straight there) — install/cp abort on a same-file copy.
mkdir -p "$INSTALL"
if [ "$SELF/config-export.sh" -ef "$INSTALL/config-export.sh" ]; then
  echo "config-export.sh already in place at $INSTALL"
else
  install -m 755 "$SELF/config-export.sh" "$INSTALL/config-export.sh"
  echo "installed $INSTALL/config-export.sh"
fi

# 2) register the nightly cron (02:30) if not already present.
#    Capture explicitly so a query failure (e.g. middleware still warming up during a
#    fresh-NAS recovery) fails LOUD instead of silently skipping creation.
existing="$(midclt call cronjob.query "[[\"description\",\"=\",\"$CRON_DESC\"]]")" \
  || { echo "ERROR: cronjob.query failed (middleware not ready?)" >&2; exit 1; }
if [ "$existing" = "[]" ]; then
  midclt call cronjob.create "{\"user\":\"root\",\"command\":\"$INSTALL/config-export.sh\",\"description\":\"$CRON_DESC\",\"schedule\":{\"minute\":\"30\",\"hour\":\"2\",\"dom\":\"*\",\"month\":\"*\",\"dow\":\"*\"},\"enabled\":true,\"stdout\":false,\"stderr\":true}" >/dev/null
  echo "created cron: $CRON_DESC"
else
  echo "cron already present: $CRON_DESC"
fi

# 3) create the periodic snapshot tasks (idempotent)
python3 "$SELF/snapshot-tasks.py"

echo "Phase-1 deploy complete."
```

- [ ] **Step 2: Syntax-check locally**

Run:
```bash
bash -n docs/nas-backup/deploy.sh && echo OK
```
Expected: `OK`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add docs/nas-backup/deploy.sh
git commit -m "feat(backup): idempotent on-NAS Phase-1 deploy script"
```

---

## Task 4: `README.md` — deploy & reinstall-recovery doc

**Files:**
- Create: `docs/nas-backup/README.md`

- [ ] **Step 1: Write the doc**

Create `docs/nas-backup/README.md` with exactly this content:

````markdown
# NAS Backup — operational scripts (midclt-as-code)

Reproducible TrueNAS backup config for the homelab. These scripts ARE the source of
truth: TrueNAS middleware config (snapshot tasks, cron, shares) lives only in the
config DB and is lost on an OS reinstall — re-running `deploy.sh` recreates it.

See the strategy: [`../specs/2026-06-05-nas-backup-strategy-design.md`](../specs/2026-06-05-nas-backup-strategy-design.md).

## Phase 1 — local snapshots + config export

Deploy (or re-deploy after a reinstall):

```bash
# from a machine that can reach the NAS:
scp -r docs/nas-backup root@192.168.80.50:/mnt/backup/scripts/
ssh root@192.168.80.50 'bash /mnt/backup/scripts/nas-backup/deploy.sh'
```

What it creates (all idempotent):
- **Periodic Snapshot Tasks** per `snapshot-tasks.py` (`SPECS` table) — naming `auto-%Y-%m-%d_%H-%M`.
- **Nightly cron 02:30** running `config-export.sh` → `/mnt/backup/dumps/truenas-config/`.

Verify:
```bash
midclt call pool.snapshottask.query | python3 -m json.tool   # tasks present
zfs list -t snapshot -o name | grep auto-                    # snapshots materialising
ls -l /mnt/backup/dumps/truenas-config/                      # config tarballs
```

## Alerts (channel = open decision, spec §10)

TrueNAS native Alert Services support Email/Slack/Telegram (not ntfy). Until the
channel is chosen, alerts are visible in the TrueNAS UI. To wire delivery, see
Task 7 of the Phase-1 plan (Email Alert Service via configured SMTP).

## Later phases (separate plans)
- Phase 2 — local cross-disk replication (`fast`/`data` → `backup/replica`).
- Phase 3 — `50-backup` stack: pg_dump/forgejo dump + restic→Backblaze B2.
- Phase 4 — Velero→Garage + fold `velero` bucket into B2 + first restore drill.
````

- [ ] **Step 2: Commit**

```bash
git add docs/nas-backup/README.md
git commit -m "docs(backup): Phase-1 deploy & reinstall-recovery README"
```

---

## Task 5: Deploy to the NAS and verify tasks/cron exist

**Files:** none (operational). Requires root SSH to `192.168.80.50`.

- [ ] **Step 1: Copy the scripts to the NAS**

Run:
```bash
scp -o ConnectTimeout=15 -r docs/nas-backup root@192.168.80.50:/mnt/backup/scripts/
```
Expected: three `.sh`/`.py` files + README transfer with no error.

- [ ] **Step 2: Run the deploy**

Run:
```bash
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 root@192.168.80.50 \
  'bash /mnt/backup/scripts/nas-backup/deploy.sh'
```
Expected: lines like `installed …/config-export.sh`, `created cron: …`, several `CREATE …` lines, and `Phase-1 deploy complete.` (A re-run prints `skip …`/`already present` instead — idempotent.)

- [ ] **Step 3: Verify snapshot tasks were created**

Run:
```bash
ssh root@192.168.80.50 \
  'midclt call pool.snapshottask.query | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d),\"tasks\"); [print(t[\"dataset\"], t[\"schedule\"][\"hour\"]+\"h\", \"dow=\"+t[\"schedule\"][\"dow\"], t[\"lifetime_value\"], t[\"lifetime_unit\"]) for t in d]"'
```
Expected: **16 tasks** — `data/paperless`, `data/homes`, `backup/HomeFolders`, `backup/dumps` each twice (`0,12h` + Sunday `5h dow=0`), `fast/appdata`, `fast/ix-apps`, `data/makerlab` each twice (`3h` + Sunday), `data/provisioning` + `data/media` once each. (If `data/homes` is not a ZFS dataset it is skipped with a WARN in Step 2 → 14 tasks; resolve per spec §10.)

- [ ] **Step 4: Verify the cron job exists**

Run:
```bash
ssh root@192.168.80.50 'midclt call cronjob.query "[[\"description\",\"~\",\"NAS backup\"]]"'
```
Expected: one job, `command` = `/mnt/backup/scripts/nas-backup/config-export.sh`, `schedule` 02:30 daily, `enabled: true`.

---

## Task 6: Verify a snapshot actually materialises

**Files:** none (operational).

- [ ] **Step 1: Trigger one task immediately**

Run (runs the `data/paperless` frequent task now without waiting for the schedule):
```bash
ssh root@192.168.80.50 \
  'id=$(midclt call pool.snapshottask.query "[[\"dataset\",\"=\",\"data/paperless\"],[\"schedule.hour\",\"=\",\"0,12\"]]" | python3 -c "import sys,json;print(json.load(sys.stdin)[0][\"id\"])"); echo "task id=$id"; midclt call pool.snapshottask.run "$id"; sleep 5'
```
Expected: prints `task id=<n>` and returns without error.

- [ ] **Step 2: Confirm the snapshot exists**

Run:
```bash
ssh root@192.168.80.50 "zfs list -t snapshot -o name -s creation | grep 'data/paperless@auto-' | tail -3"
```
Expected: at least one fresh `data/paperless@auto-YYYY-MM-DD_HH-MM` snapshot dated today.

- [ ] **Step 3: Verify the config-export script works**

Run:
```bash
ssh root@192.168.80.50 \
  'bash /mnt/backup/scripts/nas-backup/config-export.sh && ls -l /mnt/backup/dumps/truenas-config/'
```
Expected: `wrote /mnt/backup/dumps/truenas-config/truenas-config-<ts>.tar.gz` and a `.tar.gz` (~0.8 MB) listed, mode `600`.

---

## Task 7: Alert delivery — Email Alert Service (channel decision)

**Files:** none (operational). **Prerequisite/decision (spec §10):** confirms the alert channel. Email is the most universal native option; Slack/Telegram swap the `attributes` block.

- [ ] **Step 1: Check whether system SMTP is configured**

Run:
```bash
ssh root@192.168.80.50 'midclt call mail.config'
```
Expected: shows `fromemail`, `outgoingserver`, `port`, `user`. If `outgoingserver` is empty, configure SMTP first (creds from 1Password) via `midclt call mail.update '{"fromemail":"…","outgoingserver":"…","port":587,"security":"TLS","smtp":true,"user":"…","pass":"…"}'` before continuing.

- [ ] **Step 2: Create an Email Alert Service for backup-relevant alerts**

Run (sends WARNING-and-above alerts — pool degraded, task failures, SMART/scrub errors — to the admin address):
```bash
ssh root@192.168.80.50 \
  'midclt call alertservice.create "{\"name\":\"Email admin\",\"type\":\"Mail\",\"attributes\":{\"email\":\"admin@appsfab.org\"},\"level\":\"WARNING\",\"enabled\":true}"'
```
Expected: returns the created service object with `"type": "Mail"`, `"enabled": true`.

- [ ] **Step 2 (alt): Slack instead of Email** — if Slack is the chosen channel, skip Step 2 and run:
```bash
ssh root@192.168.80.50 \
  'midclt call alertservice.create "{\"name\":\"Slack\",\"type\":\"Slack\",\"attributes\":{\"url\":\"<incoming-webhook-url-from-1Password>\"},\"level\":\"WARNING\",\"enabled\":true}"'
```

- [ ] **Step 3: Send a test alert**

Run:
```bash
ssh root@192.168.80.50 \
  'id=$(midclt call alertservice.query "[[\"name\",\"=\",\"Email admin\"]]" | python3 -c "import sys,json;print(json.load(sys.stdin)[0][\"id\"])"); midclt call alertservice.test "$(midclt call alertservice.query "[[\"id\",\"=\",$id]]" | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin)[0]))")"'
```
Expected: returns `true`; a test message arrives at the channel. (If `alertservice.test` rejects the payload shape on this build, send a manual test from the UI: System → Alert Services → ⋯ → Send Test Alert.)

---

## Task 8: Push branch and open the PR

**Files:** none (git).

- [ ] **Step 1: Confirm the tree and log**

Run:
```bash
git -C /Users/christian/Workspace/appsfab/NAS/homelab-gitops.worktrees/nas-backup status --short --branch
git -C /Users/christian/Workspace/appsfab/NAS/homelab-gitops.worktrees/nas-backup log --oneline f1b4b08..HEAD
```
Expected: branch `docs/nas-backup-strategy`, clean tree, commits for the spec + the four Phase-1 files.

- [ ] **Step 2: Push and open the PR**

Run:
```bash
git -C /Users/christian/Workspace/appsfab/NAS/homelab-gitops.worktrees/nas-backup push -u origin docs/nas-backup-strategy
gh --repo appwerkstatt/homelab-gitops pr create \
  --base main --head docs/nas-backup-strategy \
  --title "NAS backup strategy + Phase 1 (local snapshots + config export)" \
  --body "Spec: docs/specs/2026-06-05-nas-backup-strategy-design.md. Phase-1 plan: docs/plans/2026-06-06-nas-backup-phase1.md. Adds idempotent midclt-as-code (snapshot tasks + nightly config export). No external accounts needed for Phase 1."
```
Expected: branch pushed; PR URL printed. The `validate` check runs (docs-only change → passes).

- [ ] **Step 3: Report the PR URL** to the user and stop. Do **not** auto-merge.

---

## Follow-on plans (not in this plan)

Written when their prerequisites resolve (spec §8 / §10):
- **Phase 2 — local replication.** `pool.replication` tasks `fast`/`data` → `backup/replica/…`; verify received snapshots. No external deps.
- **Phase 3 — `50-backup` stack.** New Arcane stack: `pg_dump` (keycloak, paperless) + `forgejo dump`, then `restic`→Backblaze B2 of the Tier-1 set + config-export dir. **Blocks on:** B2 account + scoped app-key + restic repo password in 1Password.
- **Phase 4 — cluster + drills.** Velero→Garage bucket `velero`; fold `velero` into the B2 restic run; first documented quarterly restore drill. **Blocks on:** Velero deployed.

---

## Self-Review notes (planning)

- **Spec coverage (Phase 1 = spec §8 step 1):** snapshot tasks (Task 1/5/6 ✓), config export (Task 2/6 ✓), alert services (Task 7 ✓). Schedules match §5.1; tiers match §3; `backup/timemachine` excluded ✓. Later phases explicitly deferred with their blockers.
- **Idempotency:** snapshot creator keys on `(dataset, hour, dow)`; cron keyed on description; `install -m` is overwrite-safe — all re-runnable for fresh-NAS recovery (the core spec principle, §0/§7).
- **No placeholders:** every command is concrete and was schema-checked against the live box (`pool.snapshottask`/`cronjob`/`alertservice` methods, `/data/freenas-v1.db` present, `python3`/`tar`/`find` present). The only intentional fill-at-execution values are secrets (SMTP/Slack creds from 1Password) and the channel choice — both flagged in Task 7.
- **Known risk:** `data/homes` may be a directory rather than a ZFS dataset; `snapshot-tasks.py` skips missing datasets with a WARN rather than failing (Task 5 Step 3 calls this out).
