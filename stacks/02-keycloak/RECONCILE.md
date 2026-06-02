# Realm Reconcile (keycloak-config-cli)

`AppsFab-realm.json` is applied to the **running** Keycloak by the one-shot
`keycloak-config-cli` (kcc) service in `compose.yaml`, on every Arcane (re)deploy of this
stack. This is what makes the realm genuine config-as-code. `--import-realm` on the `keycloak`
service still seeds an **empty** DB (disaster recovery); kcc owns every change after that.

## kcc service account (one-time, before the first deploy)

kcc authenticates to Keycloak as a dedicated **master-realm service account** (client-credentials
grant) — not a human login, not the bootstrap admin (the `KC_BOOTSTRAP_ADMIN_*` vars name a user
that doesn't exist in the migrated DB). Create it once, logged into the admin console as the
master admin (`christian`):

1. Realm **master** → **Clients → Create client**: Client ID `keycloak-config-cli`, type OpenID
   Connect; **Client authentication ON**, **Service account roles ON** (Standard flow / Direct
   access grants can be OFF).
2. The new client → **Service account roles → Assign role** → "Filter by realm roles" → assign
   **`admin`** (master super-admin role; lets kcc manage the AppsFab realm).
3. **Credentials** tab → copy the **Client secret**.
4. In **Arcane → `keycloak` stack → Environment**, set `KCC_CLIENT_SECRET` to that value.

Compose wires this via `KEYCLOAK_GRANTTYPE=client_credentials`,
`KEYCLOAK_CLIENTID=keycloak-config-cli`, `KEYCLOAK_CLIENTSECRET=${KCC_CLIENT_SECRET}`,
`KEYCLOAK_LOGINREALM=master`.

## One-time migration (do this once, before the first kcc run)

The four client secrets used to be `CHANGE_ME_*` placeholders rotated by hand in the Keycloak
UI. The live values must be set in the **Arcane environment** for this stack (the source of
truth for env vars — `compose.yaml`'s `${...}` interpolation, including kcc's secret
pass-throughs, resolves from it) so kcc reconciles to the **same** secret each downstream app
already uses — otherwise kcc would overwrite the live secret with an empty value and break
those apps' logins.

> The committed `secrets.enc.env` (SOPS) is **legacy/unused** — env is managed in Arcane, not
> from that file. Ignore it here; it still carries dead `KC_CLIENT_SECRET_*` and is slated for
> separate cleanup.

1. Read each client's current secret. Easiest from the admin console: realm **AppsFab** →
   **Clients** → *client* → **Credentials** tab → **Client secret**, for `grafana`, `forgejo`,
   `netboot-console`, `oauth2-proxy`. (Or via kcadm using the service account from above — see the
   gate-tests block for the `config credentials --client … --secret …` form, then `get clients`.)
2. In **Arcane → the `keycloak` stack → Environment**, set the four canonical vars to those
   values: `GRAFANA_OIDC_CLIENT_SECRET`, `FORGEJO_OIDC_CLIENT_SECRET`,
   `NETBOOT_OIDC_CLIENT_SECRET`, `OAUTH2_PROXY_CLIENT_SECRET`. `GRAFANA_*` and `OAUTH2_PROXY_*`
   are likely already set (the existing Grafana/oauth2-proxy stacks use them), so the new ones
   to **add** are `FORGEJO_OIDC_CLIENT_SECRET` and `NETBOOT_OIDC_CLIENT_SECRET`. (Plus
   `KCC_CLIENT_SECRET` from the service-account section above.) Then redeploy the stack so kcc
   picks them up.

> **Forgejo wrinkle:** Forgejo's OIDC secret is **not** read from env at runtime — it was applied
> once via `forgejo admin auth add-oauth ... --secret '<value>'` and lives in `gitea.db`. Use the
> **same** `FORGEJO_OIDC_CLIENT_SECRET` value there. To rotate it later, update both the Arcane
> env (for kcc → realm) **and** re-run Forgejo's `update-oauth` with the new value.

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
# kcadm login as the kcc service account (reused below); <KCC_CLIENT_SECRET> = the Arcane value
docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --client keycloak-config-cli --secret '<KCC_CLIENT_SECRET>'

# G1 reconcile: change displayName in the JSON + bump KCC_REALM_REV, redeploy, then:
docker exec keycloak-keycloak-1 /opt/keycloak/bin/kcadm.sh get realms/AppsFab --fields displayName

# G2 no placeholders: each client's live secret equals the Arcane env value (spot-check grafana)
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
