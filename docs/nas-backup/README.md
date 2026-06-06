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
