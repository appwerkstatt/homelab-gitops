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
