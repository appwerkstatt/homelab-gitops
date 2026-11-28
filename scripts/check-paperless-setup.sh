#!/usr/bin/env bash
# Startet die Paperless-Version aus stacks/11-paperless/compose.yaml (SQLite, frisch) und prüft
# stacks/11-paperless/setup/paperless-setup.py dagegen: Anlegen, zweiter Lauf ändert nichts, Consume-Ordner-
# Workflows (Besitzer pro Unterordner), Teilen mit haushalt, Backfill und die Abfragen der n8n-Workflows.
# Renovate-PRs für Paperless bleiben hier stehen, wenn sich die API ändert, auf die das Skript baut.
#   scripts/check-paperless-setup.sh            # in CI (Docker des Runners)
set -euo pipefail
cd "$(dirname "$0")/.."
compose=stacks/11-paperless/compose.yaml
image=$(grep -oE 'ghcr.io/paperless-ngx/paperless-ngx:[0-9][^ ]*' "$compose")
redis=$(grep -oE 'image: redis:[0-9][^ ]*' "$compose" | cut -d' ' -f2)
ocr=$(sed -nE 's/^ *PAPERLESS_OCR_LANGUAGE: *"?([^" #]+)"?.*/\1/p' "$compose")
pw=$(openssl rand -hex 16)
tmp=$(mktemp -d)
mkdir -p "$tmp/consume"
chmod 777 "$tmp/consume"

cleanup() {
  docker rm -f pl-check pl-check-redis >/dev/null 2>&1 || true
  docker network rm pl-check >/dev/null 2>&1 || true
  rm -rf "$tmp" 2>/dev/null || sudo rm -rf "$tmp" 2>/dev/null || true
}
trap cleanup EXIT
cleanup
mkdir -p "$tmp/consume" && chmod 777 "$tmp/consume"

docker network create pl-check >/dev/null
docker run -d --name pl-check-redis --network pl-check "$redis" >/dev/null
docker run -d --name pl-check --network pl-check -p 127.0.0.1:8000:8000 \
  -e PAPERLESS_REDIS=redis://pl-check-redis:6379 \
  -e PAPERLESS_ADMIN_USER=admin -e PAPERLESS_ADMIN_PASSWORD="$pw" \
  -e PAPERLESS_OCR_LANGUAGE="$ocr" -e PAPERLESS_CONSUMER_RECURSIVE=true -e PAPERLESS_CONSUMER_POLLING=2 \
  -e PAPERLESS_TIME_ZONE=Europe/Berlin \
  -v "$tmp/consume:/usr/src/paperless/consume" "$image" >/dev/null

echo "Warte auf $image (OCR: $ocr)"
for _ in $(seq 1 120); do
  curl -sf -u "admin:$pw" http://127.0.0.1:8000/api/profile/ >/dev/null 2>&1 && break
  sleep 3
done
if ! curl -sf -u "admin:$pw" http://127.0.0.1:8000/api/profile/ >/dev/null; then
  docker logs pl-check 2>&1 | tail -60
  echo "::error file=$compose::$image startet nicht (Log oben)"
  exit 1
fi

export PAPERLESS_URL=http://127.0.0.1:8000 CHECK_ADMIN_PASSWORD="$pw" CHECK_CONSUME="$tmp/consume"
if ! python3 -I scripts/check-paperless-setup.py; then
  echo "--- Paperless-Log ---"; docker logs pl-check 2>&1 | tail -80
  echo "::error file=stacks/11-paperless/setup/paperless-setup.py::paperless-setup.py passt nicht zu $image (siehe oben)"
  exit 1
fi
