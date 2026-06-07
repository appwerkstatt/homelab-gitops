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

# 4) create the local replication tasks (idempotent)
python3 "$SELF/replication-tasks.py"

echo "Backup deploy complete (Phase 1 + 2)."
