#!/bin/bash
# nas-firewall.sh — Host-Firewall-Regeln für das NAS, die TrueNAS selbst nicht kennt (Security-Check 2026-11-22).
# Idempotent: jede Regel wird nur gesetzt, wenn sie fehlt. Läuft als root, beim Booten (Init-Script POSTINIT) und
# alle 10 Minuten per Cron, damit Regeln nach einem Docker-/Middleware-Neustart wieder da sind.
# Installation und Rückbau: docs/nas-firewall/README.md
#
#   H5  Sandbox-VM (br88, 10.88.88.2) darf keine neuen Verbindungen zum NAS oder durch das NAS aufbauen.
#       NAS -> VM (n8n -> sandbox-api :8080) bleibt erlaubt, Antworten der VM laufen über ESTABLISHED.
#   H4  Arcane (:30258, steuert Docker = Root) und die VM-Konsole (VNC :5900) nur aus MGMT_CIDRS.
set -u

MGMT_CIDRS="192.168.10.0/24"   # VLAN 10 (Trusted). Genau EIN Netz: iptables kann "! -s" nicht mit Listen.
SANDBOX_IF="${SANDBOX_IF:-br88}"
ARCANE_PORT=30258
VNC_PORT=5900

ipt()  { iptables  -w "$@"; }
ip6t() { ip6tables -w "$@"; }

# ensure <cmd> <chain> <pos> <rule...>: Regel an Position einfügen, wenn sie noch nicht existiert
ensure() {
  local cmd=$1 chain=$2 pos=$3; shift 3
  "$cmd" -C "$chain" "$@" 2>/dev/null || "$cmd" -I "$chain" "$pos" "$@"
}

# --- H5: Sandbox-Bridge ---
if [ -e "/sys/class/net/$SANDBOX_IF" ]; then
  acc=(-i "$SANDBOX_IF" -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment "nas-firewall: sandbox replies" -j ACCEPT)
  drp=(-i "$SANDBOX_IF" -m comment --comment "nas-firewall: sandbox no new conns" -j DROP)
  for chain in INPUT FORWARD; do
    # Das Paar gehört zusammen und in dieser Reihenfolge (ACCEPT vor DROP). Fehlt eine Hälfte, beide neu setzen,
    # sonst stünde ein einzelnes DROP über dem ACCEPT und n8n bekäme keine Antworten der VM mehr.
    if ! { ipt -C "$chain" "${acc[@]}" 2>/dev/null && ipt -C "$chain" "${drp[@]}" 2>/dev/null; }; then
      while ipt -D "$chain" "${acc[@]}" 2>/dev/null; do :; done
      while ipt -D "$chain" "${drp[@]}" 2>/dev/null; do :; done
      ipt -I "$chain" 1 "${drp[@]}"
      ipt -I "$chain" 1 "${acc[@]}"
    fi
  done
else
  echo "nas-firewall: $SANDBOX_IF fehlt (VM-Bridge noch nicht da?) – H5-Regeln übersprungen" >&2
fi

# --- H4: VNC der VMs (qemu lauscht auf dem Host) ---
ensure ipt INPUT 1 -p tcp --dport "$VNC_PORT" ! -i lo ! -s "$MGMT_CIDRS" -m comment --comment "nas-firewall: vnc mgmt only" -j DROP

# --- H4: Arcane. IPv4-Zugriffe von außen laufen per DNAT durch FORWARD -> Kette DOCKER-USER (Original-Port
# über conntrack, weil der Zielport nach DNAT der Container-Port ist). Die Kette legt Docker an; fehlt sie
# (Docker startet noch), setzt der nächste Cron-Lauf die Regel.
if ipt -nL DOCKER-USER >/dev/null 2>&1; then
  ensure ipt DOCKER-USER 1 -p tcp -m conntrack --ctorigdstport "$ARCANE_PORT" ! -s "$MGMT_CIDRS" -m comment --comment "nas-firewall: arcane mgmt only" -j DROP
else
  echo "nas-firewall: Kette DOCKER-USER fehlt noch – Arcane-Regel beim nächsten Lauf" >&2
fi

# --- IPv6: im LAN ungenutzt; Arcane (docker-proxy) und VNC lauschen aber auf [::] -> nur lokal erlauben ---
if command -v ip6tables >/dev/null 2>&1; then
  for port in "$ARCANE_PORT" "$VNC_PORT"; do
    ensure ip6t INPUT 1 -p tcp --dport "$port" ! -i lo -m comment --comment "nas-firewall: v6 mgmt off" -j DROP
  done
fi
exit 0
