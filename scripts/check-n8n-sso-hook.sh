#!/usr/bin/env bash
# Startet die n8n-Version aus stacks/13-n8n/compose.yaml mit dem Keycloak-Hook (hooks/keycloak-sso.js)
# und prüft den Login-Ablauf samt Negativfällen (check-n8n-sso-hook.mjs, mit echtem Browser).
# Renovate-PRs für n8n bleiben hier stehen, wenn ein Update die Interna ändert, auf die der Hook baut.
# Dann: Log unten lesen ("keycloak-sso: DEAKTIVIERT: …"), Hook anpassen (Handbuch: Dienste → n8n).
#   scripts/check-n8n-sso-hook.sh                 # in CI (Docker + Chrome des Runners)
#   N8N_BASE_URL=http://127.0.0.1:5678 SSO_SECRET=… scripts/check-n8n-sso-hook.sh   # gegen ein schon laufendes n8n
set -euo pipefail
cd "$(dirname "$0")/.."
image=$(grep -oE 'n8nio/n8n:[0-9][^ ]*' stacks/13-n8n/compose.yaml)
pw=1.63.0   # playwright-core, nur als Client; Browser = Chrome des Runners

if [ -z "${N8N_BASE_URL:-}" ]; then
  export SSO_SECRET=$(openssl rand -hex 32)
  name=n8n-sso-check
  trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" -p 127.0.0.1:5678:5678 \
    -e EXTERNAL_HOOK_FILES=/opt/n8n-hooks/keycloak-sso.js \
    -e N8N_SSO_SECRET_SHA256="$(printf %s "$SSO_SECRET" | sha256sum | cut -d' ' -f1)" \
    -e N8N_SECURE_COOKIE=false -e N8N_DIAGNOSTICS_ENABLED=false \
    -v "$PWD/stacks/13-n8n/hooks:/opt/n8n-hooks:ro" "$image" >/dev/null
  export N8N_BASE_URL=http://127.0.0.1:5678 PW_CHANNEL=${PW_CHANNEL:-chrome}
  for _ in $(seq 1 90); do
    docker logs "$name" 2>&1 | grep -q 'keycloak-sso:' && curl -sf "$N8N_BASE_URL/healthz/readiness" >/dev/null && break
    sleep 2
  done
  docker logs "$name" 2>&1 | grep 'keycloak-sso:' || true
  if ! docker logs "$name" 2>&1 | grep -q 'keycloak-sso: aktiv'; then
    docker logs "$name" 2>&1 | tail -40
    echo "::error file=stacks/13-n8n/hooks/keycloak-sso.js::$image: Keycloak-Hook nicht aktiv (siehe Log oben)"
    exit 1
  fi
fi

tmp=$(mktemp -d); trap 'rm -rf "$tmp"; docker rm -f n8n-sso-check >/dev/null 2>&1 || true' EXIT
(cd "$tmp" && npm init -y >/dev/null && npm install --silent --no-audit --no-fund "playwright-core@$pw" >/dev/null)
cp scripts/check-n8n-sso-hook.mjs "$tmp/"
echo "Prüfe $image"
node "$tmp/check-n8n-sso-hook.mjs"
