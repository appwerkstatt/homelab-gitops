#!/usr/bin/env bash
# Rendert die Arcane-Environment für einen Stack aus .env.example + 1Password (op CLI).
#   scripts/render-env.sh keycloak    # Stack per Name-Teil (stacks/*keycloak*/)
#   scripts/render-env.sh --all       # alle Variablen
# Ausgabe auf stdout -> in Arcane -> <Stack> -> Environment einfügen. Nicht in Dateien im Repo umleiten.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v op >/dev/null || { echo "op (1Password CLI) fehlt: https://developer.1password.com/docs/cli/" >&2; exit 1; }
[ $# -eq 1 ] || { echo "usage: $0 <stack>|--all" >&2; exit 2; }

if [ "$1" = "--all" ]; then
  vars=$(scripts/env-vars.sh)
else
  matches=(stacks/*"$1"*/)
  [ -d "${matches[0]}" ] || { echo "kein Stack passt zu '$1'" >&2; exit 2; }
  [ ${#matches[@]} -eq 1 ] || { echo "mehrdeutig: ${matches[*]}" >&2; exit 2; }
  vars=$(scripts/env-vars.sh "${matches[0]}")
fi

# Zeilen VAR=... aus .env.example für genau diese Vars, ohne Inline-Kommentare, dann op inject.
awk -v vars="$vars" '
  BEGIN { n = split(vars, v, "\n"); for (i = 1; i <= n; i++) want[v[i]] = 1 }
  /^[A-Za-z_][A-Za-z0-9_]*=/ {
    name = substr($0, 1, index($0, "=") - 1)
    if (name in want) { sub(/[ \t]+#.*$/, ""); print }
  }' .env.example | op inject
