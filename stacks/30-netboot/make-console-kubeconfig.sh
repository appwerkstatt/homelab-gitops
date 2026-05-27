#!/usr/bin/env bash
# make-console-kubeconfig.sh — extrahiert das Service-Account-Token aus dem
# Phase-3b RBAC-Setup (console-rbac.yaml) und baut daraus eine restricted
# kubeconfig für die netboot-console.
#
# Auf einem k3s-server-Pi ausführen (z.B. pi5d1). Voraussetzung: console-rbac.yaml
# wurde vorher applied (sudo k3s kubectl apply -f console-rbac.yaml). Das Skript
# verifiziert das + extrahiert + verifiziert die Identity gegen die kube-api,
# schreibt das Resultat nach /tmp/console-kubeconfig. scp-Befehl am Ende muss
# angepasst werden — wir hardcoden den TrueNAS-Pfad nicht weil das pro Setup
# variiert.

set -euo pipefail

NS=kube-system
SA=netboot-console
SECRET=netboot-console-token
OUTPUT=/tmp/console-kubeconfig
EXPECTED_USER="system:serviceaccount:${NS}:${SA}"

# Welcher kubectl ist verfügbar? Pi5 hat 'k3s kubectl', dev-host hat plain kubectl.
if command -v kubectl >/dev/null 2>&1; then
	KUBECTL=(kubectl)
elif command -v k3s >/dev/null 2>&1; then
	KUBECTL=(sudo k3s kubectl)
else
	echo "FAIL: weder kubectl noch k3s gefunden — auf einem k3s-server ausführen." >&2
	exit 1
fi

echo "==> Verifying that RBAC was applied"
if ! "${KUBECTL[@]}" -n "$NS" get sa "$SA" >/dev/null 2>&1; then
	echo "FAIL: ServiceAccount ${NS}/${SA} existiert nicht." >&2
	echo "      console-rbac.yaml zuerst applien:" >&2
	echo "      ${KUBECTL[*]} apply -f /pfad/zu/console-rbac.yaml" >&2
	exit 1
fi
if ! "${KUBECTL[@]}" -n "$NS" get secret "$SECRET" >/dev/null 2>&1; then
	echo "FAIL: Secret ${NS}/${SECRET} existiert nicht — RBAC unvollständig applied?" >&2
	exit 1
fi

echo "==> Extracting token + CA + API-URL"
TOKEN=$("${KUBECTL[@]}" -n "$NS" get secret "$SECRET" -o jsonpath='{.data.token}' | base64 -d)
CA=$(    "${KUBECTL[@]}" -n "$NS" get secret "$SECRET" -o jsonpath='{.data.ca\.crt}')
API=$(   "${KUBECTL[@]}" config view --raw -o jsonpath='{.clusters[0].cluster.server}')

if [[ -z "$TOKEN" || -z "$CA" || -z "$API" ]]; then
	echo "FAIL: token/ca/api leer — controller-manager hat das Secret evtl. noch nicht befüllt." >&2
	echo "      Ein paar Sekunden warten + nochmal versuchen." >&2
	exit 1
fi

echo "==> Writing $OUTPUT"
cat > "$OUTPUT" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: cluster
  cluster:
    server: ${API}
    certificate-authority-data: ${CA}
contexts:
- name: netboot-console
  context:
    cluster: cluster
    user: netboot-console
current-context: netboot-console
users:
- name: netboot-console
  user:
    token: ${TOKEN}
EOF
chmod 600 "$OUTPUT"

echo "==> Verifying identity against kube-apiserver"
WHO=$("${KUBECTL[@]}" --kubeconfig "$OUTPUT" auth whoami -o jsonpath='{.status.userInfo.username}' 2>/dev/null || true)
if [[ "$WHO" != "$EXPECTED_USER" ]]; then
	echo "FAIL: auth whoami returnt '$WHO', erwartet '$EXPECTED_USER'." >&2
	echo "      kubeconfig wurde geschrieben aber bindet nicht zur erwarteten SA." >&2
	exit 1
fi

echo
echo "OK: $OUTPUT geschrieben, Identity = $WHO"
echo
echo "Nächster Schritt — auf TrueNAS kopieren:"
echo "  scp $OUTPUT truenas:/mnt/data/provisioning/control/console-kubeconfig"
echo "  ssh truenas chmod 600 /mnt/data/provisioning/control/console-kubeconfig"
echo
echo "Danach compose up -d (oder Arcane re-deploys automatisch nach GitOps-pull)."
