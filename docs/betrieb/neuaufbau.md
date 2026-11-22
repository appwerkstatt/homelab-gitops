# Neuaufbau (Disaster Recovery)

Ziel: Aus GitHub, 1Password und Backblaze B2 ein funktionierendes NAS machen. Reihenfolge ist wichtig.

!!! info "Was man braucht"
    Zugang zu GitHub (dieses Repo), 1Password (Vault `AppsFab`, inkl. `restic-b2.env` und Datei-Secrets),
    Cloudflare-Konto, Christians Mac mit `op`.

## Fall A: Nur TrueNAS neu installiert, Pools intakt

1. TrueNAS installieren, Netzwerk wie vorher (`enp3s0` = `192.168.80.50`, `enp6s0` VLAN 40), Pools importieren.
2. **Konfiguration einspielen**: neuesten Export aus `/mnt/backup/dumps/truenas-config/` in TrueNAS hochladen
   (System → General → Manage Configuration). Das bringt u. a. den Schlüssel für den Pool `backup`, Shares, Cronjobs.
   Ohne Export: `bash /mnt/backup/scripts/nas-backup/deploy.sh` legt Snapshot-, Replikations- und Cronjobs neu an.
3. **Arcane** als TrueNAS-App installieren (App-Pool `fast`), dieses Repo als GitOps-Quelle eintragen.
4. **Stacks** anlegen und deployen, jeweils mit Env aus `scripts/render-env.sh <stack>`:
   traefik → forgejo + keycloak → oauth2-proxy → Rest (siehe [Startreihenfolge](../architektur/index.md#startreihenfolge)).
   Gitsync-Apps genauso benennen wie vorher (Slugs wie `garages3`, `registryzot`, `plane`).
5. Registry-Credentials in Arcane: `127.0.0.1:5000` mit Benutzer `pull`.
6. VM `n8n-sandbox` und Bridge `br88` prüfen (stecken in der Konfig), sonst nach
   [n8n-Sandbox](../extern/n8n-sandbox.md).
7. Prüfen: alle Probes grün, Login über `auth.appsfab.org`, Telegram-Testalarm.

## Fall B: Daten verloren, nur B2 übrig

1. Neue Pools `fast`, `data`, `backup` anlegen, Datasets nach [Speicher](../architektur/speicher.md).
2. `restic-b2.env` aus 1Password nach `/mnt/fast/appdata/_secrets/`, Daten aus B2 holen
   ([Restore aus B2](../backup/restore.md#5-aus-backblaze-b2-restic)): Dumps, Paperless, Homes, Plane-Uploads.
3. Datei-Secrets aus 1Password zurücklegen (`credentials.json`, `htpasswd`, `wipe-ssh.key`, `jwt/private.pem`).
4. Arcane und Stacks wie in Fall A, Schritt 3 bis 5.
5. **Datenbanken** einspielen, bevor die Apps zum ersten Mal schreiben: Stack starten, App-Container stoppen,
   Dump einspielen, App starten ([Dump-Restore](../backup/restore.md#4-datenbank-aus-einem-dump)).
   Keycloak: ohne Dump legt `--import-realm` den Realm aus dem JSON neu an; Benutzer und Passkeys sind dann neu
   anzulegen.
6. Forgejo aus dem `forgejo dump` zurückspielen.
7. `bash /mnt/backup/scripts/nas-backup/deploy.sh`, damit Backups wieder laufen.

**Nicht wiederherstellbar** (bewusst): Grafana-Einstellungen außerhalb des Repos, Metrik- und Log-Historie,
Garage-Objekte, Zot-Images (neu bauen), Docker-Hub-Cache.

## Danach

- Neuer Offsite-Lauf erfolgreich (`OffsiteBackupStale` still)?
- Replikation läuft (`ReplicaBackupStale` still)?
- Diese Seite mit allem ergänzen, was gefehlt hat.
