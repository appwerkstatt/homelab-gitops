#!/bin/sh
# Baut das Homelab-Handbuch aus main, sobald sich der Commit ändert (15-doku, doku-builder).
set -u
REPO="${DOKU_REPO:?DOKU_REPO fehlt}"
INTERVAL="${DOKU_INTERVAL:-300}"
SRC=/tmp/repo        # Arbeitskopie im Container (geht beim Neustart verloren, ist egal)
OUT=/site            # geteiltes Volume, nginx liest /site/current
last=""

while true; do
  if [ ! -d "$SRC/.git" ]; then
    git clone --quiet --depth 1 --branch main "$REPO" "$SRC" || { echo "clone fehlgeschlagen"; sleep 60; continue; }
  else
    { git -C "$SRC" fetch --quiet --depth 1 origin main && git -C "$SRC" reset --quiet --hard FETCH_HEAD; } \
      || { echo "fetch fehlgeschlagen"; sleep 60; continue; }
  fi
  rev="$(git -C "$SRC" rev-parse --short HEAD)"
  if [ "$rev" != "$last" ] || [ ! -e "$OUT/current" ]; then
    dir="$OUT/build-$rev"
    rm -rf "$dir"
    if (cd "$SRC" && mkdocs build --quiet --site-dir "$dir"); then
      ln -sfn "build-$rev" "$OUT/current"
      find "$OUT" -mindepth 1 -maxdepth 1 -name 'build-*' ! -name "build-$rev" -exec rm -rf {} +
      echo "Handbuch $rev gebaut"
    else
      rm -rf "$dir"
      echo "build of $rev failed, alte Seite bleibt"
    fi
    last="$rev"
  fi
  sleep "$INTERVAL"
done
