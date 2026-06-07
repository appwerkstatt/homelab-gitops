# NAS Backup — Phase 3 (Offsite: DB dumps + restic→B2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add **Copy 3 (offsite)** of 3-2-1 — app-consistent DB dumps + an encrypted, deduplicated `restic` backup of the small Tier-1 set to **Backblaze B2** — extending the Phase-1 pattern (a committed script + a TrueNAS cron). 100-Mbit-friendly: only the small critical set goes offsite.

**Architecture:** A new `docs/nas-backup/backup-offsite.sh` (run by a TrueNAS cron at 03:30) does `docker exec` DB dumps (keycloak + paperless `pg_dump`; `forgejo dump`) into `/mnt/backup/dumps/<app>/`, then runs `restic` (via `docker run --rm restic/restic`) to back up the Tier-1 set to B2. `deploy.sh` installs it + registers the cron. Secrets come from a NAS-local root-600 env file (`/mnt/fast/appdata/_secrets/restic-b2.env`, also in 1Password, covered by the encrypted `fast/appdata` replica) — sourced by the script; nothing secret in git.

**Tech Stack:** bash, Docker (`docker exec` + `docker run`), `restic` (B2 backend), `zstd`, `pg_dump` 17, `forgejo dump`, TrueNAS `cronjob` middleware.

**Spec:** [docs/specs/2026-06-05-nas-backup-strategy-design.md](../specs/2026-06-05-nas-backup-strategy-design.md) (Phase 3 = §8 step 3; §5.3–§5.5).

---

## Verified-live facts (spiked before writing)

- **keycloak** dump: `docker exec keycloak-keycloak-db-1 sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"'` — works with **no password** (postgres-image local trust), DB `keycloak`. ✓
- **paperless** dump: `docker exec paperless-paperless-db-1 sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"'`, DB `paperless`. ✓
- **forgejo** dump: `docker exec -u git forgejo-forgejo-1 forgejo dump --type tar.zst --file -` → streams a consistent `tar.zst` (db + repos + config) to **stdout**. ✓ (forgejo 15, container `forgejo-forgejo-1`, SQLite.)
- Host has `zstd`; `/mnt/backup/dumps` exists (snapshotted + replicated by Phases 1-2). The Tier-1 source paths exist (verified in Phase 1).

**Deferred to deploy (needs the B2 account):** creating the bucket + app key, writing the secrets file, and the first live `restic` run. The script/plan are exact; only the secret VALUES + a `docker run restic` pull happen at deploy.

**Tier-1 offsite set (spec §5.4):** `/mnt/backup/dumps` (DB dumps + TrueNAS config-export) · `/mnt/data/paperless/media` + `/export` · `/mnt/data/homes` · `/mnt/backup/HomeFolders`. (Bulk — Time Machine, media — stays local; cluster `velero` bucket folds in at Phase 4.)

---

## File Structure

- `docs/nas-backup/backup-offsite.sh` — **create**: the offsite job (DB dumps + restic→B2).
- `docs/nas-backup/restic-b2.env.example` — **create**: template for the NAS-local secrets file (no real values).
- `docs/nas-backup/deploy.sh` — **modify**: install `backup-offsite.sh` too (step 1 loop) + register the 03:30 cron (new step 5).
- `docs/nas-backup/README.md` — **modify**: Phase-3 section (B2 setup, secrets file, restore notes).

**Branch:** `feat/nas-backup-phase3-restic` in worktree `…/homelab-gitops.worktrees/nas-backup-phase3`. **Verification empirical**; deploy needs root SSH to `192.168.80.50` + the B2 secrets file in place.

---

## Task 1: `backup-offsite.sh` — DB dumps + restic→B2

**Files:**
- Create: `docs/nas-backup/backup-offsite.sh`

- [ ] **Step 1: Write the script**

Create `docs/nas-backup/backup-offsite.sh` with exactly this content:

```bash
#!/usr/bin/env bash
# Offsite backup (NAS backup, Phase 3): app-consistent DB dumps + restic -> Backblaze B2.
# Backs up the Tier-1 set (DB dumps + TrueNAS config-export, paperless docs, homes,
# HomeFolders) to an encrypted, deduplicated restic repo on B2 = Copy 3 (offsite) of 3-2-1.
# Run by a TrueNAS cron at 03:30 daily. Idempotent; safe to re-run.
set -euo pipefail

# --- secrets: NAS-local, root-600, NOT in git (also in 1Password; covered by the
#     encrypted fast/appdata replica). See restic-b2.env.example. ---
SECRETS=/mnt/fast/appdata/_secrets/restic-b2.env
[ -r "$SECRETS" ] || { echo "ERROR: $SECRETS not found/readable" >&2; exit 1; }
set -a; . "$SECRETS"; set +a
: "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD:?}" "${B2_ACCOUNT_ID:?}" "${B2_ACCOUNT_KEY:?}"

RESTIC_IMAGE="restic/restic:0.18.0"   # Renovate-tracked
DUMPS=/mnt/backup/dumps
ts="$(date +%Y-%m-%d_%H-%M)"

hc() { [ -n "${HC_PING_URL:-}" ] && curl -fsS -m 10 "${HC_PING_URL}${1:-}" >/dev/null 2>&1 || true; }

restic_run() {   # one-shot restic container with B2 env + the Tier-1 sources (read-only)
  docker run --rm \
    -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e B2_ACCOUNT_ID -e B2_ACCOUNT_KEY \
    -v "$DUMPS":/data/dumps:ro \
    -v /mnt/data/paperless/media:/data/paperless-media:ro \
    -v /mnt/data/paperless/export:/data/paperless-export:ro \
    -v /mnt/data/homes:/data/homes:ro \
    -v /mnt/backup/HomeFolders:/data/HomeFolders:ro \
    "$RESTIC_IMAGE" "$@"
}

hc /start
trap 'hc /fail' ERR        # ping the dead-man's-switch on any failure (if configured)

# clean stale temp dumps from a prior aborted run
find "$DUMPS" -type f -name '.*.tmp' -mtime +1 -delete 2>/dev/null || true

# --- 1) app-consistent DB dumps -> $DUMPS/<app>/<ts> (also snapshotted+replicated locally) ---
mkdir -p "$DUMPS/keycloak" "$DUMPS/paperless" "$DUMPS/forgejo"

dump_pg() {   # $1=container  $2=app  — uses the container's own POSTGRES_USER/DB (local trust)
  local tmp="$DUMPS/$2/.${ts}.sql.zst.tmp"
  docker exec "$1" sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | zstd -qc > "$tmp"
  mv "$tmp" "$DUMPS/$2/${ts}.sql.zst"
}
dump_pg keycloak-keycloak-db-1 keycloak
dump_pg paperless-paperless-db-1 paperless

# forgejo (sqlite + repos + config) — its own consistent dump, tar.zst to stdout
ftmp="$DUMPS/forgejo/.${ts}.tar.zst.tmp"
docker exec -u git forgejo-forgejo-1 forgejo dump --type tar.zst --quiet --file - > "$ftmp"
mv "$ftmp" "$DUMPS/forgejo/${ts}.tar.zst"

# local dump retention: keep 14 days (offsite retention is restic's, below)
find "$DUMPS" -type f \( -name '*.sql.zst' -o -name '*.tar.zst' \) -mtime +14 -delete

# --- 2) restic -> B2 (init the repo on first run) ---
restic_run snapshots >/dev/null 2>&1 || restic_run init
restic_run backup --host nas --tag nas-offsite \
  /data/dumps /data/paperless-media /data/paperless-export /data/homes /data/HomeFolders
restic_run forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune

hc           # success ping
echo "offsite backup complete: $ts"
```

- [ ] **Step 2: Syntax-check**

Run:
```bash
bash -n docs/nas-backup/backup-offsite.sh && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add docs/nas-backup/backup-offsite.sh
git commit -m "feat(backup): offsite DB dumps + restic->B2 (Phase 3)"
```

---

## Task 2: `restic-b2.env.example` — secrets template

**Files:**
- Create: `docs/nas-backup/restic-b2.env.example`

- [ ] **Step 1: Write the template**

Create `docs/nas-backup/restic-b2.env.example` with exactly this content:

```bash
# Phase-3 offsite secrets. Copy to the NAS as /mnt/fast/appdata/_secrets/restic-b2.env
# (root:root, chmod 600). NOT committed to git. Also store these in 1Password.
# (This path is on fast/appdata, so it's covered by the encrypted backup/replica.)
RESTIC_REPOSITORY=b2:YOUR_BUCKET_NAME:nas
RESTIC_PASSWORD=GENERATE_A_LONG_RANDOM_PASSPHRASE
B2_ACCOUNT_ID=YOUR_B2_KEY_ID
B2_ACCOUNT_KEY=YOUR_B2_APPLICATION_KEY
# optional healthchecks.io dead-man's-switch (alerts if a run is missed):
# HC_PING_URL=https://hc-ping.com/<uuid>
```

- [ ] **Step 2: Commit**

```bash
git add docs/nas-backup/restic-b2.env.example
git commit -m "docs(backup): restic/B2 secrets template (Phase 3)"
```

---

## Task 3: `deploy.sh` — install backup-offsite.sh + register the cron

**Files:**
- Modify: `docs/nas-backup/deploy.sh`

- [ ] **Step 1: Install both scripts (step 1 loop)**

Replace this block in `docs/nas-backup/deploy.sh`:

```bash
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
```

with:

```bash
# 1) install the cron scripts to a persistent path (survives an OS reinstall on boot-pool).
#    Skip the copy when deploy.sh is already running from the install dir (e.g. scp'd
#    straight there) — install/cp abort on a same-file copy.
mkdir -p "$INSTALL"
for f in config-export.sh backup-offsite.sh; do
  if [ "$SELF/$f" -ef "$INSTALL/$f" ]; then
    echo "$f already in place at $INSTALL"
  else
    install -m 755 "$SELF/$f" "$INSTALL/$f"
    echo "installed $INSTALL/$f"
  fi
done
```

- [ ] **Step 2: Add the offsite cron (new step 5)**

Replace the final block of `docs/nas-backup/deploy.sh`:

```bash
# 4) create the local replication tasks (idempotent)
python3 "$SELF/replication-tasks.py"

echo "Backup deploy complete (Phase 1 + 2)."
```

with:

```bash
# 4) create the local replication tasks (idempotent)
python3 "$SELF/replication-tasks.py"

# 5) register the offsite-backup cron (03:30) if not already present
OFFSITE_DESC="NAS backup: offsite restic to B2"
offsite_existing="$(midclt call cronjob.query "[[\"description\",\"=\",\"$OFFSITE_DESC\"]]")" \
  || { echo "ERROR: cronjob.query failed (middleware not ready?)" >&2; exit 1; }
if [ "$offsite_existing" = "[]" ]; then
  midclt call cronjob.create "{\"user\":\"root\",\"command\":\"$INSTALL/backup-offsite.sh\",\"description\":\"$OFFSITE_DESC\",\"schedule\":{\"minute\":\"30\",\"hour\":\"3\",\"dom\":\"*\",\"month\":\"*\",\"dow\":\"*\"},\"enabled\":true,\"stdout\":false,\"stderr\":true}" >/dev/null
  echo "created cron: $OFFSITE_DESC"
else
  echo "cron already present: $OFFSITE_DESC"
fi

echo "Backup deploy complete (Phase 1 + 2 + 3)."
```

- [ ] **Step 3: Syntax-check + commit**

```bash
bash -n docs/nas-backup/deploy.sh && echo OK
git add docs/nas-backup/deploy.sh
git commit -m "feat(backup): deploy.sh installs backup-offsite.sh + 03:30 cron (Phase 3)"
```

---

## Task 4: `README.md` — document Phase 3

**Files:**
- Modify: `docs/nas-backup/README.md`

- [ ] **Step 1: Append a Phase-3 section** (after the Phase-2 section, before "## Later phases"):

````markdown
## Phase 3 — offsite (restic → Backblaze B2)

`backup-offsite.sh` (TrueNAS cron, 03:30 daily) takes app-consistent dumps —
`pg_dump` of keycloak + paperless (via `docker exec`, local trust) and `forgejo dump`
(tar.zst) into `/mnt/backup/dumps/<app>/` — then runs `restic` (`docker run --rm
restic/restic`) to back up the **Tier-1 set** (`/mnt/backup/dumps` incl. the TrueNAS
config-export, `/mnt/data/paperless/{media,export}`, `/mnt/data/homes`,
`/mnt/backup/HomeFolders`) to B2. Encrypted + deduplicated; retention 14 daily / 8 weekly
/ 12 monthly. Bulk (Time Machine, media) stays local by design (100-Mbit uplink).

### One-time B2 setup
1. Create a **private B2 bucket** (e.g. `appsfab-nas-offsite`).
2. Create an **application key restricted to that bucket** (read+write). Note `keyID` + `applicationKey`.
3. Generate a long restic passphrase (`openssl rand -base64 32`); store it in 1Password.
4. On the NAS, create `/mnt/fast/appdata/_secrets/restic-b2.env` (root, `chmod 600`) from
   `restic-b2.env.example` with the real values. (Also in 1Password.)
5. Deploy: `bash /mnt/backup/scripts/nas-backup/deploy.sh` (registers the cron); first run:
   `bash /mnt/backup/scripts/nas-backup/backup-offsite.sh`.

### Restore (sketch)
```bash
# with the same env file present:
docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e B2_ACCOUNT_ID -e B2_ACCOUNT_KEY \
  -v /restore/target:/restore restic/restic:0.18.0 restore latest --target /restore
# DB: zstd -d keycloak/<ts>.sql.zst | docker exec -i keycloak-keycloak-db-1 psql -U "$POSTGRES_USER" -d keycloak
```
````

- [ ] **Step 2: Commit**

```bash
git add docs/nas-backup/README.md
git commit -m "docs(backup): document Phase-3 offsite (restic/B2)"
```

---

## Task 5: Deploy + first live B2 backup (needs the B2 secrets file)

**Files:** none (operational). **Prereq:** the B2 bucket + app key exist and `/mnt/fast/appdata/_secrets/restic-b2.env` is in place on the NAS.

- [ ] **Step 1: Copy scripts + deploy (registers the cron)**

```bash
scp -o ConnectTimeout=20 -r docs/nas-backup root@192.168.80.50:/mnt/backup/scripts/
ssh -o ConnectTimeout=20 root@192.168.80.50 'bash /mnt/backup/scripts/nas-backup/deploy.sh'
```
Expected tail includes `created cron: NAS backup: offsite restic to B2` and `Backup deploy complete (Phase 1 + 2 + 3).`

- [ ] **Step 2: Verify the restic image pulls + run the first backup**

```bash
ssh -o ConnectTimeout=20 -o ServerAliveInterval=5 root@192.168.80.50 \
  'time bash /mnt/backup/scripts/nas-backup/backup-offsite.sh'
```
Expected: dumps written under `/mnt/backup/dumps/{keycloak,paperless,forgejo}/`, restic `init` then `backup` (first run uploads the Tier-1 set — small, but over the 100-Mbit uplink), `forget --prune`, `offsite backup complete: <ts>`. (If `restic/restic:0.18.0` 404s on pull, bump to the current tag — it's Renovate-tracked.)

- [ ] **Step 3: Confirm the B2 snapshot exists**

```bash
ssh -o ConnectTimeout=20 root@192.168.80.50 \
  'set -a; . /mnt/fast/appdata/_secrets/restic-b2.env; set +a;
   docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e B2_ACCOUNT_ID -e B2_ACCOUNT_KEY restic/restic:0.18.0 snapshots --host nas'
```
Expected: at least one snapshot listed with the Tier-1 paths, host `nas`.

- [ ] **Step 4: Verify the dump files landed locally**

```bash
ssh -o ConnectTimeout=20 root@192.168.80.50 'ls -lR /mnt/backup/dumps/{keycloak,paperless,forgejo} | tail -20'
```
Expected: a `*.sql.zst` (keycloak, paperless) and a `*.tar.zst` (forgejo) dated today.

---

## Task 6: Push branch and open PR

**Files:** none (git — main agent only).

- [ ] **Step 1: Push + PR**

```bash
git -C /Users/christian/Workspace/appsfab/NAS/homelab-gitops.worktrees/nas-backup-phase3 push -u origin feat/nas-backup-phase3-restic
gh pr create --repo appwerkstatt/homelab-gitops --base main --head feat/nas-backup-phase3-restic \
  --title "NAS backup Phase 3: offsite DB dumps + restic->B2" \
  --body "Adds docs/nas-backup/backup-offsite.sh (pg_dump keycloak+paperless via docker exec, forgejo dump, then restic->Backblaze B2 of the Tier-1 set), restic-b2.env.example, deploy.sh cron (03:30), README. Secrets via a NAS-local root-600 env file (1Password). Dump commands verified live; B2 wiring done at deploy."
```

- [ ] **Step 2: Report the PR URL.** After merge: clean up the worktree + branch (confirm the commits actually landed in main).

---

## Self-Review notes (planning)

- **Spec coverage (§5.3–§5.5 / §8 step 3):** DB dumps (Task 1: keycloak/paperless `pg_dump` + `forgejo dump`), restic→B2 of the Tier-1 set incl. the config-export (Task 1), retention 14d/8w/12m, 03:30 cron (Task 3), secrets out of git (Task 2), dead-man's-switch optional hook (Task 1 `hc`). ✓
- **No placeholders:** dump commands + container names spiked live; restic CLI is standard; the only fill-at-deploy values are the B2 secrets + the image-tag pull check.
- **Idempotency:** cron keyed on description; `restic snapshots || init`; dumps overwrite per-timestamp + 14-day prune; `install -m` overwrite-safe; safe to re-run for fresh-NAS recovery.
- **Security:** no secrets in git (template only); secrets file root-600 on `fast/appdata` (encrypted replica + 1Password); restic repo encrypted; B2 app key scoped to the bucket.
- **Known caveat:** `restic/restic:0.18.0` tag is a best-effort pin (Renovate-tracked) — Task 5 Step 2 calls out bumping it if the pull 404s.
