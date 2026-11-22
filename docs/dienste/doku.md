# 15-doku

| | |
|---|---|
| **Zweck** | Dieses Handbuch als Website mit Suche und Diagrammen |
| **Adresse** | `https://doku.lab.appsfab.org` (nur LAN) |
| **Login** | `sso@docker` |
| **Daten** | keine; der Build liegt im Docker-Volume `doku-site` |
| **Backup** | nicht nötig, die Quelle ist dieses Repo |
| **Quelle** | [`stacks/15-doku/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/15-doku) |

## So funktioniert es

- **doku-builder** (`squidfunk/mkdocs-material`) klont `main` von GitHub und prüft alle 5 Minuten, ob es einen
  neuen Commit gibt. Wenn ja, baut er die Seite in ein neues Verzeichnis und biegt den Symlink `current` um.
  Scheitert ein Build, bleibt die alte Seite stehen.
- **doku-web** (nginx) liefert `/site/current` aus; `/healthz` für die blackbox-Probe.

Ein Merge in `main` ist also nach spätestens etwa 5 Minuten online, ohne dass Arcane etwas tun muss.

## Doku schreiben

```bash
python3 -m venv .venv && .venv/bin/pip install -r docs/requirements.txt
.venv/bin/mkdocs serve      # http://127.0.0.1:8000, lädt bei jeder Änderung neu
```

- Neue Seite: Datei unter `docs/` anlegen und in `nav:` in `mkdocs.yml` eintragen.
- Links auf Code außerhalb von `docs/` als volle GitHub-URL, sonst findet MkDocs sie nicht.
- Diagramme als `mermaid`-Codeblock.
- Die CI (`validate`) baut mit `--strict`: kaputte interne Links oder Anker lassen sie scheitern.

## Stolperfallen

- Ein Build-Fehler steht nur im Log von `doku-builder` (`build of <rev> failed`). Die CI fängt ihn vorher ab.
- `docs/requirements.txt` (CI) und das Image im `compose.yaml` müssen dieselbe mkdocs-material-Version haben;
  Renovate hebt beide gemeinsam, die CI prüft es.
