#!/usr/bin/env bash
# Holt Standard-Community-Dashboards von grafana.com nach config/dashboards/
# und setzt die Datasource-UID auf "victoriametrics" (bzw. "loki"), damit sie
# per Provisioning OHNE Import-Assistent laufen.
#
# Einmalig (oder zum Aktualisieren) auf dem NAS ausführen, danach die JSONs committen.
#   bash stacks/20-observability/fetch-dashboards.sh && git add stacks/20-observability/config/dashboards
#
# Neues Dashboard aufnehmen: Zeile in DASH ergänzen (name=grafana.com-ID), Skript erneut laufen lassen.
set -euo pipefail
cd "$(dirname "$0")/config/dashboards"

# "Dateiname:grafana.com-ID" (portabel, kein assoziatives Array -> läuft auch auf macOS bash 3.2)
DASH="
node-exporter-full:1860
cadvisor-docker:19908
victoriametrics-single:10229
"

for entry in $DASH; do
  name="${entry%%:*}"
  id="${entry##*:}"
  rev="$(curl -fsSL "https://grafana.com/api/dashboards/${id}" \
         | python3 -c 'import sys,json;print(json.load(sys.stdin)["revision"])')"
  echo "  ${name}  (id ${id}, rev ${rev})"
  curl -fsSL "https://grafana.com/api/dashboards/${id}/revisions/${rev}/download" \
    | sed -e 's/${DS_PROMETHEUS}/victoriametrics/g' \
          -e 's/${DS_VICTORIAMETRICS}/victoriametrics/g' \
          -e 's/${DS_LOKI}/loki/g' \
    > "${name}.json"
done
echo "Fertig. JSONs liegen in config/dashboards/ — jetzt committen."
