# 13-n8n

| | |
|---|---|
| **Zweck** | Workflow-Automatisierung: Tagesbericht, PR-Meldungen, Alert-Erklärer, eigene Automationen |
| **Adresse** | Editor `https://n8n.lab.appsfab.org`; Webhooks öffentlich `https://hooks.appsfab.org/webhook/…` |
| **Login** | `sso-admin@docker` (vorerst nur `lab-admins`, siehe [Rechtekonzept](../sicherheit/rechtekonzept.md)) und danach n8n-eigenes Konto (Community-Edition ohne OIDC) |
| **Daten** | `fast/appdata/n8n/{data,db}` |
| **Backup** | Tier 2 + `pg_dump` offsite |
| **Abhängig von** | Mac Studio (Ollama `:11434`, LM Studio `:1234`), VM `n8n-sandbox`, VictoriaMetrics + Loki (über `edge-n8n`) |
| **Quelle** | [`stacks/13-n8n/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/13-n8n) |

## Bausteine

- **n8n** + **n8n-db** (Postgres 17). Ausführungen werden nach 14 Tagen gelöscht.
- **searxng**: Metasuche für den n8n-Assistenten, nur im Stack-Netz.
- **Assistent (Instance AI)**: Modell über LM Studio auf dem Mac Studio (OpenAI-kompatibel), kein Cloud-Modell.
  Code führt er in der [Sandbox-VM](../extern/n8n-sandbox.md) aus.
- **Ollama-Credential**: Die Base-URL ist im Stack fest vorgegeben (`CREDENTIALS_OVERWRITE_DATA`).

## Webhooks

| Pfad | LAN (`n8n.lab`) | Internet (`hooks.appsfab.org`) |
|---|---|---|
| `/webhook/`, `/webhook-test/` | ja, ohne SSO | ja, mit Rate-Limit |
| `/webhook-waiting/` | ja | nein (404) |
| Editor, API | nur mit SSO | nein (404) |

Jeder öffentliche Webhook sichert sich selbst ab (Header-Auth oder Signaturprüfung im Webhook-Node).

## Workflows im Repo

Die JSON-Dateien in [`stacks/13-n8n/workflows/`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/13-n8n/workflows) werden **von Hand** importiert;
Arcane deployt sie nicht. Einrichtung steht im [README](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/13-n8n/workflows/README.md).

| Workflow | Was er tut |
|---|---|
| `tagesbericht.json` | 07:30 Telegram-Bericht: Alarme der letzten 24 h + Renovate-Status |
| `github-prs.json` | meldet neue PRs in `homelab-gitops` nach Telegram |
| `alert-erklaerer.json` | holt bei jedem Alarm die Logs aus Loki und lässt LM Studio erklären, Antwort als zweite Telegram-Nachricht |

## Stolperfallen

- **Encryption-Key** (`homelab-n8n/encryption-key`) nie neu erzeugen, solange die DB existiert, sonst sind
  alle gespeicherten Credentials unlesbar.
- Ist der Mac Studio aus, schlagen LLM-Nodes fehl; Workflows sollten Retry und einen Error-Workflow haben
  ([Mac-Studio-Runbook](../mac-studio-llm.md#6-plan-b-wenn-der-mac-aus-ist)).
