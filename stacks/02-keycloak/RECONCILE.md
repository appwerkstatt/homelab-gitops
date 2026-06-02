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

# G1 reconcile: change displayName in the JSON + bump KCC_REALM_REV, redeploy, then:
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
