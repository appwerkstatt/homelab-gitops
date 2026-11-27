#!/usr/bin/env bash
# Prüft, ob die Plane-Dateien, auf denen stacks/14-plane/patches/gitea.py aufbaut, in der
# Version aus compose.yaml noch genau so aussehen wie beim Schreiben des Patches.
# Schlägt ein Plane-Update (Renovate) hier fehl: Upstream-Diff lesen, Patch anpassen,
# danach upstream.sha256 neu erzeugen:  scripts/check-plane-patch.sh --update
set -euo pipefail
cd "$(dirname "$0")/.."
dir=stacks/14-plane/patches
tag=$(grep -oE 'makeplane/plane-backend:v[0-9][^ ]*' stacks/14-plane/compose.yaml | sort -u)
[ "$(echo "$tag" | wc -l)" -eq 1 ] || { echo "::error::plane-backend mit unterschiedlichen Tags: $tag"; exit 1; }
tag=${tag##*:}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for f in $(awk '{print $2}' "$dir/upstream.sha256"); do
  mkdir -p "$tmp/$(dirname "$f")"
  curl -fsSL --retry 3 "https://raw.githubusercontent.com/makeplane/plane/$tag/apps/api/$f" -o "$tmp/$f"
done
if [ "${1:-}" = "--update" ]; then
  (cd "$tmp" && sha256sum $(awk '{print $2}' "$OLDPWD/$dir/upstream.sha256")) > "$dir/upstream.sha256"
  echo "upstream.sha256 für $tag neu geschrieben"; exit 0
fi
if ! (cd "$tmp" && sha256sum -c --quiet "$OLDPWD/$dir/upstream.sha256"); then
  echo "::error file=$dir/gitea.py::Plane $tag hat Dateien geändert, auf denen der Keycloak-Patch aufbaut. Diff gegen die alte Version lesen, patches/gitea.py anpassen, dann scripts/check-plane-patch.sh --update (Handbuch: Dienste → Plane)."
  exit 1
fi
echo "Plane $tag: Keycloak-Patch passt zu den Upstream-Dateien"
