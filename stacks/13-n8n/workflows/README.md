# n8n-Workflows (Import-Vorlagen)

Arcane deployt diese Dateien nicht in n8n. Sie liegen hier zum Versionieren und werden von Hand importiert:
n8n → *Workflows → Create → ⋯ → Import from File*.

## tagesbericht.json — täglicher Alert- und Renovate-Bericht

Jeden Morgen um 7:30 kommt eine Telegram-Nachricht mit diesen Inhalten:

- **Alerts der letzten 24 h**: was gerade aktiv ist und was wieder gelöst ist, jeweils mit Dauer.
  Die Daten stammen aus der `ALERTS`-Serie, die vmalert in VictoriaMetrics schreibt
  (`http://victoriametrics:8428`, über das Netz `edge-n8n`).
- **Renovate**: der letzte Lauf, gemergte PRs (24 h), offene PRs, Majors, die auf Freigabe
  warten, Updates, die auf das Zeitfenster warten, Fehler und Repository-Probleme. Quelle ist die
  GitHub-API ohne Token, weil das Repo öffentlich ist (60 Anfragen pro Stunde, der Bericht braucht 4).

Einrichtung nach dem Import:

1. Im Node **Telegram** ein Credential *Telegram API* anlegen. Der Bot-Token steht in
   1Password `homelab-alerting/telegram-bot-token` (derselbe Bot wie bei Alertmanager).
2. Im Node **Config** `chatId` auf `homelab-alerting/telegram-chat-id` setzen. Bei Gruppen ist der
   Wert negativ.
3. Mit *Execute workflow* einmal testen, dann den Workflow auf **Active** stellen.

Uhrzeit ändern: Node **Täglich 7:30** (Cron, Zeitzone Europe/Berlin).

## github-prs.json: neue PRs nach Telegram

Bei jedem neuen PR in `appwerkstatt/homelab-gitops` kommt sofort eine Telegram-Nachricht. Das gilt auch, wenn
ein PR wieder geöffnet oder aus dem Draft-Status freigegeben wird. Drafts, Pushes und Schließen werden
ignoriert. Renovate-PRs stummschalten: im Node **Nachricht bauen** `SKIP_RENOVATE = true` setzen.

Der Node **GitHub Trigger** legt den Webhook im Repo beim Aktivieren selbst an und löscht ihn beim
Deaktivieren wieder. Die Adresse ist `https://hooks.appsfab.org/webhook/<id>/webhook`, öffentlich über
den Tunnel.

Einrichtung nach dem Import:

1. Auf GitHub einen **Fine-grained Token** anlegen (*Settings → Developer settings → Fine-grained tokens*).
   Unter *Repository access* nur `homelab-gitops` wählen, unter *Permissions* **Webhooks: Read and write**
   (Metadata: Read kommt automatisch dazu). Ablauf z. B. 1 Jahr. Den Token in 1Password unter
   `homelab-n8n/github-webhook-token` ablegen.
2. Im Node **GitHub Trigger** ein Credential *GitHub API* anlegen: User `appwerkstatt`, Access Token = der Token.
3. Im Node **Telegram** das vorhandene Telegram-Credential wählen und die `chatId` eintragen.
4. Workflow auf **Active** stellen. Unter *Repo → Settings → Webhooks* steht jetzt ein Hook mit grünem Haken
   (der erste `ping` kommt an, wird aber nicht gemeldet).

Weitere Repos: Workflow duplizieren und im Trigger das Repository ändern.

## alert-erklaerer.json: Alert-Erklärer (Loki + LM Studio → Telegram)

Bei jedem Alert mit severity warning oder critical schickt Alertmanager zusätzlich zur normalen
Telegram-Meldung einen Webhook an n8n (`http://n8n:5678/webhook/alert-erklaerer`, intern über `edge-n8n`).
Der Workflow läuft dann so:

1. Er holt die passenden Container-Logs aus Loki, ab 15 min vor Alert-Beginn. Bei cadvisor-Alerts ist das
   der Container aus dem Label `name`. Bei Probes ist es der Dienstname aus `instance`. Sonst sind es die
   Fehlerzeilen aller Container. Die Logs schickt Alloy (`20-observability`) nach Loki.
2. LM Studio auf dem Mac Studio (`prism-ml/bonsai-27b`) erklärt in drei Abschnitten, was los ist, was die
   wahrscheinliche Ursache ist und was die nächsten Schritte sind.
3. Die Antwort kommt als zweite Telegram-Nachricht mit 🧠.

Ein Alert wird höchstens alle 12 h erklärt (`dedupeHours`), auch wenn Alertmanager ihn wiederholt.
Ist LM Studio nicht erreichbar, kommt die Meldung trotzdem, nur ohne Erklärung.

Einrichtung, **vor** dem Merge des zugehörigen PRs, damit Alertmanager nicht ins Leere sendet:

1. 1Password: `op item edit homelab-alerting --vault AppsFab "n8n-webhook-token[password]=$(openssl rand -hex 32)"`
2. Workflow importieren. Im Node **Alert-Webhook** ein Credential *Header Auth* anlegen:
   Name `Authorization`, Value `Bearer <Token aus Schritt 1>`.
3. Im Node **Telegram** das Telegram-Credential wählen, im Node **Config** die `chatId` eintragen.
4. Workflow auf **Active** stellen.
5. Nach dem Merge: `scripts/render-env.sh observability` → Arcane → observability → Environment → **Recreate**.

Testen ohne echten Alert (vom NAS aus, Token einsetzen):

```bash
docker exec "$(docker ps -qf name=alertmanager)" wget -qO- --header "Authorization: Bearer <Token>" \
  --header "Content-Type: application/json" --post-data '{"alerts":[{"status":"firing","fingerprint":"test1",
  "startsAt":"'"$(date -u +%FT%TZ)"'","labels":{"alertname":"ContainerRestartLoop","severity":"warning",
  "name":"n8n"},"annotations":{"summary":"Test"}}]}' http://n8n:5678/webhook/alert-erklaerer
```
