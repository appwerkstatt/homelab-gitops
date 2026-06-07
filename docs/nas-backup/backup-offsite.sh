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
