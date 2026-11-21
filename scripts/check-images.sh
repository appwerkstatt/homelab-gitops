#!/usr/bin/env bash
# CI-Check: jedes Image, das ein PR in stacks/*/compose.yaml neu einträgt, muss in der Registry
# existieren und ein linux/amd64-Image haben (das NAS ist x86). Fängt Renovate-Bumps auf Tags
# ab, die (noch) nicht existieren oder nur für arm64 gebaut sind — bevor Automerge + Arcane sie
# um 4 Uhr ausrollen.
#   scripts/check-images.sh <base-ref>          # nur im Diff geänderte Images (PR)
#   scripts/check-images.sh --all               # alle Images (manuell)
# Images aus der lokalen NAS-Registry (127.0.0.1:…) werden übersprungen.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v skopeo >/dev/null || { echo "skopeo fehlt" >&2; exit 2; }
[ $# -eq 1 ] || { echo "usage: $0 <base-ref>|--all" >&2; exit 2; }

extract() { grep -oE '^[+ ]?[[:space:]]*image:[[:space:]]*[^[:space:]#]+' | sed -E 's/.*image:[[:space:]]*//'; }
if [ "$1" = "--all" ]; then
  images=$(cat stacks/*/compose.yaml | extract | sort -u)
else
  images=$(git diff -U0 "$1"...HEAD -- 'stacks/*/compose.yaml' | { grep '^+' || true; } | { grep -v '^+++' || true; } | { extract || true; } | sort -u)
fi
[ -n "$images" ] || { echo "Keine geänderten Images."; exit 0; }

fail=0
for img in $images; do
  case "$img" in 127.0.0.1:*|localhost:*) echo "skip  $img (lokale NAS-Registry)"; continue ;; esac
  ref="$img"; case "${img%%/*}" in *.*|*:*) ;; *) ref="docker.io/$img" ;; esac
  if arch=$(skopeo inspect --retry-times 3 --override-os linux --override-arch amd64 \
              --format '{{.Os}}/{{.Architecture}}' "docker://$ref" 2>/tmp/skopeo.err); then
    if [ "$arch" = "linux/amd64" ]; then echo "ok    $img ($arch)"
    else echo "::error::$img: kein linux/amd64-Image (gefunden: $arch)"; fail=1; fi
  else
    echo "::error::$img: nicht abrufbar — $(tail -1 /tmp/skopeo.err)"; fail=1
  fi
done
exit $fail
