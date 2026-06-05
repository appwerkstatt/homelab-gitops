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
    ("fast/docker/appdata", True,  "3",    (1, "WEEK"), (4, "WEEK")),
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
