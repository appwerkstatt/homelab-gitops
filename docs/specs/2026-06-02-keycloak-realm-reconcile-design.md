# Keycloak Realm Reconcile — Design

> Stand: 2026-06-02 · Repo: **homelab-gitops** (TrueNAS, Arcane-driven GitOps)
> Goal: make `02-keycloak`'s `AppsFab-realm.json` reconcile on **every** change — not just
> on a fresh install — so the realm is genuinely config-as-code and OIDC client secrets stop
> living as `CHANGE_ME_*` placeholders rotated by hand in the UI.

---

## 0. Why this exists (and why now)

This is a **NAS-side prerequisite** for the cluster-side milestone **M4a — SSO** (in the
separate `cluster` repo, `docs/superpowers/specs/`). M4a wants to add OIDC clients for the Pi
cluster's ArgoCD, Grafana, and a cluster oauth2-proxy. That only works cleanly if adding a
client to the realm is a git-commit-and-reconcile operation. Today it is **not**:

- `02-keycloak`'s `keycloak` service imports `realm/AppsFab-realm.json` **only via
  `--import-realm`, which runs solely when the realm does not yet exist** (fresh DB). On every
  subsequent boot the import is skipped — so a realm edit committed to git never reaches the
  running Keycloak.
- The four existing clients (`grafana`, `forgejo`, `netboot-console`, `oauth2-proxy`) carry
  literal `"secret": "CHANGE_ME_*"` values. The README's standing instruction is to rotate
  these **manually in the Keycloak UI** after import — i.e. the live secret diverges from git
  by design, and the only source of truth for the real value is "whatever is in the DB".

The result is a realm that drifts from its git definition the moment it is first used. M4a
would inherit and compound that drift. This sub-milestone fixes the mechanism first, on a
small, NAS-local surface, before any cluster client depends on it.

**Scope boundary:** this milestone adds the reconcile *mechanism* and migrates the *four
existing* clients onto it. It deliberately adds **no new (cluster) clients** — those are M4a.

---

## 1. Scope & gate

### In scope

1. Add **`keycloak-config-cli`** (kcc) as a one-shot service to
   `stacks/02-keycloak/compose.yaml`. It runs after Keycloak is healthy, applies
   `AppsFab-realm.json` against the live Keycloak via the admin API, and exits `0`.
2. Replace the four `"secret": "CHANGE_ME_*"` literals in `AppsFab-realm.json` with
   kcc variable-substitution placeholders (`$(env:VAR_NAME)`), resolved from the same
   `secrets.env` the rest of the stack already uses.
3. Extend `.env.example` with the three currently-missing client-secret variables
   (`GRAFANA_OIDC_CLIENT_SECRET` already exists).
4. Add a one-time **migration note** (`stacks/02-keycloak/RECONCILE.md`) covering how to
   capture the four currently-UI-rotated secrets into `secrets.env`, the gate-test commands,
   and the rollback.
5. Update the `02-keycloak` row of the `README.md` stacks table.

### Out of scope (explicit YAGNI)

- **Adding cluster-side OIDC clients** (ArgoCD / cluster Grafana / cluster oauth2-proxy) —
  that is **M4a**, in the `cluster` repo, and depends on this being done.
- **Switching the secret backend** away from SOPS+age to 1Password-CLI-on-TrueNAS. The
  existing SOPS model stays. (Whether M4a bridges cluster-side 1Password to NAS-side env is
  an M4a concern.)
- **Removing `--import-realm`** from the `keycloak` service. It still serves the genuine
  fresh-install / disaster-recovery path (empty DB → seed the realm). kcc takes over for every
  boot after the first. The two are complementary, not redundant (see §4).
- Touching any other stack (`00-traefik`, `03-oauth2-proxy`, `20-observability`, …).
- A Keycloak DB restore drill — `/mnt/fast/appdata/keycloak` is already inside the TrueNAS
  snapshot regime.
- Changing the passkey/WebAuthn browser flow already defined in the realm.

### Gate (done = all true)

1. **Reconcile reaches a running realm.** Commit a realm change (e.g. tweak
   `displayName`), let Arcane redeploy the stack → the change is visible in the live Keycloak
   **with zero UI clicks** (verify via `kcadm.sh` or the admin REST API).
2. **No `CHANGE_ME_*` in the live realm.** All four client secrets in the running Keycloak
   match exactly what is in `secrets.env`
   (`kcadm.sh get clients/<id>/client-secret -r AppsFab`). The realm JSON in git contains
   only `$(env:…)` placeholders — `grep CHANGE_ME realm/AppsFab-realm.json` returns nothing.
3. **From-scratch reconstitution.** Delete the AppsFab realm, redeploy the stack → the realm
   is rebuilt **identically** (clients, secrets, passkey flow, groups, roles) from `realm/` +
   `secrets.env` alone, no UI step.
4. **Clean idempotent reconcile.** The kcc container exits `0`; its logs show four clients
   reconciled as `updated`/`unchanged` (never `created`) on any run after the first, and no
   unintended deletions.

---

## 2. Architecture

No new infrastructure — one new container in an existing stack, driven by the GitOps loop
that already exists.

```
git push (main, appwerkstatt/homelab-gitops)
   │
   ▼  (Arcane watches the repo)
Arcane (TrueNAS app)
   │  redeploys a stack when its compose / mounted files change
   ▼
stacks/02-keycloak  (docker compose project "keycloak")
   ┌──────────────────────────────────────────────────────────────────┐
   │ keycloak-db  postgres:17.8-alpine            (unchanged)          │
   │     ▲ pg                                                          │
   │     │                                                            │
   │ keycloak     quay.io/keycloak/keycloak:26.5.4                     │
   │     │  + healthcheck on the management port (NEW — see §4)        │
   │     │  --import-realm still present (fresh-install path)          │
   │     ▼ admin REST API (in-network, http://keycloak:8080)           │
   │ keycloak-config-cli   adorsys/keycloak-config-cli:<kc26 build>    │ ◀── NEW
   │     restart: "no"            # one-shot                           │
   │     depends_on: keycloak (condition: service_healthy)             │
   │     volumes:  ./realm:/config:ro                                  │
   │     env:                                                          │
   │       KEYCLOAK_URL=http://keycloak:8080                           │
   │       KEYCLOAK_USER / KEYCLOAK_PASSWORD = bootstrap admin         │
   │       IMPORT_FILES_LOCATIONS=/config/AppsFab-realm.json           │
   │       IMPORT_VAR_SUBSTITUTION_ENABLED=true                        │
   │       GRAFANA_OIDC_CLIENT_SECRET                                  │
   │       FORGEJO_OIDC_CLIENT_SECRET                                  │
   │       NETBOOT_OIDC_CLIENT_SECRET                                  │
   │       OAUTH2_PROXY_OIDC_CLIENT_SECRET                             │
   │     networks: [kc-internal]   # admin API never leaves the stack │
   └──────────────────────────────────────────────────────────────────┘
```

**Trigger model:** kcc is a **one-shot service** (`restart: "no"`). It runs once each time
Arcane (re)deploys the stack — which Arcane does whenever `compose.yaml` or a mounted file
under `realm/` changes. So **every git push that touches the realm reconciles it**, and no
push leaves it idle. This matches the repo's existing "Arcane watches git → redeploys stack"
contract exactly; it introduces no cron, no external trigger, no second moving part.

**Network:** kcc talks to Keycloak over the in-stack `kc-internal` network at
`http://keycloak:8080`. The admin API is never exposed on `edge` / the internet. The
bootstrap admin credentials it uses already exist in `secrets.env`
(`KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD`).

---

## 3. Deliverables

One PR to `homelab-gitops`. Five files.

| # | File | Change | Size |
|---|------|--------|------|
| 1 | `stacks/02-keycloak/compose.yaml` | Add the `keycloak-config-cli` service (block in §2). **Add a healthcheck to the `keycloak` service** so `depends_on: service_healthy` actually gates (see §4). Keep `--import-realm`. | +~25 lines |
| 2 | `stacks/02-keycloak/realm/AppsFab-realm.json` | Replace the four `"secret": "CHANGE_ME_*"` lines with `"secret": "$(env:<VAR>)"`. Nothing else. | 4 lines edited |
| 3 | `.env.example` | Add `FORGEJO_OIDC_CLIENT_SECRET`, `NETBOOT_OIDC_CLIENT_SECRET`, `OAUTH2_PROXY_OIDC_CLIENT_SECRET` next to the existing `GRAFANA_OIDC_CLIENT_SECRET`, in the `# --- Keycloak (02) ---` block. | +3 lines |
| 4 | `stacks/02-keycloak/RECONCILE.md` (new) | One-time migration + operations note: (a) read the four current live client secrets out of Keycloak and put them in `secrets.env` (re-encrypt `secrets.enc.env` via SOPS), (b) the four gate-test commands, (c) rollback = comment out the kcc service and redeploy. ~35 lines. | new |
| 5 | `README.md` | Append "+ Realm-Reconcile (keycloak-config-cli)" to the `02-keycloak` stacks-table row; one line in the bootstrap-order prose noting kcc reconciles on redeploy. | ~2 lines |

The `secrets.enc.env` itself is updated by the operator during migration (step 4a) and is not
pre-authored here — its plaintext values are real secrets and stay out of this design.

---

## 4. Key decisions & rationale

**kcc complements `--import-realm`, it does not replace it.** `--import-realm` handles the
empty-DB case (it seeds the realm so Keycloak can even start cleanly into a known state).
kcc handles every subsequent reconcile. Keeping both means the DR path (lose the DB, redeploy)
still works *and* ongoing edits apply — gate criteria #1 and #3 respectively. Removing
`--import-realm` would make a cold start depend on kcc's first run succeeding before anything
exists, with no benefit.

**Managed mode = authoritative (drift is removed).** kcc's default managed modes treat the
import file as the source of truth for the AppsFab realm: a client present in Keycloak but
absent from the JSON gets **deleted** on reconcile. For a config-as-code milestone this is the
desired behaviour — it is exactly what makes the realm trustworthy — but it has a sharp edge:
**any client created by hand in the AppsFab realm and not committed to git will be removed.**
This is called out in `RECONCILE.md`. (It does not touch the `master` realm or the bootstrap
admin, which live outside the imported realm.) The plan must confirm the default managed modes
behave as described for this kcc build, and explicitly decide each resource type's mode rather
than relying on an unverified default.

**Keycloak needs a healthcheck for `depends_on` to mean anything.** The current `keycloak`
service has **no** healthcheck (only `keycloak-db` does), so `condition: service_healthy`
would never be satisfiable. Keycloak 26 serves health on its **management interface (port
9000)** at `/health/ready` when health is enabled. The plan adds a healthcheck against that
endpoint (enabling `KC_HEALTH_ENABLED=true` / the management port if not already implied by
the image defaults) and verifies the exact port/path against `26.5.4` before wiring kcc's
`depends_on`. Without a real readiness gate, kcc races Keycloak's startup and fails
intermittently.

**Variable substitution syntax.** With `IMPORT_VAR_SUBSTITUTION_ENABLED=true`, kcc resolves
`$(env:VAR_NAME)` from its own environment. The four client-secret env vars are passed into
the kcc container from `secrets.env` (same mechanism the compose `${VAR}` interpolation
already uses elsewhere). The realm JSON therefore contains only references, never secrets —
keeping git clean and satisfying gate #2.

**Image pinning.** Per repo convention (no `latest`), the kcc image is pinned to the release
**built for Keycloak 26.x** (as of 2026-06 the 6.x line; the plan pins the exact tag verified
against `26.5.4` and lets Renovate track it, consistent with `renovate.json`).

**Secret backend stays SOPS+age.** No reason to disturb it in this slice. The migrated client
secrets join the existing `secrets.enc.env`. The decision of whether/how M4a bridges
cluster-side 1Password into NAS env is deferred to M4a and explicitly not prejudged here.

---

## 5. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| kcc deletes a hand-created client on first reconcile | `RECONCILE.md` warns; the realm JSON is confirmed to contain **all four** intended clients before the first run; managed modes reviewed in the plan. |
| Health gate misconfigured → kcc races startup | Add + verify the Keycloak healthcheck (§4) before merging; gate #4 catches a racing failure (non-zero exit). |
| Migrated secret typo'd into `secrets.env` (the recurring field-label class of bug) | Gate #2 verifies live secret == `secrets.env` for all four clients; a mismatch breaks the corresponding app's login immediately and visibly. |
| Arcane does not redeploy on a `realm/`-only change | Confirm during the plan that Arcane watches mounted files, not just `compose.yaml`; if it only watches `compose.yaml`, bump a trivial label/comment as part of realm-change commits, or document a manual redeploy. |
| `--import-realm` and kcc disagree on first cold boot | They run in sequence, not parallel: import seeds, Keycloak goes healthy, then kcc reconciles the now-existing realm. Idempotent by construction. |

---

## 6. Verification plan (maps to the gate)

1. **G1 reconcile:** edit `displayName` in the JSON → commit → Arcane redeploy →
   `kcadm.sh get realms/AppsFab --fields displayName` shows the new value.
2. **G2 no placeholders:** `grep CHANGE_ME realm/AppsFab-realm.json` empty; for each client,
   `kcadm.sh get clients/<uuid>/client-secret -r AppsFab` equals the `secrets.env` value.
3. **G3 reconstitution:** `kcadm.sh delete realms/AppsFab` → redeploy stack → realm present
   and complete; one OIDC login (e.g. Grafana on the NAS) succeeds end-to-end.
4. **G4 idempotency:** inspect kcc container logs across two consecutive redeploys → second
   run reports `updated`/`unchanged`, exit `0`, no deletions.

These run on the NAS (no headless SSH from the Mac — operator executes, per the standing
TrueNAS-access constraint).
