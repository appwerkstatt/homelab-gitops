# NAS Renovate Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Renovate actually run on the `appwerkstatt/homelab-gitops` GitHub repo — self-hosted via GitHub Actions, authenticated as an org-owned GitHub App, with a validate gate so patch/digest image bumps auto-merge only on green.

**Architecture:** A scheduled `renovate.yml` workflow mints a 1-hour GitHub App installation token (`actions/create-github-app-token`) and runs `ghcr.io/renovatebot/renovate:43` against the repo. Renovate's PRs trigger a separate `validate.yml` workflow (`renovate-config-validator` + `docker compose config`); a branch-protection required check named `validate` + repo "Allow auto-merge" let `platformAutomerge` merge patch/digest PRs on green.

**Tech Stack:** GitHub Actions (ubuntu-latest), Renovate 43 (Docker), `actions/create-github-app-token@v1`, `gh` CLI, Docker Compose.

**Spec:** [docs/specs/2026-06-05-nas-renovate-runner-design.md](../specs/2026-06-05-nas-renovate-runner-design.md)

---

## File Structure

- `renovate.json` — **modify**: drop the dead `customManagers` (`_chart.yaml`) block; replace the patch rule with a cluster-style patch/digest automerge rule.
- `.github/workflows/validate.yml` — **create**: the required `validate` check (config + compose lint). Runs on `pull_request` + `push` to `main`.
- `.github/workflows/renovate.yml` — **create**: the scheduled self-hosted Renovate runner using the App token.
- GitHub App + repo settings — **manual** (Task 4): not files, but required for Tasks 3/5 to function.

Branch for all file work: `feat/renovate-runner` (already created as a worktree off `main`). Verification is empirical (no unit-test suite in this repo).

---

## Task 1: `renovate.json` — drop dead manager, add patch/digest automerge

**Files:**
- Modify: `renovate.json`

- [ ] **Step 1: Replace the file with the cleaned-up config**

Write `renovate.json` to exactly this content (removes `customManagers`; the old `automerge:false` grouped patch rule becomes a patch/digest/pin automerge rule; `major` approval rule unchanged):

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended", ":dependencyDashboard"],
  "timezone": "Europe/Berlin",
  "schedule": ["after 2am and before 6am"],
  "packageRules": [
    {
      "description": "Major-Updates nur nach manueller Freigabe (verhindert Überraschungs-Breaks)",
      "matchUpdateTypes": ["major"],
      "dependencyDashboardApproval": true
    },
    {
      "description": "Patch + Digest automatisch mergen nach grünem validate-Check (cluster-style; Minor/Major bleiben manuell)",
      "matchUpdateTypes": ["patch", "digest", "pin", "pinDigest"],
      "automerge": true,
      "automergeType": "pr",
      "platformAutomerge": true
    }
  ]
}
```

- [ ] **Step 2: Validate the config (same validator the CI gate will use)**

Run:
```bash
npx --yes --package renovate@43 -- renovate-config-validator --strict
```
Expected output ends with:
```
 INFO: Config validated successfully against 1 file(s)
```
Exit code 0. (Confirmed during planning.)

- [ ] **Step 3: Commit**

```bash
git add renovate.json
git commit -m "feat(renovate): patch/digest automerge, drop dead _chart.yaml manager"
```

---

## Task 2: `validate.yml` — the required check (config + compose lint)

**Files:**
- Create: `.github/workflows/validate.yml`

- [ ] **Step 1: Confirm the compose lint passes locally for all stacks**

Run (Docker Compose required; substitutes unset `${VARS}` to empty with a warning but exits 0):
```bash
fail=0
for f in stacks/*/compose.yaml; do
  docker compose -f "$f" config -q || fail=1
done
echo "exit=$fail"
```
Expected: `exit=0` (all 12 stacks valid; confirmed during planning — no `env_file:`, no `${VAR:?}` mandatory syntax, no file-based `secrets:`/`configs:`).

- [ ] **Step 2: Create `.github/workflows/validate.yml`**

```yaml
# validate.yml — Required Check für Renovate-Automerge: prüft, dass renovate.json valide
# bleibt und jede Compose-Stack-Datei syntaktisch parst. Läuft auf jedem PR (also auch auf
# Renovate-PRs, weil die per GitHub-App-Token geöffnet werden -> NICHT GITHUB_TOKEN -> triggert
# Folge-Workflows). Der Job-Name "validate" IST der Status-Context, der in der Branch-
# Protection als Pflicht eingetragen wird.
name: validate

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Validate renovate.json
        run: npx --yes --package renovate@43 -- renovate-config-validator --strict

      - name: Validate compose stacks
        run: |
          fail=0
          for f in stacks/*/compose.yaml; do
            echo "::group::$f"
            docker compose -f "$f" config -q || fail=1
            echo "::endgroup::"
          done
          exit $fail
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/validate.yml
git commit -m "ci: add validate check (renovate-config-validator + compose lint)"
```

---

## Task 3: `renovate.yml` — the self-hosted runner (App auth)

**Files:**
- Create: `.github/workflows/renovate.yml`

- [ ] **Step 1: Create `.github/workflows/renovate.yml`**

```yaml
# renovate.yml — self-hosted Renovate auf GitHub-hosted Runner, authentifiziert als org-eigene
# GitHub App (kurzlebiges Installation-Token, kein PAT). Renovate klont das Repo selbst via
# GitHub-API -> kein actions/checkout nötig. Image-Tag :43 == Validator-Version in validate.yml
# (kein Version-Skew, vgl. cluster-M5). PRs erscheinen als <app-slug>[bot].
name: renovate

on:
  schedule:
    - cron: '0 3 * * *'   # 03:00 UTC ≈ 04–05 Uhr Berlin, im "after 2am and before 6am"-Fenster (DST-sicher)
  workflow_dispatch: {}

permissions: {}   # Job nutzt ausschließlich den App-Token unten, nicht GITHUB_TOKEN

jobs:
  renovate:
    runs-on: ubuntu-latest
    steps:
      - name: Mint GitHub App installation token
        id: app-token
        uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ secrets.RENOVATE_APP_ID }}
          private-key: ${{ secrets.RENOVATE_APP_PRIVATE_KEY }}

      - name: Resolve App bot identity (git author)
        id: bot
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
          APP_SLUG: ${{ steps.app-token.outputs.app-slug }}
        run: |
          uid=$(gh api "/users/${APP_SLUG}[bot]" --jq '.id')
          echo "author=${APP_SLUG}[bot] <${uid}+${APP_SLUG}[bot]@users.noreply.github.com>" >> "$GITHUB_OUTPUT"

      - name: Run Renovate
        env:
          RENOVATE_TOKEN: ${{ steps.app-token.outputs.token }}
          RENOVATE_GIT_AUTHOR: ${{ steps.bot.outputs.author }}
        run: |
          docker run --rm \
            -e RENOVATE_TOKEN \
            -e RENOVATE_GIT_AUTHOR \
            -e RENOVATE_PLATFORM=github \
            -e RENOVATE_AUTODISCOVER=false \
            -e RENOVATE_REPOSITORIES='["appwerkstatt/homelab-gitops"]' \
            -e RENOVATE_ONBOARDING=false \
            -e RENOVATE_REQUIRE_CONFIG=optional \
            -e LOG_LEVEL=info \
            ghcr.io/renovatebot/renovate:43
```

- [ ] **Step 2: Sanity-check the YAML parses**

Run:
```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/renovate.yml')); print('renovate.yml OK')"
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/validate.yml')); print('validate.yml OK')"
```
Expected: both print `OK`. (Full run is verified end-to-end in Task 5, after the App exists.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/renovate.yml
git commit -m "ci: add self-hosted Renovate runner (GitHub App auth, renovate:43)"
```

---

## Task 4: GitHub App + repo settings (MANUAL — human only)

> These steps cannot be automated by the implementing agent. They require org-owner / repo-admin
> access in the GitHub UI and produce the secrets the workflow in Task 3 depends on. Do them
> before Task 5.

- [ ] **Step 1: Create the org-owned GitHub App**

  1. `https://github.com/organizations/appwerkstatt/settings/apps` → **New GitHub App**.
  2. **GitHub App name:** `homelab-renovate` (any name; the workflow reads the slug dynamically).
  3. **Homepage URL:** the repo URL is fine.
  4. **Webhook → Active: uncheck** (no webhook needed).
  5. **Repository permissions:**
     - Contents: **Read and write**
     - Pull requests: **Read and write**
     - Issues: **Read and write** (dependency dashboard)
     - Workflows: **Read and write** (the `github-actions` manager may bump workflow pins)
     - Metadata: **Read-only** (auto)
  6. **Where can this app be installed:** Only on this account.
  7. **Create GitHub App.**

- [ ] **Step 2: Install the App on the repo only**

  App → **Install App** → install on `appwerkstatt`, **Only select repositories → `homelab-gitops`**.

- [ ] **Step 3: Generate a private key**

  App → **General → Private keys → Generate a private key** → downloads a `.pem`.

- [ ] **Step 4: Note the App ID**

  App → **General → About → App ID** (a number).

- [ ] **Step 5: Add the two repo secrets**

  `https://github.com/appwerkstatt/homelab-gitops/settings/secrets/actions` → **New repository secret**:
  - `RENOVATE_APP_ID` = the App ID number.
  - `RENOVATE_APP_PRIVATE_KEY` = the **entire** contents of the downloaded `.pem` (including the `-----BEGIN/END-----` lines).

- [ ] **Step 6: Enable repo auto-merge** (required for `platformAutomerge`)

```bash
gh api -X PATCH repos/appwerkstatt/homelab-gitops -F allow_auto_merge=true
```
Expected: JSON with `"allow_auto_merge": true`.

- [ ] **Step 7: Branch protection on `main` requiring the `validate` check**

> Do this only AFTER `validate.yml` has reached `main` (it must exist on the default branch for
> the required check to resolve). In this plan that is after the Task 1–3 PR is merged (Task 5,
> Step 2). The status context name MUST equal the job name `validate`.

```bash
gh api -X PUT repos/appwerkstatt/homelab-gitops/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "checks": [ { "context": "validate" } ] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
```
Expected: HTTP 200 with the protection object echoing `"contexts": ["validate"]`.

---

## Task 5: End-to-end verification

**Files:** none (operational verification).

- [ ] **Step 1: Push the branch and open a PR to `main`**

```bash
git push -u origin feat/renovate-runner
gh pr create --base main --head feat/renovate-runner \
  --title "Renovate runner + validate gate" \
  --body "Self-hosted Renovate (GitHub App) + validate required-check. See docs/plans/2026-06-05-nas-renovate-runner.md"
```
Expected: PR URL printed. The `validate` workflow runs on this PR (it ships in the PR head).

- [ ] **Step 2: Confirm `validate` is green on the PR, then merge**

```bash
gh pr checks --watch
```
Expected: `validate` → `pass`. Then merge:
```bash
gh pr merge --merge --delete-branch=false
```
(Now `renovate.yml`, `validate.yml`, and the new `renovate.json` are on `main`.)

- [ ] **Step 3: Apply branch protection** — run Task 4, Step 7 now (validate.yml is on `main`).

- [ ] **Step 4: Trigger Renovate on demand**

```bash
gh workflow run renovate.yml
gh run watch "$(gh run list --workflow=renovate.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
```
Expected: the run succeeds. In the logs Renovate reports it processed `appwerkstatt/homelab-gitops`.

- [ ] **Step 5: Confirm the Dependency Dashboard + at least one update PR**

```bash
gh issue list --search "Dependency Dashboard in:title" --state open
gh pr list --author "app/homelab-renovate" --state open
```
Expected: a "Dependency Dashboard" issue exists, and ≥1 update PR opened by the app bot (several `:vX.Y.Z` image tags are bumpable).

- [ ] **Step 6: Confirm patch/digest automerge on green**

Pick a **patch or digest** Renovate PR and watch it:
```bash
gh pr checks <pr-number> --watch
```
Expected: `validate` passes → the PR **auto-merges** (Renovate enabled GitHub auto-merge). A **minor/major** PR stays open / appears in the dashboard for manual approval.

- [ ] **Step 7: Confirm bot identity**

```bash
gh pr list --state all --json author,title --jq '.[] | select(.title|test("Update|chore")) | .author.login' | head
```
Expected: PR author is `homelab-renovate[bot]` (the App identity), not a human user.

---

## Self-Review notes (planner)

- **Spec coverage:** Runner (Task 3) ✓; validate gate (Task 2) ✓ + branch protection (Task 4.7); GitHub App + permissions + secrets + allow-auto-merge (Task 4) ✓; `renovate.json` edits — drop `_chart.yaml`, add patch/digest automerge (Task 1) ✓; verification incl. bot identity, dashboard, automerge-on-green, major-stays-manual (Task 5) ✓; worktree-off-main hygiene (header) ✓.
- **Version pinning:** Renovate `:43` in both the runner (Task 3) and the validator (Tasks 1 & 2) — no validator/runtime skew (cluster M5 lesson).
- **Required-check name:** job name `validate` == branch-protection context `validate` (cluster M5 lesson).
- **Empirically pre-verified during planning:** `renovate.json` passes `renovate-config-validator@43 --strict`; all 12 stacks pass `docker compose config -q` with no env set.
