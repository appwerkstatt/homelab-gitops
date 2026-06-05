# NAS Backup-Strategie — Design

> Stand: 2026-06-05 · Repo: **homelab-gitops** (TrueNAS, Arcane-driven GitOps)
> Goal: Eine vollständige **3-2-1-Backup-Strategie** für das TrueNAS-Homelab — vom lokalen
> ZFS-Snapshot über eine zweite lokale Kopie bis zur verschlüsselten Offsite-Kopie in der
> Cloud — und zwar **reproduzierbar aus Git**, damit ein OS-Neuinstall sie nicht wieder mitnimmt.

---

## 0. Why this exists (and why now)

Zwei Befunde aus der Bestandsaufnahme (`NAS/nas-inventur-20260525-150407.txt`) und dem
Reinstall vom 2026-06-05:

1. **Es gibt aktuell *null* automatisierte Backups.** Keine Periodic-Snapshot-Tasks, keine
   Replication-Tasks, kein Cloud-Sync. Die alten `data/paperless@auto-…`-Snapshots beweisen,
   dass *früher* eine Snapshot-Task lief — der Reinstall hat ihre **Konfiguration** mitgenommen
   (genau wie die SMB-Shares). Es entsteht also nicht neu, was geschützt wäre.
2. **Die SMB-Shares mussten am 2026-06-05 von Hand aus dem Inventur-JSON rekonstruiert werden**
   (`nas-timemachine-share-restore`). Lehre: TrueNAS-Middleware-Config liegt **nicht in Git** und
   geht bei jedem Reinstall verloren.

Daraus folgt das Leitprinzip dieser Strategie: **Das Backup-System muss sich selbst
wiederherstellen können.** Jede native ZFS-Task wird zusätzlich als `midclt`-as-code in Git
abgelegt, die Container-Schicht ist deklarativ in `homelab-gitops`, und der nächtliche
**TrueNAS-Config-Export wird selbst offsite gesichert** — so kann ein Neuaufbau Snapshots,
Replication und Shares genauso reproduzieren, wie wir gerade das Time-Machine-Share reproduziert
haben.

## 1. Scope

**In scope:**
- **Local Copy 1** — Periodic-Snapshot-Tasks für alle relevanten Datasets (Point-in-Time gegen
  versehentliches Löschen / Ransomware / kaputtes Update).
- **Local Copy 2** — Replication-Tasks `zfs send` von `fast`/`data` (Mirror) → `backup`-Pool
  (anderes physisches Laufwerk).
- **Offsite Copy 3** — verschlüsselte, deduplizierte `restic`-Sicherung des **kleinen kritischen
  Sets** nach Backblaze B2 (100-Mbit-tauglich).
- **App-konsistente Dumps** — `pg_dump` (Keycloak, Paperless), `forgejo dump`.
- **TrueNAS-Config-Export** — nächtlich, offsite mitgesichert.
- **Cluster-State** — Velero → Garage-Bucket `velero`, Bucket offsite mitgesichert.
- **Monitoring & Verifikation** — Alerts auf Task-Fehler/Pool-Health, Dead-Man's-Switch,
  vierteljährliche Restore-Drills.
- **Reproduzierbarkeit** — native Tasks als `midclt`-Doku, Container-Layer im Repo.

**Out of scope:**
- **Pool-Redundanz** des `backup`-Pools (bleibt 6-TB-Single — bewusste Entscheidung: reiner
  Backup/Cold-Tier; Verlust trifft nur re-erzeugbare Time-Machine-Historie).
- **Bulk-Offsite** (Time Machine 1 T, Media) — bleibt lokal, geht **nicht** über die 100-Mbit-
  Leitung in die Cloud.
- **Swappable-Bay / Remote-ZFS-Replikation** — verworfen (keine Hardware/Zielsystem); Offsite =
  Cloud-only.

## 2. Prinzipien

1. **3-2-1 an reale Pools.** 3 Kopien, 2 Medien, 1 offsite — abgebildet auf `fast`/`data`-Mirror
   (Copy 1), `backup`-Single-Disk (Copy 2), Backblaze B2 (Copy 3).
2. **100-Mbit-Realität.** Cloud nur für *kleine, unersetzliche* Daten. Großes bleibt lokal.
3. **Backup-System rebuildet Backup-System.** Siehe §0 / §7.
4. **Daten getrennt von Definition** (Runbook §9.1). Persistente Daten auf eigenen Datasets;
   Compose ist Wegwerf. Backups schützen die Datasets, nicht die Container.
5. **Pets vs. Cattle.** Was aus Git/Internet reproduzierbar ist, wird *nicht* offsite gesichert,
   nur lokal gesnapshottet (Tier 3).

## 3. Datenklassifikation

| Tier | Daten | Pool | Kopien |
|------|-------|------|--------|
| **1 — unersetzlich, klein** | Keycloak-PG-Dump · Paperless-PG-Dump + `data/paperless/media` + `…/export` · Forgejo-Dump (DB + Repos) · `data/homes` · `backup/HomeFolders` · TrueNAS-Config-Export · Garage-Bucket `velero` | data/backup | **alle 3** (Snapshot + Replica + **B2**) |
| **2 — wichtig, groß** | `fast/docker/appdata` (61 G) · `fast/ix-apps` (20 G) · `data/makerlab` · `backup/timemachine` (1 T) | fast/data/backup | Snapshot + Replica (**kein B2**) |
| **3 — reproduzierbar** | `data/provisioning` (Netboot) · `data/media` · Garage-Buckets `loki`/`artifacts` · Observability-TSDB · `boot-pool` (OS) | data/fast | Snapshot, kurze Retention (**kein Offsite**) |

Anmerkungen:
- **Time Machine** bleibt bewusst lokal-only: die Laptops sind die Primärquelle; ein
  `backup`-Disk-Verlust kostet nur re-erzeugbare Historie. Kein Snapshot nötig (TM versioniert
  selbst), keine Replica (liegt bereits auf dem `backup`-Pool).
- **Redis** (Paperless-Celery-Broker) ist zustandslos → kein Backup.
- **Forgejo-Repos** sind teils *primär* auf Forgejo (z. B. `cluster`-Repo) → Tier 1, **nicht** nur
  GitHub-gespiegelt. `homelab-gitops` selbst liegt primär auf GitHub (bereits offsite).
- `data/homes`-Größe ist vor B2-Aufnahme zu verifizieren (→ §10). Bei >einigen GB nach Tier 2
  herabstufen.

## 4. Architektur / Datenfluss

```
                          ┌──────────────────────── TrueNAS (192.168.80.50) ───────────────────────┐
                          │                                                                          │
  Live-Daten (Copy 1)     │   fast (NVMe-Mirror)        data (3T-Mirror)        backup (6T-Single)   │
  + Periodic Snapshots    │   ├─ docker/appdata  ──┐    ├─ paperless    ──┐     ├─ timemachine (TM)  │
                          │   └─ ix-apps         ──┤    ├─ homes        ──┤     ├─ HomeFolders       │
                          │                        │    ├─ provisioning   │     ├─ dumps/   ◄───┐     │
                          │                        │    └─ media          │     ├─ replica/  ◄─┐│     │
                          │   Replication (Copy 2) └────┴─────────────────┴────►│ (zfs send)   ││     │
                          │                                                      │              ││     │
                          │   ┌─ Stack 50-backup (Arcane / homelab-gitops) ──────┘              ││     │
                          │   │   • cron: docker exec pg_dump (keycloak, paperless) ────────────┘│     │
                          │   │           forgejo dump                                            │     │
                          │   │   • cron: midclt call config.save  ──────────────────────────────┘     │
                          │   │   • restic backup  ──► Tier-1-Set ──┐                                   │
                          │   └─────────────────────────────────────┼───────────────────────────────── │
                          └─────────────────────────────────────────┼─────────────────────────────────┘
   Cluster (k3s) ── Velero ──► Garage-Bucket `velero` ──────────────┤
                                                                     ▼
                                          Backblaze B2  (restic, verschlüsselt+dedup, Copy 3 offsite)
                                          Keys/Repo-Passwort: 1Password
```

## 5. Komponenten im Detail

### 5.1 Native ZFS — Periodic-Snapshot-Tasks
Naming-Schema `auto-%Y-%m-%d_%H-%M` (wie Altsystem). Pro Tier:

| Tier | Frequenz | Retention |
|------|----------|-----------|
| 1 | alle 12 h + weekly | 14 daily · 8 weekly |
| 2 | daily | 7 daily · 4 weekly |
| 3 | daily | 7 daily |

`recursive=true` auf Dataset-Wurzeln, wo sinnvoll; `backup/timemachine` ausgenommen.

### 5.2 Native ZFS — Replication-Tasks (lokal, cross-disk)
`zfs send` der Tier-1+2-Datasets von `fast`/`data` → `backup/replica/<pool>/<dataset>`. Täglich,
nach den Snapshots. Das ist **Copy 2 auf anderem physischem Medium** — überlebt den Verlust einer
`fast`/`data`-Disk. (Der `backup`-Pool ist single, aber ein *drittes* physisches Laufwerk;
Tier-1-Daten leben zusätzlich auf dem Mirror (Copy 1) und in B2 (Copy 3).)

### 5.3 Stack `50-backup` (neu, homelab-gitops) — App-konsistente Dumps
Schlanker Container (Cron im Container oder Forgejo-Action-getriggert), Zugriff auf den
Docker-Socket bzw. die DB-Container:
- **Keycloak:** `docker exec … pg_dump -U … keycloak | zstd` → `/mnt/backup/dumps/keycloak/<ts>.sql.zst`
- **Paperless:** dito → `/mnt/backup/dumps/paperless/<ts>.sql.zst`
- **Forgejo:** `forgejo dump` (DB + Repos + Config) → `/mnt/backup/dumps/forgejo/<ts>.zip`
- Lokale Retention: letzte N (z. B. 14) je App; Dumps liegen auf `backup`-Pool → von Snapshot
  **und** Replica mit abgedeckt.
- **Postgres-Pin beachten:** Dump-Tool-Major == Server-Major (17) — kein 18-Bump (Incident 2026-06-05).

### 5.4 Stack `50-backup` — restic → Backblaze B2
Verschlüsselt, dedupliziert, inkrementell. Sichert **nur das Tier-1-Set**:
`/mnt/backup/dumps/**` · `data/paperless/media` + `…/export` · `data/homes` · `backup/HomeFolders`
· `/mnt/backup/dumps/truenas-config/**` · (Garage-`velero`-Bucket, sobald live).
- Täglich; `restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune`.
- **Repo-Passwort + B2-App-Keys aus 1Password**, in den Container via Arcane-Env / SOPS injiziert —
  nie im Git-Klartext.
- Volumen-Sanity: aktuell wenige hundert MB bis low-GB; tägliche Inkremente winzig → 100-Mbit ok.

### 5.5 Stack `50-backup` — TrueNAS-Config-Export
Nächtlich `midclt call config.save` (bzw. `system.general`-Config-Download-API) →
`/mnt/backup/dumps/truenas-config/<ts>.tar`. **Enthält die Middleware-DB inkl. SMB-Shares *und*
der Snapshot/Replication-Tasks selbst** → schließt die Reinstall-Wipe-Lücke. Wird von restic→B2
(§5.4) mit offsite getragen.

### 5.6 Cluster-State — Velero → Garage
Velero im Cluster sichert k8s-Ressourcen + PV-Daten (restic/kopia) in den Garage-Bucket `velero`
(S3 `http://192.168.80.50:3900` o. ä.), täglich, Retention 30 d. Der kleine `velero`-Bucket wird
ins NAS-restic→B2 (§5.4) gefaltet = Cluster-State offsite. **IaC ist bereits 3-2-1:** `cluster`-
und `homelab-gitops`-Repo auf GitHub, Secrets in 1Password. **Abhängigkeit:** Velero muss deployed
sein (Garage-Stack `21-garage` existiert; Velero ggf. noch ausstehend → Phase 4).

### 5.7 Monitoring & Verifikation
- **Alerts (TrueNAS Alert Services):** Task-Fehler (Snapshot/Replication/Cloud), Pool DEGRADED,
  SMART-Fehler, Scrub-Fehler, Dataset >80 %.
- **Dead-Man's-Switch (healthchecks.io):** der `50-backup`-Container pingt nach Erfolg; Alert wenn
  ein Lauf **ausbleibt** (nicht nur wenn er fehlschlägt). Push via ntfy.
- **Scrub + SMART:** laufen bereits (Inventur zeigt Scrubs); SMART-Long-Tests + Alerting auf allen
  4 Pools sicherstellen.
- **Restore-Drill (vierteljährlich, dokumentiert):** (1) Paperless-Dokument aus Snapshot, (2)
  Keycloak-Dump in temp-Postgres, (3) Datei aus B2 via `restic restore`, (4) Velero-Namespace-
  Restore. Das ist die **„0"** in 3-2-1-1-0 (zero errors verified).

## 6. RPO / RTO

| Tier | RPO lokal | RPO offsite | RTO |
|------|-----------|-------------|-----|
| 1 | ~12 h (Snapshot) | ~24 h (B2) | Minuten lokal / Stunden aus B2 |
| 2 | ~24 h (Snapshot+Replica) | — | Minuten–Stunden lokal |
| 3 | best-effort | — (Rebuild aus Git) | Rebuild-Zeit |

## 7. Reproduzierbarkeit (midclt-as-code)

- Jede native Snapshot-/Replication-Task wird als **dokumentierter `midclt call`** in
  `homelab-gitops/docs/nas-backup/` abgelegt (z. B. `snapshot-tasks.md`, `replication-tasks.md`) —
  reproduzierbar wie die SMB-Share-Wiederherstellung.
- Der `50-backup`-Stack ist deklarativ im Repo (Compose + Cron) → übersteht einen Reinstall nativ.
- Der nächtliche Config-Export ist die *Belt-and-Suspenders*-Ebene: selbst wenn die `midclt`-Doku
  veraltet, stellt der Export die exakte Task-Definition wieder her.

## 8. Phasen-Rollout

1. **Phase 1 (dringend):** Periodic-Snapshot-Tasks (alle Tiers) + Config-Export-Job +
   Alert-Services. Beendet sofort den „Zero-Backup"-Zustand — **ohne** Cloud-Abhängigkeit.
2. **Phase 2:** Lokale Replication-Tasks (`fast`/`data` → `backup/replica`).
3. **Phase 3:** Stack `50-backup` — DB-Dumps + restic→B2 (braucht B2-Account + 1Password-Keys).
4. **Phase 4:** Velero→Garage + `velero`-Bucket in B2 falten + erste dokumentierte Restore-Drill.

Jede Phase ist eigenständig nützlich; bei Abbruch nach Phase 1 existieren bereits valide lokale
Point-in-Time-Backups.

## 9. Sicherheit / Härtung

- restic-Repo-Passwort + B2-Keys + (künftig) Velero-S3-Keys ausschließlich in **1Password**.
- Config-Export kann Secrets enthalten → wird nur **verschlüsselt** (restic) abgelegt, nie im
  Klartext nach B2 oder Git.
- B2-Bucket mit eigenem, scoped App-Key (nur dieser Bucket, kein Master-Key).
- Konsistent mit Runbook §9.4 (SOPS/age, keine Secrets im Git-Klartext).

## 10. Offene Entscheidungen / TODO

- [ ] **Cloud-Provider bestätigen:** Backblaze B2 (Runbook-Default) — Account + scoped App-Key +
      Bucket anlegen. Alternativen (S3/Wasabi) offen.
- [ ] **Alert-Kanal bestätigen:** healthchecks.io (Dead-Man's-Switch) + ntfy (Push) — oder
      E-Mail/Slack.
- [ ] **Velero-Deploy-Status klären** (Phase 4 abhängig).
- [ ] **`data/homes`-Größe verifizieren** (Tier-1-Eignung für B2).
- [ ] **Snapshot-Frequenzen/Retention** final tunen (Defaults in §5.1).
- [ ] **`50-backup`-Trigger** festlegen: Cron-im-Container vs. Forgejo-Action vs. TrueNAS-Cron-Job.
