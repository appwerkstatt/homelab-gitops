# Keycloak Realm Reconcile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `02-keycloak`'s `AppsFab-realm.json` reconcile into the live Keycloak on every
git change (not just fresh install) by adding a one-shot `keycloak-config-cli` service, and
migrate the four `CHANGE_ME_*` client secrets to env-substituted placeholders sourced from
`secrets.env`.

**Architecture:** A one-shot `keycloak-config-cli` (kcc) container is added to the existing
`stacks/02-keycloak` compose project. It waits for Keycloak via kcc's **native availability
check** (no Docker healthcheck needed), then imports `AppsFab-realm.json` with variable
substitution enabled, resolving `$(env:VAR)` placeholders from its own environment. Arcane
redeploys the stack on git change, so every push to `realm/` triggers a reconcile.

**Tech Stack:** Docker Compose (Arcane-driven GitOps on TrueNAS), Keycloak 26.5.4,
`adorsys/keycloak-config-cli:6.5.0-26.5.4`, SOPS+age for secrets.

---

## Deviations from the spec (read first)

Planning research changed four spec details. All are improvements or corrections; none change
scope. They are applied throughout this plan:

1. **No healthcheck added to the `keycloak` service.** The spec called for one so
   `depends_on: service_healthy` could gate kcc. Research found kcc's native
   `KEYCLOAK_AVAILABILITYCHECK_ENABLED=true` (timeout `120s`) polls Keycloak until ready —
   cleaner, and it avoids the awkward healthcheck workaround the Keycloak image's distroless
   base would otherwise require (no `curl`/`wget` in the image). We use availability-check and
   leave the `keycloak` service otherwise untouched. **Fulfills the spec's intent** (gate kcc
   until Keycloak is up) by a better mechanism.

2. **`.env.example` work is a canonicalization, not "add 3 vars."** The repo's client-secret
   vars are inconsistent today: consumers read `GRAFANA_OIDC_CLIENT_SECRET` (20-observability),
   `NETBOOT_OIDC_CLIENT_SECRET` (30-netboot), `OAUTH2_PROXY_CLIENT_SECRET` (03-oauth2-proxy),
   while `.env.example` also carries three **dead** `KC_CLIENT_SECRET_{GRAFANA,FORGEJO,NETBOOT}`
   vars nothing reads. Forgejo has **no** runtime env consumer (its OIDC secret is applied once
   via `forgejo admin auth add-oauth` and lives in `gitea.db`). We canonicalize to
   `<APP>_OIDC_CLIENT_SECRET` matching the real consumers, add the missing
   `FORGEJO_OIDC_CLIENT_SECRET`, and remove the dead vars. kcc references the **same** var each
   consumer uses — single source of truth, directly addressing the recurring field-label bug.

3. **Substitution enable var is `IMPORT_VARSUBSTITUTION_ENABLED`** (one token, no underscore
   between `VAR` and `SUBSTITUTION`). The spec wrote `IMPORT_VAR_SUBSTITUTION_ENABLED`.

4. **Managed-mode risk corrected.** kcc default is `import.managed.client=full` **with**
   `import.remote-state.enabled=true` (both defaults). It deletes only clients **kcc itself
   previously created** and are now absent from config — it does **not** delete clients created
   by Keycloak's native `--import-realm` or by hand. Safer than spec §4 implied; no extra
   config needed. (`RECONCILE.md` still documents the behavior.)

**Operator-execution constraint:** the plan author (Claude) cannot headless-SSH to TrueNAS
(`192.168.80.50`). Every step that runs against the live NAS/Keycloak is an explicit
**[OPERATOR ON NAS]** handoff. Steps that can be verified on the Mac from the repo are marked
**[LOCAL]**.

---

## Canonical reference values (used across tasks)

| Realm client | Secret placeholder in realm JSON | Env var (canonical) | Runtime consumer of that var |
|---|---|---|---|
| `grafana` | `$(env:GRAFANA_OIDC_CLIENT_SECRET)` | `GRAFANA_OIDC_CLIENT_SECRET` | `stacks/20-observability` Grafana |
| `forgejo` | `$(env:FORGEJO_OIDC_CLIENT_SECRET)` | `FORGEJO_OIDC_CLIENT_SECRET` | none at runtime — applied via Forgejo CLI (gitea.db) |
| `netboot-console` | `$(env:NETBOOT_OIDC_CLIENT_SECRET)` | `NETBOOT_OIDC_CLIENT_SECRET` | `stacks/30-netboot` console |
| `oauth2-proxy` | `$(env:OAUTH2_PROXY_CLIENT_SECRET)` | `OAUTH2_PROXY_CLIENT_SECRET` | `stacks/03-oauth2-proxy` |

kcc image (pinned, Renovate-trackable): **`adorsys/keycloak-config-cli:6.5.0-26.5.4`**
(tag pattern `{kcc-version}-{keycloak-version}`; matches the running `keycloak:26.5.4`).

---

## Task 1: Canonicalize client-secret vars in `.env.example`

Bring `.env.example` in line with what the real consumers read, add the missing Forgejo var,
and delete the three dead `KC_CLIENT_SECRET_*` vars. This is the single source of truth kcc and
every consumer share.

**Files:**
- Modify: `.env.example` (the `# --- Keycloak (02) ---` block at lines 19-23, the dead block at
  lines 53-56, and the existing `GRAFANA_OIDC_CLIENT_SECRET` at line 38 / `OAUTH2_PROXY_CLIENT_SECRET`
  at line 50)

- [ ] **Step 1 [LOCAL]: Replace the Keycloak (02) block** to own all four OIDC client secrets in one place.

Change the `# --- Keycloak (02) ---` block from:

```
# --- Keycloak (02) ---
KC_DB_USER=keycloak
KC_DB_PASSWORD=
KC_BOOTSTRAP_ADMIN_USERNAME=admin
KC_BOOTSTRAP_ADMIN_PASSWORD=
```

to:

```
# --- Keycloak (02) ---
KC_DB_USER=keycloak
KC_DB_PASSWORD=
KC_BOOTSTRAP_ADMIN_USERNAME=admin
KC_BOOTSTRAP_ADMIN_PASSWORD=
# OIDC client secrets — single source of truth for BOTH the realm (keycloak-config-cli
# substitutes these into AppsFab-realm.json) AND each downstream consumer below.
# Generate once per client: openssl rand -base64 32
GRAFANA_OIDC_CLIENT_SECRET=        # consumed by stacks/20-observability (Grafana)
FORGEJO_OIDC_CLIENT_SECRET=        # applied to Forgejo via `forgejo admin auth add-oauth` (gitea.db), not env
NETBOOT_OIDC_CLIENT_SECRET=        # consumed by stacks/30-netboot (console)
OAUTH2_PROXY_CLIENT_SECRET=        # consumed by stacks/03-oauth2-proxy
```

- [ ] **Step 2 [LOCAL]: Delete the now-duplicated standalone `GRAFANA_OIDC_CLIENT_SECRET` line** in the `# --- Grafana (20) ---` block (it now lives in the Keycloak block above).

Remove this line from the `# --- Grafana (20) ---` block:

```
GRAFANA_OIDC_CLIENT_SECRET=       # Keycloak-Client-Secret
```

Leave `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` in that block untouched.

- [ ] **Step 3 [LOCAL]: Delete the standalone `OAUTH2_PROXY_CLIENT_SECRET` line** from the `# --- oauth2-proxy (03, ForwardAuth) ---` block (now owned by the Keycloak block); keep `OAUTH2_PROXY_COOKIE_SECRET` there.

Change that block from:

```
# --- oauth2-proxy (03, ForwardAuth) ---
OAUTH2_PROXY_CLIENT_SECRET=        # = Keycloak-Client-Secret "oauth2-proxy"
OAUTH2_PROXY_COOKIE_SECRET=        # openssl rand -base64 32
```

to:

```
# --- oauth2-proxy (03, ForwardAuth) ---
# OAUTH2_PROXY_CLIENT_SECRET is defined in the Keycloak (02) block (shared with the realm).
OAUTH2_PROXY_COOKIE_SECRET=        # openssl rand -base64 32
```

- [ ] **Step 4 [LOCAL]: Delete the dead `KC_CLIENT_SECRET_*` block** entirely.

Remove these four lines:

```
# --- Keycloak-Client-Secrets (nach Realm-Import in Keycloak generieren) ---
KC_CLIENT_SECRET_GRAFANA=
KC_CLIENT_SECRET_FORGEJO=
KC_CLIENT_SECRET_NETBOOT=
```

- [ ] **Step 5 [LOCAL]: Verify there is exactly one definition of each canonical var and zero dead vars.**

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
grep -nE 'GRAFANA_OIDC_CLIENT_SECRET|FORGEJO_OIDC_CLIENT_SECRET|NETBOOT_OIDC_CLIENT_SECRET|OAUTH2_PROXY_CLIENT_SECRET' .env.example
echo '--- dead vars (expect no output) ---'
grep -nE 'KC_CLIENT_SECRET_' .env.example || echo 'OK: no dead KC_CLIENT_SECRET_ vars'
```
Expected: the first grep shows **exactly one** assignment line per canonical var (4 lines total, all in the Keycloak block). The second prints `OK: no dead KC_CLIENT_SECRET_ vars`.

- [ ] **Step 6 [LOCAL]: Confirm the consumers still match the canonical names** (guards against the field-label bug).

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
grep -nE 'GRAFANA_OIDC_CLIENT_SECRET' stacks/20-observability/compose.yaml
grep -nE 'NETBOOT_OIDC_CLIENT_SECRET' stacks/30-netboot/compose.yaml
grep -nE 'OAUTH2_PROXY_CLIENT_SECRET' stacks/03-oauth2-proxy/compose.yaml
```
Expected: each grep matches (the consumer reads exactly the canonical var name now documented in `.env.example`).

- [ ] **Step 7 [LOCAL]: Commit.**

```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
git add .env.example
git commit -m "chore(02-keycloak): canonicalize OIDC client-secret env vars

Consolidate the four client secrets into the Keycloak (02) block under their
<APP>_OIDC_CLIENT_SECRET names — the same vars the real consumers read. Remove
the dead KC_CLIENT_SECRET_* duplicates nothing consumed. Single source of truth
for the realm (via keycloak-config-cli) and each downstream stack."
```

---

## Task 2: Migrate realm client secrets to `$(env:...)` placeholders

Replace the four literal `CHANGE_ME_*` secrets in `AppsFab-realm.json` with kcc env
placeholders, using the canonical var names from Task 1. Nothing else in the realm changes.

**Files:**
- Modify: `stacks/02-keycloak/realm/AppsFab-realm.json` (the four `"secret": "CHANGE_ME_*"` lines)

- [ ] **Step 1 [LOCAL]: Replace each `CHANGE_ME_*` secret** with its canonical placeholder.

Make these four exact edits in `stacks/02-keycloak/realm/AppsFab-realm.json`:

| Find | Replace with |
|---|---|
| `"secret": "CHANGE_ME_grafana",` | `"secret": "$(env:GRAFANA_OIDC_CLIENT_SECRET)",` |
| `"secret": "CHANGE_ME_forgejo",` | `"secret": "$(env:FORGEJO_OIDC_CLIENT_SECRET)",` |
| `"secret": "CHANGE_ME_netboot",` | `"secret": "$(env:NETBOOT_OIDC_CLIENT_SECRET)",` |
| `"secret": "CHANGE_ME_oauth2proxy",` | `"secret": "$(env:OAUTH2_PROXY_CLIENT_SECRET)",` |

- [ ] **Step 2 [LOCAL]: Verify the JSON is still well-formed.**

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
python3 -m json.tool stacks/02-keycloak/realm/AppsFab-realm.json > /dev/null && echo 'OK: valid JSON'
```
Expected: `OK: valid JSON` (no traceback).

- [ ] **Step 3 [LOCAL]: Verify no `CHANGE_ME` remains and all four placeholders are present.**

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
echo '--- CHANGE_ME (expect none) ---'
grep -n 'CHANGE_ME' stacks/02-keycloak/realm/AppsFab-realm.json || echo 'OK: no CHANGE_ME left'
echo '--- placeholders (expect 4) ---'
grep -cE '\$\(env:(GRAFANA|FORGEJO|NETBOOT|OAUTH2_PROXY)_[A-Z_]*CLIENT_SECRET\)' stacks/02-keycloak/realm/AppsFab-realm.json
```
Expected: `OK: no CHANGE_ME left`, then `4`.

- [ ] **Step 4 [LOCAL]: Verify each placeholder's var name exactly matches a var defined in `.env.example`** (the bug-class guard, cross-file).

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
for v in GRAFANA_OIDC_CLIENT_SECRET FORGEJO_OIDC_CLIENT_SECRET NETBOOT_OIDC_CLIENT_SECRET OAUTH2_PROXY_CLIENT_SECRET; do
  grep -q "\$(env:$v)" stacks/02-keycloak/realm/AppsFab-realm.json \
    && grep -qE "^$v=" .env.example \
    && echo "OK: $v matches in realm + .env.example" \
    || echo "MISMATCH: $v"
done
```
Expected: four `OK:` lines, no `MISMATCH`.

- [ ] **Step 5 [LOCAL]: Commit.**

```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
git add stacks/02-keycloak/realm/AppsFab-realm.json
git commit -m "feat(02-keycloak): realm client secrets via \$(env:...) placeholders

Replace the four CHANGE_ME_* literals with keycloak-config-cli env placeholders
using the canonical <APP>_OIDC_CLIENT_SECRET names. The realm JSON now contains
only references; real values stay in secrets.env."
```

---

## Task 3: Add the `keycloak-config-cli` one-shot service to the stack

Add kcc as a third service that waits for Keycloak (native availability check), imports the
realm with substitution enabled, and exits. No change to the `keycloak` or `keycloak-db`
services.

**Files:**
- Modify: `stacks/02-keycloak/compose.yaml` (append a service; no edits to existing services)

- [ ] **Step 1 [LOCAL]: Add the `keycloak-config-cli` service.** Insert this block after the `keycloak:` service (before the top-level `networks:` key), keeping two-space indentation under `services:`:

```yaml
  # Realm-Reconcile: applies realm/AppsFab-realm.json to the running Keycloak on every
  # (re)deploy, then exits. Complements --import-realm (which only seeds an empty DB).
  # One-shot: restart "no". Waits for Keycloak via kcc's own availability check, so the
  # keycloak service needs no healthcheck (its image is distroless — no curl/wget).
  #
  # Realm placeholders use kcc's DEFAULT substitution syntax $(env:VAR) — prefix "$(",
  # suffix ")" — which deliberately avoids Keycloak's own ${...} placeholders. We rely on
  # the default (the image tag is pinned, so the default is fixed) rather than setting
  # IMPORT_VARSUBSTITUTION_PREFIX/SUFFIX here, because "$(" in a compose value would be
  # mangled by Compose's own $-interpolation.
  keycloak-config-cli:
    image: adorsys/keycloak-config-cli:6.5.0-26.5.4   # tag = {kcc-version}-{keycloak-version}; Renovate-tracked
    depends_on:
      keycloak:
        condition: service_started
    environment:
      KEYCLOAK_URL: http://keycloak:8080
      KEYCLOAK_USER: ${KC_BOOTSTRAP_ADMIN_USERNAME}
      KEYCLOAK_PASSWORD: ${KC_BOOTSTRAP_ADMIN_PASSWORD}
      KEYCLOAK_AVAILABILITYCHECK_ENABLED: "true"     # poll Keycloak until ready before importing
      KEYCLOAK_AVAILABILITYCHECK_TIMEOUT: 120s
      IMPORT_FILES_LOCATIONS: /config/AppsFab-realm.json
      IMPORT_VARSUBSTITUTION_ENABLED: "true"         # enable $(env:VAR) substitution (default prefix/suffix)
      # Bump on every realm/ change. A changed env value forces Compose to recreate this
      # one-shot (so it re-runs), AND touching compose.yaml guarantees Arcane redeploys the
      # stack (a realm-only file edit alone may not trigger either). See RECONCILE.md.
      KCC_REALM_REV: "1"
      # OIDC client secrets — resolved into the realm by $(env:...). Same vars the consumers read.
      GRAFANA_OIDC_CLIENT_SECRET: ${GRAFANA_OIDC_CLIENT_SECRET}
      FORGEJO_OIDC_CLIENT_SECRET: ${FORGEJO_OIDC_CLIENT_SECRET}
      NETBOOT_OIDC_CLIENT_SECRET: ${NETBOOT_OIDC_CLIENT_SECRET}
      OAUTH2_PROXY_CLIENT_SECRET: ${OAUTH2_PROXY_CLIENT_SECRET}
    volumes:
      - ./realm:/config:ro
    networks: [kc-internal]
    restart: "no"
    mem_limit: 256m
```

> **Note on `KCC_REALM_REV`:** kcc ignores this variable — it exists purely to make realm
> reconciles deterministic. Bumping it changes the kcc container's config (Compose recreates
> and re-runs the one-shot) and changes `compose.yaml` (Arcane definitely redeploys). Without
> it, a realm-only file edit may not re-run kcc, because Compose does not recreate an unchanged
> exited one-shot and does not hash bind-mounted file contents.

- [ ] **Step 2 [LOCAL]: Verify the compose YAML parses** (structure only; full interpolation needs the NAS env).

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
python3 -c "
import yaml
d = yaml.safe_load(open('stacks/02-keycloak/compose.yaml'))
k = d['services']['keycloak-config-cli']
env = k['environment']
assert k['restart'] == 'no', 'not one-shot'
assert k['volumes'] == ['./realm:/config:ro'], 'realm not mounted ro'
assert env['IMPORT_VARSUBSTITUTION_ENABLED'] == 'true', 'substitution not enabled'
assert 'KCC_REALM_REV' in env, 'rev lever missing'
assert 'IMPORT_VARSUBSTITUTION_PREFIX' not in env, 'fragile prefix var present (relies on default)'
for v in ['GRAFANA_OIDC_CLIENT_SECRET','FORGEJO_OIDC_CLIENT_SECRET','NETBOOT_OIDC_CLIENT_SECRET','OAUTH2_PROXY_CLIENT_SECRET']:
    assert v in env, f'{v} not passed to kcc'
print('OK: kcc service one-shot, realm ro-mounted, substitution on, rev lever present, 4 secrets passed, no fragile prefix')
"
```
Expected: `OK: kcc service one-shot, realm ro-mounted, substitution on, rev lever present, 4 secrets passed, no fragile prefix`.

- [ ] **Step 3 [LOCAL]: Confirm the existing `keycloak` service was NOT modified** (still has `--import-realm`, no healthcheck added).

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
grep -nE '\-\-import-realm' stacks/02-keycloak/compose.yaml && echo 'OK: --import-realm retained'
python3 -c "import yaml; d=yaml.safe_load(open('stacks/02-keycloak/compose.yaml')); assert 'healthcheck' not in d['services']['keycloak'], 'unexpected healthcheck on keycloak'; print('OK: keycloak service unchanged (no healthcheck)')"
```
Expected: the `--import-realm` line prints + `OK: --import-realm retained`, then `OK: keycloak service unchanged (no healthcheck)`.

- [ ] **Step 4 [LOCAL]: Commit.**

```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
git add stacks/02-keycloak/compose.yaml
git commit -m "feat(02-keycloak): add keycloak-config-cli one-shot reconcile service

Applies AppsFab-realm.json to the running Keycloak on every (re)deploy with
\$(env:...) substitution, then exits. Waits via kcc's native availability check
(KEYCLOAK_AVAILABILITYCHECK_ENABLED) so the distroless keycloak image needs no
healthcheck. Pinned to 6.5.0-26.5.4 to match Keycloak 26.5.4."
```

---

## Task 4: Write the migration + operations note `RECONCILE.md`

A focused runbook: the one-time secret-capture migration (so the live secrets match
`secrets.env` before kcc first runs), the gate-test commands, managed-mode behavior, the
Forgejo wrinkle, and rollback.

**Files:**
- Create: `stacks/02-keycloak/RECONCILE.md`

- [ ] **Step 1 [LOCAL]: Create `stacks/02-keycloak/RECONCILE.md`** with this content:

````markdown
# Realm Reconcile (keycloak-config-cli)

`AppsFab-realm.json` is applied to the **running** Keycloak by the one-shot
`keycloak-config-cli` (kcc) service in `compose.yaml`, on every Arcane (re)deploy of this
stack. This is what makes the realm genuine config-as-code. `--import-realm` on the `keycloak`
service still seeds an **empty** DB (disaster recovery); kcc owns every change after that.

## One-time migration (do this once, before the first kcc run)

The four client secrets used to be `CHANGE_ME_*` placeholders rotated by hand in the Keycloak
UI. The live values must be captured into `secrets.env` so kcc reconciles to the **same**
secret each downstream app already uses — otherwise kcc would overwrite the live secret with an
empty value and break those apps' logins.

1. Read each current client secret from the running Keycloak (on the NAS):
   ```bash
   docker exec keycloak-keycloak-1 \
     /opt/keycloak/bin/kcadm.sh config credentials \
     --server http://localhost:8080 --realm master \
     --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"
   for c in grafana forgejo netboot-console oauth2-proxy; do
     id=$(docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh get clients -r AppsFab \
            -q clientId=$c --fields id --format csv --noquotes)
     echo -n "$c: "
     docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh get clients/$id/client-secret \
       -r AppsFab --fields value --format csv --noquotes
   done
   ```
2. Put those four values into `secrets.env` under the canonical names
   (`GRAFANA_OIDC_CLIENT_SECRET`, `FORGEJO_OIDC_CLIENT_SECRET`, `NETBOOT_OIDC_CLIENT_SECRET`,
   `OAUTH2_PROXY_CLIENT_SECRET`), then re-encrypt:
   ```bash
   cp secrets.env secrets.enc.env && sops -e -i secrets.enc.env && rm -f secrets.env
   ```
   (If you instead manage these in Arcane's environment, set them there with the same names.)

> **Forgejo wrinkle:** Forgejo's OIDC secret is **not** read from env at runtime — it was applied
> once via `forgejo admin auth add-oauth ... --secret '<value>'` and lives in `gitea.db`. Use the
> **same** `FORGEJO_OIDC_CLIENT_SECRET` value there. To rotate it later, update both `secrets.env`
> (for kcc → realm) **and** re-run Forgejo's `update-oauth` with the new value.

## How a change reconciles

**Every realm change is two edits in one commit:** the `realm/AppsFab-realm.json` change itself,
**and** a bump of `KCC_REALM_REV` in `compose.yaml` (`"1"` → `"2"` → …). Then commit → push →
Arcane redeploys → the `keycloak-config-cli` container re-runs, waits for Keycloak, applies the
realm, exits `0`.

> **Why the rev bump is required.** A realm-only file edit may not reconcile on its own: Compose
> does not recreate an unchanged exited one-shot, and does not hash bind-mounted file contents,
> so kcc would not re-run; and depending on Arcane's watch scope, a `realm/`-only change might not
> even trigger a redeploy. Bumping `KCC_REALM_REV` solves both — it changes the kcc container
> config (Compose recreates → kcc re-runs) and changes `compose.yaml` (Arcane definitely
> redeploys). kcc itself ignores the variable.

## Managed mode (what kcc will and won't delete)

Defaults are `import.managed.client=full` **with** `import.remote-state.enabled=true`. kcc
deletes only resources **it previously created** that are now absent from the realm JSON. It
does **not** touch the `master` realm, the bootstrap admin, or clients created outside kcc
(e.g. by `--import-realm` or by hand). Net effect for us: the realm JSON is authoritative for
clients kcc manages; a client you add by hand and never commit is left alone, but should be
committed to avoid drift.

## Gate tests (run on the NAS after deploy)

```bash
# kcadm login (reused below)
docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"

# G1 reconcile: change displayName in the JSON, redeploy, then:
docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh get realms/AppsFab --fields displayName

# G2 no placeholders: each client's live secret equals secrets.env (spot-check grafana)
gid=$(docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh get clients -r AppsFab \
        -q clientId=grafana --fields id --format csv --noquotes)
docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh get clients/$gid/client-secret \
  -r AppsFab --fields value --format csv --noquotes   # must equal $GRAFANA_OIDC_CLIENT_SECRET

# G4 idempotency: inspect the one-shot container's logs/exit on two consecutive redeploys
docker logs keycloak-keycloak-config-cli-1 2>&1 | tail -20   # expect "updated"/"unchanged", no "created", exit 0
```

`G3 reconstitution` (destructive): `kcadm.sh delete realms/AppsFab` → redeploy stack → realm
returns complete; one OIDC login (e.g. Grafana) succeeds.

## Rollback

Comment out the `keycloak-config-cli` service in `compose.yaml` and redeploy. The realm in the
DB is untouched; you simply stop reconciling. (The literal `$(env:...)` placeholders only ever
exist in git, never in the DB, so there is nothing to clean up.)
````

- [ ] **Step 2 [LOCAL]: Verify the file exists and references all four canonical vars.**

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
test -f stacks/02-keycloak/RECONCILE.md && echo 'OK: file exists'
for v in GRAFANA_OIDC_CLIENT_SECRET FORGEJO_OIDC_CLIENT_SECRET NETBOOT_OIDC_CLIENT_SECRET OAUTH2_PROXY_CLIENT_SECRET; do
  grep -q "$v" stacks/02-keycloak/RECONCILE.md && echo "OK: $v referenced" || echo "MISSING: $v"
done
```
Expected: `OK: file exists` then four `OK: ... referenced`.

- [ ] **Step 3 [LOCAL]: Commit.**

```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
git add stacks/02-keycloak/RECONCILE.md
git commit -m "docs(02-keycloak): RECONCILE.md — migration, gate tests, managed-mode, rollback"
```

---

## Task 5: Update `README.md` stacks table + bootstrap note

**Files:**
- Modify: `README.md` (the `02-keycloak` row of the Stacks table; one line in the bootstrap-order prose)

- [ ] **Step 1 [LOCAL]: Update the `02-keycloak` table row** to note the reconcile mechanism.

Change:
```
| `02-keycloak` | Keycloak 26.5.4 + Postgres 17.8 (Realm-as-Code, Passkeys) | `fast/appdata/keycloak` |
```
to:
```
| `02-keycloak` | Keycloak 26.5.4 + Postgres 17.8 (Realm-as-Code via keycloak-config-cli, Passkeys) | `fast/appdata/keycloak` |
```

- [ ] **Step 2 [LOCAL]: Add a one-line note** to the bootstrap-order section, right after the `01-forgejo` + `02-keycloak` step. Find the line:

```
3. **01-forgejo** + **02-keycloak** — danach kann GitHub optional nach Forgejo gespiegelt werden (GitHub bleibt die Wahrheit).
```
and add immediately below it (same list indentation):
```
   - Realm-Änderungen reconcilen über `keycloak-config-cli` bei jedem Redeploy — siehe `stacks/02-keycloak/RECONCILE.md` (inkl. einmaliger Secret-Migration).
```

- [ ] **Step 3 [LOCAL]: Verify both edits landed.**

Run:
```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
grep -n 'keycloak-config-cli' README.md
```
Expected: two matching lines (the table row + the bootstrap note).

- [ ] **Step 4 [LOCAL]: Commit.**

```bash
cd ~/Workspace/appsfab/NAS/homelab-gitops
git add README.md
git commit -m "docs(readme): note keycloak-config-cli realm reconcile for 02-keycloak"
```

---

## Task 6: Deploy and verify the gate [OPERATOR ON NAS]

Everything above is repo-only and verified on the Mac. This task runs against the live NAS and
**must be performed by the operator** (no headless SSH from the Mac). The plan author hands off
here and waits for results.

**Pre-req:** the four canonical secrets are populated in `secrets.env` (or Arcane env) per
`RECONCILE.md` → "One-time migration". Do that **before** the first kcc run.

- [ ] **Step 1 [OPERATOR ON NAS]: Pull/verify the kcc image tag exists** (sanity before deploy):
  ```bash
  docker pull adorsys/keycloak-config-cli:6.5.0-26.5.4
  ```
  Expected: image pulls. If the tag is missing, pick the nearest `*-26.5.4` or `latest-26` tag
  from Docker Hub and update `compose.yaml` (note it back to the plan author).

- [ ] **Step 2 [OPERATOR ON NAS]: Merge to `main` and let Arcane deploy** (or trigger redeploy of `02-keycloak`). Then capture the kcc container's logs:
  ```bash
  docker logs keycloak-keycloak-config-cli-1 2>&1 | tail -30
  ```
  Expected: availability check passes, realm import runs, four clients reconciled, exit `0`.

- [ ] **Step 3 [OPERATOR ON NAS]: Gate G2 — live secrets equal `secrets.env`.** Run the G2 block
  from `RECONCILE.md` for at least `grafana` and `oauth2-proxy`. Expected: the printed
  `client-secret` value equals the corresponding `*_CLIENT_SECRET` in `secrets.env`.

- [ ] **Step 4 [OPERATOR ON NAS]: Gate G1 — reconcile reaches the realm via the rev-bump workflow.**
  Edit `displayName` in `realm/AppsFab-realm.json` **and** bump `KCC_REALM_REV` in `compose.yaml`
  (`"1"` → `"2"`) in the **same** commit, push, wait for Arcane, then:
  ```bash
  docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master \
    --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"
  docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh get realms/AppsFab --fields displayName
  ```
  Expected: the new `displayName`. **If unchanged**, the kcc container did not re-run — check
  `docker ps -a` for `keycloak-keycloak-config-cli-1` and confirm Arcane recreated it on this
  deploy; note findings back to the plan author. Revert the `displayName` test change afterward
  (and bump the rev again).

- [ ] **Step 5 [OPERATOR ON NAS]: Gate G4 — idempotency.** Redeploy once more without changes;
  confirm the kcc logs show `updated`/`unchanged` (never `created`), exit `0`, no deletions.

- [ ] **Step 6 [OPERATOR ON NAS]: Gate G3 — reconstitution (optional, destructive; do when you can
  afford a brief Keycloak blip).** `kcadm.sh delete realms/AppsFab` → redeploy stack → confirm the
  realm returns complete and one OIDC login (e.g. Grafana on the NAS) works end-to-end.

- [ ] **Step 7 [OPERATOR → PLAN AUTHOR]: Report gate results.** Paste the kcc logs + the G1/G2/G4
  outputs. The plan author records the outcome, fixes anything red (per
  `superpowers:systematic-debugging`), and only then considers the milestone done.

---

## Task 7: Finish the branch

- [ ] **Step 1 [LOCAL]: Confirm all repo-side commits are present and the tree is clean.**
  ```bash
  cd ~/Workspace/appsfab/NAS/homelab-gitops
  git log --oneline -7
  git status --short   # expect empty
  ```
  Expected: Task 1-5 commits (plus the earlier spec commit) on `spec/keycloak-realm-reconcile`; clean tree.

- [ ] **Step 2: Integrate per `superpowers:finishing-a-development-branch`.** This repo deploys
  from `main` via Arcane, so merging to `main` triggers the live deploy in Task 6 — coordinate the
  merge timing with the operator (don't merge until they're ready to run the migration + gate).
  Open a PR on `appwerkstatt/homelab-gitops` or fast-forward `main`, per the user's preference.

---

## Self-review notes (author)

- **Spec coverage:** §1 in-scope items 1-5 → Tasks 3, 2, 1, 4, 5 respectively. §1 gate G1-G4 →
  Task 6 Steps 4/3/6/5 + `RECONCILE.md`. §4 decisions (kcc complements import-realm; managed
  mode; var substitution; image pin) → Task 3 + Deviations 1/4 + `RECONCILE.md`. §5 risks →
  `RECONCILE.md` (delete-drift, Arcane trigger, secret typo via G2, import/kcc sequence). The
  spec's "add a healthcheck" sub-item is intentionally replaced (Deviation 1) — intent preserved.
- **Placeholders:** none — every step has exact paths, full content, and concrete commands with
  expected output. The `$(env:...)` and `# realm: rev N` strings are intentional literals.
- **Type/name consistency:** the four canonical var names are identical across Tasks 1, 2, 3, 4
  and the consumers (verified by Task 1 Step 6 + Task 2 Step 4). Image tag `6.5.0-26.5.4` and
  container names `keycloak-keycloak-1` / `keycloak-keycloak-config-cli-1` (compose project
  `name: keycloak`) are consistent across Tasks 3, 4, 6.
