# 11-paperless

| | |
|---|---|
| **Zweck** | Dokumentenarchiv mit OCR (Paperless-ngx) und KI-Suche/Tagging (paperless-ai) |
| **Adresse** | `https://docs.lab.appsfab.org`, `https://docs-ai.lab.appsfab.org` |
| **Login** | Paperless: eigenes Konto; paperless-ai: `sso-admin@docker` (nur `lab-admins`) |
| **Daten** | `data/paperless/{media,consume,export}`, `fast/appdata/paperless/{db,redis,data}`, `fast/appdata/paperless-ai` |
| **Backup** | Dokumente Tier 1 (alle 12 h) + offsite; DB Tier 2 + `pg_dump` offsite |
| **Abhängig von** | Ollama auf dem Mac Studio (`192.168.80.30:11434`) für paperless-ai |
| **Quelle** | [`stacks/11-paperless/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/11-paperless/compose.yaml) |

## Bausteine

- **paperless** + **paperless-db** (Postgres 17) + **paperless-redis** (Celery-Broker, zustandslos).
- **paperless-ai**: Modell `qwen2.5:14b`, Embeddings `nomic-embed-text` über Ollama; die RAG-Embeddings
  rechnet v4 lokal, daher `mem_limit: 2g`.
- Neue Dokumente kommen über den SMB-Eingang `data/paperless/consume`.

## Stolperfallen

- Ist der Mac Studio aus, läuft paperless-ai ins Leere; Alarm `LlmHostDown`. Paperless selbst läuft weiter.
- Postgres nicht auf 18 heben (Vorfall 2026-06-05); Renovate macht das bewusst nicht.
