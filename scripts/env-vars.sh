#!/usr/bin/env bash
# Listet die Variablen, die compose-Dateien per ${VAR} / ${VAR:-default} lesen (eine pro Zeile).
#   scripts/env-vars.sh                      # alle Stacks
#   scripts/env-vars.sh stacks/02-keycloak   # ein Stack
set -euo pipefail
cd "$(dirname "$0")/.."
if [ $# -eq 0 ]; then set -- stacks/*/; fi
for d in "$@"; do cat "${d%/}/compose.yaml"; done \
  | sed 's/#.*//' \
  | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*' | cut -c3- | sort -u
