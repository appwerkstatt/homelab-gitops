# NAS Renovate Runner — Design

> Stand: 2026-06-05 · Repo: **homelab-gitops** (TrueNAS, Arcane-driven GitOps)
> Goal: Renovate auf dem NAS-Repo **tatsächlich laufen lassen**. Die Config existiert
> bereits (`renovate.json`) — es fehlt nur ein Runner, der sie ausführt und PRs öffnet.

---

## 0. Why this exists (and why now)

Das `cluster`-Repo (Forgejo) hat Renovate seit **M5** produktiv: ein self-hosted Runner
(`.forgejo/workflows/renovate.yml`) startet stündlich das Renovate-Image und öffnet PRs für
Image-Tags + Helm-Pins, Patches mergen automatisch auf grünes CI. Das NAS-Repo hat zwar
schon eine `renovate.json`, aber **nichts führt sie aus** — keine `.github/workflows/`, kein
geplanter Container. Die Config liegt also brach: kein Dependency-Dashboard, keine PRs, die
~26 gepinnten Image-Tags in `stacks/*/compose.yaml` (traefik, keycloak, forgejo, grafana, …)
veralten unbemerkt.

Anders als beim Cluster ist das NAS-Repo auf **GitHub** (`appwerkstatt/homelab-gitops`,
privat). GitHub hat — anders als Forgejo — eine first-party Renovate-Integration. Wir hosten
trotzdem selbst (GitHub-Actions-Runner statt Mend-Cloud-App), um keinen Dritt-Cloud-Dienst
Schreibzugriff auf ein privates Repo zu geben — konsistent mit der Self-Hosting-Linie des
Homelabs.

## 1. Scope

**In scope:**
- Ein GitHub-Actions-Workflow `.github/workflows/renovate.yml`, der Renovate self-hosted auf
  GitHub-hosted Runnern fährt, authentifiziert über eine **org-eigene GitHub App**.
- Ein schlanker Validierungs-Workflow `.github/workflows/validate.yml` als **Required Check**,
  damit Patch-Automerge erst auf grün mergt (das Cluster-Verhalten, nicht „blind mergen").
- Aufräumen von `renovate.json`: toten `_chart.yaml`-Custom-Manager entfernen, Patch/Digest-
  Automerge ergänzen (cluster-style).

**Out of scope:**
- In-Cluster- / NAS-gehosteter Renovate-Runner (GitHub-hosted reicht und kostet nichts für das
  geringe Volumen) — wie beim Cluster bewusst deferred.
- Harbor, Änderungen am Arcane-Deploy-Flow, alles was SOPS-Secrets berührt (Renovate liest nur
  Image-Tags, entschlüsselt nichts).

## 2. Architektur / Datenfluss

```
            cron 03:00 UTC  +  workflow_dispatch
                       │
                       ▼
  ┌──────────────────────────────────────────────────────────┐
  │ .github/workflows/renovate.yml  (ubuntu-latest)           │
  │                                                            │
  │  1. actions/create-github-app-token@v1                     │
  │       app-id      = secrets.RENOVATE_APP_ID                │
  │       private-key = secrets.RENOVATE_APP_PRIVATE_KEY       │
  │       → 1h Installation-Token (acts as the App bot)        │
  │                                                            │
  │  2. renovatebot/github-action (pinned major)               │
  │       RENOVATE_TOKEN        = <installation token>         │
  │       RENOVATE_REPOSITORIES = appwerkstatt/homelab-gitops  │
  │       RENOVATE_PLATFORM     = github                        │
  │       liest renovate.json aus dem Repo selbst              │
  └──────────────────────────────────────────────────────────┘
                       │ öffnet PR (als App-Bot, NICHT als GITHUB_TOKEN)
                       ▼
  ┌──────────────────────────────────────────────────────────┐
  │ pull_request → .github/workflows/validate.yml  ("validate")│
  │   • renovate-config-validator                              │
  │   • docker compose -f stacks/*/compose.yaml config -q      │
  └──────────────────────────────────────────────────────────┘
                       │ Check „validate" grün
                       ▼
        Branch-Protection (required check) + „Allow auto-merge"
                       │
                       ▼
            Patch/Digest-PR mergt automatisch → Arcane redeployt
```

**Warum der App-Token den `validate`-Workflow überhaupt triggert:** GitHub unterdrückt
Folge-Workflows nur für Events, die mit dem repo-eigenen `GITHUB_TOKEN` ausgelöst wurden. Ein
**GitHub-App-Installation-Token ist nicht `GITHUB_TOKEN`** → von Renovate (mit App-Token)
geöffnete PRs lösen `pull_request`-Workflows aus. Genau deshalb ist die App-Variante der
Mehrwert gegenüber „Renovate mit GITHUB_TOKEN laufen lassen" (das würde den Gate nie triggern
und Automerge wäre tot).

## 3. Komponenten

### 3.1 GitHub App (org-owned, **manuelle Vorarbeit** — nicht automatisierbar)
- Org `appwerkstatt` → Settings → Developer settings → GitHub Apps → **New GitHub App**.
- Name z.B. `homelab-renovate`. Homepage-URL beliebig. **Webhook: aus** (kein Webhook nötig).
- **Repository permissions:**
  | Permission     | Level        | Wofür |
  |----------------|--------------|-------|
  | Contents       | Read & write | Branches/Commits für Update-PRs |
  | Pull requests  | Read & write | PRs öffnen/aktualisieren |
  | Issues         | Read & write | Dependency-Dashboard-Issue |
  | Workflows      | Read & write | `github-actions`-Manager darf Workflow-Pins bumpen |
  | Metadata       | Read (auto)  | Pflicht |
- **Install** die App **nur** auf `appwerkstatt/homelab-gitops`.
- Private Key erzeugen (lädt `.pem` herunter).
- Repo- (oder Org-)**Secrets** anlegen:
  - `RENOVATE_APP_ID` = die numerische App-ID
  - `RENOVATE_APP_PRIVATE_KEY` = kompletter Inhalt der `.pem`

### 3.2 `.github/workflows/renovate.yml`
- `on:` `schedule: '0 3 * * *'` (03:00 UTC ≈ 04–05 Uhr Berlin, immer im `after 2am and before
  6am`-Fenster der `renovate.json`, DST-sicher) + `workflow_dispatch: {}`.
- `permissions:` minimal (der Job nutzt den App-Token, nicht `GITHUB_TOKEN`).
- Steps:
  1. `actions/create-github-app-token@v1` (gepinnt) → `outputs.token`.
  2. Renovate via **`renovatebot/github-action@<major>`** (Default: idiomatischer auf GitHub,
     integriert sich sauber mit dem App-Token-Step). `docker run ghcr.io/renovatebot/renovate`
     bleibt der Fallback, falls die Action-Inputs nicht reichen.
  3. Renovate-Major **pinnen** (Hygiene; konsistent mit dem Cluster-Pin `:43`). Der Validator
     in 3.3 muss denselben Major nutzen → kein Version-Skew (M5-Lehre).
- Git-Author/Committer auf den App-Bot setzen, damit Commits sauber dem Bot zugeordnet sind.

### 3.3 `.github/workflows/validate.yml`
- `on: pull_request` (+ optional `push` auf `main`).
- Job-Name / Check-Context: **`validate`** — exakt dieser Name muss als Required Check in der
  Branch-Protection stehen (M5-Lehre: required-check-Name == reported context, sonst hängt
  Automerge ewig).
- Steps:
  - `renovate-config-validator` (prüft, dass `renovate.json` valide bleibt).
  - `for f in stacks/*/compose.yaml; do docker compose -f "$f" config -q; done` (Syntax-/Tag-
    Sanity der Compose-Stacks; `ubuntu-latest` hat Docker vorinstalliert).

### 3.4 `renovate.json` Änderungen
- **Entfernen:** der gesamte `customManagers`-Block (matcht `_chart.yaml`; im NAS-Repo gibt es
  **keine** solche Datei → toter Code). Das beseitigt zugleich das deprecated `fileMatch`.
- **Ergänzen:** packageRule für **Patch + Digest** → `automerge: true`,
  `automergeType: 'pr'`, `platformAutomerge: true`. Major bleibt auf
  `dependencyDashboardApproval` (bestehend), restliche Updates manuell.
- Die `docker-compose`- und `dockerfile`-Manager bleiben aktiv (kommen aus `config:recommended`)
  — sie lesen die `image:`-Tags der Stacks.

## 4. Manuelle Repo-Settings (einmalig, **durch den User**)
1. App erstellen + installieren + Secrets (3.1).
2. Repo → Settings → General → **„Allow auto-merge" aktivieren**.
3. Repo → Settings → Branches → Branch-Protection für `main` → **Require status checks** →
   `validate` als Pflicht.

## 5. Verifikation (Definition of Done)
- `workflow_dispatch`-Lauf von `renovate.yml` öffnet das **Dependency-Dashboard-Issue** und
  mindestens einen Update-PR (es gibt bumpbare Tags, z.B. mehrere `:v…`-Images).
- Auf einem Update-PR läuft der **`validate`-Check** und wird grün.
- Ein **Patch/Digest-PR mergt automatisch** nach grünem `validate`; ein **Major-PR** bleibt
  offen / im Dashboard zur Freigabe.
- Renovate-PRs erscheinen als **`homelab-renovate[bot]`** (App-Identität), nicht als User.

## 6. Risiken / offene Punkte
- **Automerge ohne weiteren Gate als `validate`:** `validate` prüft Config- + Compose-Syntax,
  **nicht** ob der neue Tag zur Laufzeit funktioniert. Patch/Digest-Automerge akzeptiert dieses
  Restrisiko bewusst (kleine Sprünge, Arcane-Rollback via Revert möglich). Minor/Major bleiben
  manuell.
- **GitHub Actions Minutes (privates Repo):** Volumen ist minimal (1 Renovate-Lauf/Tag +
  kurze validate-Läufe), liegt klar im Free-Tier.
- **Branch-Strategie der Umsetzung:** Arbeit in einem **eigenen Branch/Worktree ab `main`**
  (nicht auf dem aktuell ausgecheckten `chore/console-tagbump-render-seed-fix`), gemäß
  Worktree-Hygiene (eine Session ⇏ ein Checkout teilen).
