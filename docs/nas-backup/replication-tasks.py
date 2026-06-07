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
    "fast/docker/appdata",
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
