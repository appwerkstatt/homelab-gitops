#!/usr/bin/env bash
# CI-Check: jede ${VAR} aus stacks/*/compose.yaml muss in .env.example stehen.
# Ungenutzte Einträge in .env.example sind nur eine Warnung.
set -euo pipefail
cd "$(dirname "$0")/.."
used=$(scripts/env-vars.sh)
listed=$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env.example | tr -d '=' | sort -u)
missing=$(comm -23 <(echo "$used") <(echo "$listed"))
unused=$(comm -13 <(echo "$used") <(echo "$listed"))
for v in $unused; do echo "::warning file=.env.example::$v steht in .env.example, wird aber von keinem Stack genutzt"; done
if [ -n "$missing" ]; then
  for v in $missing; do echo "::error file=.env.example::$v wird in einem compose.yaml genutzt, fehlt aber in .env.example"; done
  exit 1
fi
echo "OK: alle $(echo "$used" | wc -l) Variablen sind in .env.example dokumentiert."
