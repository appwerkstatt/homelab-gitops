# Homelab-Handbuch

Dieses Handbuch beschreibt das Homelab von AppsFab: was läuft, wie es zusammenhängt, wie man es
betreibt und wie man es nach einem Totalausfall wieder aufbaut. Es lebt im Repo
[`appwerkstatt/homelab-gitops`](https://github.com/appwerkstatt/homelab-gitops) neben dem Code,
den es beschreibt, und wird mit jedem PR mitgepflegt.

!!! abstract "Das Wichtigste in drei Sätzen"
    Ein TrueNAS-NAS (UGREEN DXP4800 Plus, 24 GB RAM, TrueNAS 25.10) betreibt alle Dienste als
    Docker-Compose-Stacks. **Arcane** deployt jeden Stack aus diesem Git-Repo, sobald `main` sich ändert;
    was nicht im Repo steht, existiert nicht. Secrets liegen nur in **1Password** (Vault `AppsFab`),
    Daten auf eigenen ZFS-Datasets mit Snapshots, lokaler Replika und Offsite-Backup.

## Schnelleinstieg

| Ich will … | Seite |
|---|---|
| verstehen, wie alles zusammenhängt | [Architektur](architektur/index.md) |
| wissen, welcher Dienst wo läuft | [Dienste](dienste/index.md) |
| eine Änderung ausrollen | [Deploy & Updates](betrieb/deploy.md) |
| einen neuen Dienst hinzufügen | [Neuen Stack anlegen](betrieb/neuer-stack.md) |
| ein Secret setzen oder rotieren | [Secrets](sicherheit/secrets.md) |
| eine Datei oder Datenbank zurückholen | [Wiederherstellung](backup/restore.md) |
| verstehen, was ein Telegram-Alarm bedeutet | [Alarme](monitoring/alerts.md) |
| etwas reparieren, das klemmt | [Fehlersuche](betrieb/fehlersuche.md) |
| das NAS komplett neu aufbauen | [Neuaufbau](betrieb/neuaufbau.md) |

## Grundprinzipien

Das Setup ist nach einer Update-Katastrophe entstanden: Docker lief am TrueNAS-System vorbei und
wurde von einem Update zerlegt. Daraus folgen vier Regeln.

1. **Kein Custom-Docker.** Container laufen über die TrueNAS-App-Engine; Arcane verwaltet die Stacks,
   ohne den Docker-Daemon umzukonfigurieren.
2. **Alles als Code.** Jeder Stack ist ein `stacks/<nn>-<name>/compose.yaml`. Auch NAS-Konfiguration,
   die nur in der TrueNAS-Datenbank lebt (Snapshot-Tasks, Cronjobs), wird von Skripten im Repo
   angelegt ([Backup-Skripte](nas-backup/README.md)).
3. **Daten getrennt.** Persistente Daten liegen auf eigenen Datasets (`/mnt/fast/appdata/<dienst>`,
   `/mnt/data/…`), niemals im Repo.
4. **Secrets in 1Password.** Das Repo enthält nur die Liste der Secrets als `op://`-Referenzen
   ([`.env.example`](https://github.com/appwerkstatt/homelab-gitops/blob/main/.env.example)).

## Wo was dokumentiert ist

- **Dieses Handbuch (`docs/`)**: Architektur, Abläufe, Runbooks. Erklärt das *Warum* und den Zusammenhang.
- **Kommentare in `compose.yaml`**: Details zu einzelnen Einstellungen, direkt am Code.
- **Stack-READMEs** (z. B. [Plane](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/14-plane/README.md),
  [Zot](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/22-harbor/README.md)): Ersteinrichtung
  und Sonderfälle eines einzelnen Stacks.
- **[`SECURITY.md`](https://github.com/appwerkstatt/homelab-gitops/blob/main/SECURITY.md)**: Security-Review
  mit behobenen und offenen Befunden.
- **`docs/specs/`, `docs/plans/`**: Entwurfs- und Umsetzungsdokumente früherer Projekte. Historisch, nicht
  in der Navigation; maßgeblich ist der aktuelle Code.

!!! tip "Doku pflegen"
    Ändert ein PR Verhalten, Hostnamen, Zeitpläne oder Abläufe, gehört die passende Seite hier in denselben
    PR. Lokal ansehen: `pip install -r docs/requirements.txt && mkdocs serve`. Die CI baut das Handbuch mit
    `--strict` und meldet kaputte Links.
