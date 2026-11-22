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
    -v /mnt/fast/appdata/plane/uploads:/data/plane-uploads:ro \
    "$RESTIC_IMAGE" "$@"
}

hc /start

# --- 0) Frische der lokalen Replikas fürs Alerting (vmalert ReplicaBackupStale): Zeitpunkt des
#     neuesten Snapshots je Replika. Nicht fatal und vor restic, damit der Wert auch kommt, wenn
#     der Offsite-Teil scheitert.
TEXTFILE_DIR=/mnt/fast/appdata/node-exporter/textfile
mkdir -p "$TEXTFILE_DIR"
{
  echo '# HELP homelab_backup_last_success_timestamp_seconds Unix time of the last successful backup run.'
  echo '# TYPE homelab_backup_last_success_timestamp_seconds gauge'
  for r in data/paperless data/homes data/makerlab fast/appdata; do
    t="$(zfs list -Hp -t snapshot -o creation -s creation -d1 "backup/replica/$r" 2>/dev/null | tail -1)"
    [ -n "$t" ] && echo "homelab_backup_last_success_timestamp_seconds{backup=\"replica-${r//\//-}\"} $t"
  done
} > "$TEXTFILE_DIR/.backup-replica.prom.tmp" && mv "$TEXTFILE_DIR/.backup-replica.prom.tmp" "$TEXTFILE_DIR/backup-replica.prom" || true
trap 'hc /fail' ERR        # ping the dead-man's-switch on any failure (if configured)

# clean stale temp dumps from a prior aborted run
find "$DUMPS" -type f -name '.*.tmp' -mtime +1 -delete 2>/dev/null || true

# --- 1) app-consistent DB dumps -> $DUMPS/<app>/<ts> (also snapshotted+replicated locally) ---
mkdir -p "$DUMPS/keycloak" "$DUMPS/paperless" "$DUMPS/forgejo" "$DUMPS/plane" "$DUMPS/n8n"

dump_pg() {   # $1=container  $2=app  — uses the container's own POSTGRES_USER/DB (local trust)
  local tmp="$DUMPS/$2/.${ts}.sql.zst.tmp"
  docker exec "$1" sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | zstd -qc --rsyncable > "$tmp"
  mv "$tmp" "$DUMPS/$2/${ts}.sql.zst"
}
dump_pg keycloak-keycloak-db-1 keycloak
dump_pg paperless-paperless-db-1 paperless
# Arcane-App "plane" (stacks/14-plane); übersprungen, solange der Stack nicht läuft (sonst bricht set -e alles ab)
if docker inspect -f '{{.State.Running}}' plane-plane-db-1 2>/dev/null | grep -q true; then
  dump_pg plane-plane-db-1 plane
fi
# Arcane-App "n8n" (stacks/13-n8n): Workflows liegen auch im Repo, Credentials/Executions nur in
# der DB. Ohne N8N_ENCRYPTION_KEY (1Password homelab-n8n) sind die Credentials im Dump unlesbar.
if docker inspect -f '{{.State.Running}}' n8n-n8n-db-1 2>/dev/null | grep -q true; then
  dump_pg n8n-n8n-db-1 n8n
fi

# forgejo (sqlite + repos + config) — its own consistent dump, als unkomprimiertes tar auf
# stdout und erst hier mit zstd --rsyncable gepackt: so bleiben unveränderte Teile auch im
# komprimierten Stream byte-gleich und restic dedupliziert sie. (Mit `--type tar.zst` war
# jeder Tages-Dump für restic komplett neu -> B2 wuchs pro Nacht um die volle Dump-Größe.)
ftmp="$DUMPS/forgejo/.${ts}.tar.zst.tmp"
docker exec -u git forgejo-forgejo-1 forgejo dump --type tar --quiet --file - | zstd -qc --rsyncable > "$ftmp"
mv "$ftmp" "$DUMPS/forgejo/${ts}.tar.zst"

# local dump retention: keep 14 days (offsite retention is restic's, below)
find "$DUMPS" -type f \( -name '*.sql.zst' -o -name '*.tar.zst' \) -mtime +14 -delete

# --- 2) restic -> B2 (init the repo on first run) ---
restic_run snapshots >/dev/null 2>&1 || restic_run init
restic_run backup --host nas --tag nas-offsite \
  /data/dumps /data/paperless-media /data/paperless-export /data/homes /data/HomeFolders /data/plane-uploads
# --group-by host,tags: restic gruppiert sonst nach host+paths. Jede neue Quelle (z. B.
# plane-uploads, 2026-11) eröffnet dann eine neue Gruppe, und die alte behält ihre
# 14+8+12 Snapshots für immer.
restic_run forget --host nas --tag nas-offsite --group-by host,tags \
  --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune

# sonntags Integritätsprüfung inkl. 5 % der Daten (Rest rotiert über die Wochen). Schlägt
# sie fehl, bricht set -e ab -> kein Erfolgs-Zeitstempel -> OffsiteBackupStale.
if [ "$(date +%u)" = 7 ]; then
  restic_run check --read-data-subset=5%
fi

hc           # success ping

# Erfolg für das Alerting festhalten (node-exporter Textfile-Collector -> vmalert
# OffsiteBackupStale). Atomar via tmp+mv, damit node-exporter nie eine halbe Datei liest.
printf '# HELP homelab_backup_last_success_timestamp_seconds Unix time of the last successful backup run.\n# TYPE homelab_backup_last_success_timestamp_seconds gauge\nhomelab_backup_last_success_timestamp_seconds{backup="offsite"} %s\n' "$(date +%s)" \
  > "$TEXTFILE_DIR/.backup.prom.tmp" && mv "$TEXTFILE_DIR/.backup.prom.tmp" "$TEXTFILE_DIR/backup.prom"
echo "offsite backup complete: $ts"
