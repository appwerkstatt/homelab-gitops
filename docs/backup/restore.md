# Wiederherstellung

Von schnell nach aufwendig: erst Snapshot, dann lokale Replika, dann B2.

!!! warning "Vor jedem Restore"
    Den betroffenen Stack in Arcane **stoppen**, bevor Daten oder Datenbanken überschrieben werden.
    Nie einen zweiten Stack per `docker compose up` ohne `-p <slug>` starten
    ([Konventionen](../architektur/konventionen.md#arcane-setzt-den-projektnamen)).

## 1. Einzelne Datei aus einem Snapshot

Snapshots sind unter `.zfs/snapshot` read-only lesbar:

```bash
ls /mnt/data/paperless/.zfs/snapshot/
cp -a /mnt/data/paperless/.zfs/snapshot/auto-2026-11-22_12-00/media/<pfad> /tmp/restore/
```

Bei SMB-Freigaben geht das unter Windows/macOS auch über „Vorherige Versionen“, sofern in TrueNAS aktiviert.

## 2. Ganzes Dataset zurückrollen

Nur wenn alles nach dem Snapshot verworfen werden darf:

```bash
zfs list -t snapshot -o name,creation -s creation fast/appdata/n8n | tail
zfs rollback -r fast/appdata/n8n@auto-2026-11-22_03-00     # -r löscht neuere Snapshots!
```

Sicherer ist ein Klon zum Nachsehen: `zfs clone <snap> fast/restore-tmp`, Daten kopieren, Klon zerstören.

## 3. Aus der lokalen Replika

Wenn ein Pool oder Dataset weg ist. Die Replika ist nur lesbar, solange der Pool `backup` entsperrt ist.

```bash
zfs list -r -o name,used,readonly backup/replica
zfs send backup/replica/fast/appdata@auto-<datum> | zfs recv -F fast/appdata-restore
```

Danach die Daten an ihren Ort bringen (oder das Dataset umbenennen) und den Stack starten.

## 4. Datenbank aus einem Dump

Lokale Dumps (14 Tage) liegen in `/mnt/backup/dumps/<app>/`. Beispiel Keycloak:

```bash
# Stack stoppen bis auf die DB, dann:
docker exec -i keycloak-keycloak-db-1 sh -c 'dropdb -U "$POSTGRES_USER" keycloak && createdb -U "$POSTGRES_USER" keycloak'
zstd -dc /mnt/backup/dumps/keycloak/<ts>.sql.zst | docker exec -i keycloak-keycloak-db-1 sh -c 'psql -U "$POSTGRES_USER" -d keycloak'
```

| App | DB-Container | Hinweis |
|---|---|---|
| Keycloak | `keycloak-keycloak-db-1` | |
| Paperless | `paperless-paperless-db-1` | Dokumente kommen aus `data/paperless` |
| Plane | `plane-plane-db-1` | Uploads aus `fast/appdata/plane/uploads` |
| n8n | `n8n-n8n-db-1` | Credentials nur mit dem originalen `encryption-key` lesbar |
| Forgejo | – | `forgejo dump`-Archiv (`tar.zst`), Restore nach Forgejo-Doku |

## 5. Aus Backblaze B2 (restic)

Wenn NAS und `backup`-Disk verloren sind. Braucht `restic-b2.env` (1Password) auf einem beliebigen Rechner
mit Docker:

```bash
set -a; . ./restic-b2.env; set +a
alias r='docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e B2_ACCOUNT_ID -e B2_ACCOUNT_KEY -v "$PWD/restore:/restore" restic/restic:0.18.0'
r snapshots --host nas --tag nas-offsite
r restore latest --host nas --tag nas-offsite --target /restore --include /data/dumps
```

Pfade im Repository: `/data/dumps`, `/data/paperless-media`, `/data/paperless-export`, `/data/homes`,
`/data/HomeFolders`, `/data/plane-uploads`. Die restic-Version im Befehl an die in `backup-offsite.sh` angleichen.

## 6. Komplettes NAS

Siehe [Neuaufbau (DR)](../betrieb/neuaufbau.md).

## Restore üben

Ein Restore-Test ist erst wirklich einer, wenn er geübt wurde. Vorschlag: einmal pro Quartal einen Dump aus B2
in eine Wegwerf-Postgres einspielen und eine Datei aus `paperless-media` zurückholen. Ein formaler Drill steht
noch aus ([Roadmap](../roadmap.md)).
