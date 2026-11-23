#!/usr/bin/env bash
# Einrichtungs-Ports der Station: ein Linux-Network-Namespace je Gateway.
#
# Neue UG65 kommen mit derselben festen Werks-IP, eingerichtete holen eth0 per DHCP. Im selben Netz
# stoeren sie sich (ARP). Deshalb bekommt jeder Port ein eigenes Namespace
# "gcp<N>": darin sieht die Station genau ein Gateway unter seiner Werks-IP.
# Internet (Cloud-API, Milesight) und VPN gehen per veth + NAT ueber den Host.
#
# Konfiguration /etc/gatewaychef/ports, eine Zeile je Port:
#   <N>  <interface>            USB-Ethernet-Adapter, ein Gateway direkt dran
#   <N>  <trunk-interface> <V>  VLAN-Switch: Port des Switches = VLAN V (Port-VLAN)
# Beispiel:
#   1 enx00e04c680001
#   2 enx00e04c680002
#   3 enp2s0 13
#
#   ports.sh up      Namespaces anlegen (idempotent, laeuft beim Boot)
#   ports.sh down    alles wieder entfernen
#   ports.sh list    Ports und Gateway-Antwort zeigen
set -euo pipefail
CONF="${GATEWAYCHEF_PORTS:-/etc/gatewaychef/ports}"
GW_ADDRS=("192.168.1.200/24" "192.168.23.200/24" "192.168.77.1/24")   # Werksnetze + DHCP-Netz
TRANSFER="10.231"                                   # 10.231.<N>.0/30 Host <-> Namespace

ports() { [[ -f "$CONF" ]] && grep -Ev '^\s*(#|$)' "$CONF" || true; }

resolv() {
  # systemd-resolved (127.0.0.53) ist aus dem Namespace nicht erreichbar.
  local src=/etc/resolv.conf
  [[ -f /run/systemd/resolve/resolv.conf ]] && src=/run/systemd/resolve/resolv.conf
  grep -v '^nameserver 127\.' "$src" || true
  grep -q '^nameserver [^1]' "$src" || echo "nameserver 1.1.1.1"
}

up_port() {
  local n="$1" ifc="$2" vlan="${3:-}" ns="gcp$1" dev hv nv
  [[ "$n" =~ ^[0-9]{1,2}$ ]] || { echo "Port '$n' ungueltig (1-99)" >&2; return 1; }
  ip netns list | grep -qw "$ns" || ip netns add "$ns"
  ip -n "$ns" link set lo up
  if [[ -n "$vlan" ]]; then
    dev="gcv$n"
    if ! ip -n "$ns" link show "$dev" >/dev/null 2>&1; then
      ip link set "$ifc" up
      ip link add link "$ifc" name "$dev" type vlan id "$vlan"
      ip link set "$dev" netns "$ns"
    fi
  else
    dev="$ifc"
    if ! ip -n "$ns" link show "$dev" >/dev/null 2>&1; then
      ip link show "$dev" >/dev/null 2>&1 || { echo "Port $n: Interface $dev fehlt" >&2; return 1; }
      ip link set "$dev" netns "$ns"
    fi
  fi
  for a in "${GW_ADDRS[@]}"; do ip -n "$ns" addr replace "$a" dev "$dev"; done
  ip -n "$ns" link set "$dev" up
  dhcp_up "$n" "$dev"

  hv="gch$n"; nv="gcn$n"
  if ! ip link show "$hv" >/dev/null 2>&1; then
    ip link add "$hv" type veth peer name "$nv"
    ip link set "$nv" netns "$ns"
  fi
  ip addr replace "$TRANSFER.$n.1/30" dev "$hv"; ip link set "$hv" up
  ip -n "$ns" addr replace "$TRANSFER.$n.2/30" dev "$nv"; ip -n "$ns" link set "$nv" up
  ip -n "$ns" route replace default via "$TRANSFER.$n.1"
  mkdir -p "/etc/netns/$ns"; resolv > "/etc/netns/$ns/resolv.conf"
  echo "Port $n: $ns  $dev${vlan:+ (VLAN $vlan auf $ifc)}"
}

dhcp_up() {
  # Eingerichtete Gateways haben eth0 auf DHCP: je Namespace ein dnsmasq (nur Adressen,
  # keine Route/DNS). Leases liest utils/gateway_lan.py (GATEWAYCHEF_PORT=<N>).
  local n="$1" dev="$2" ns="gcp$1" pid="/run/gatewaychef/dhcp-gcp$1.pid"
  command -v dnsmasq >/dev/null || { echo "Port $n: dnsmasq fehlt (apt install dnsmasq-base), kein DHCP" >&2; return 0; }
  mkdir -p /run/gatewaychef /var/lib/gatewaychef
  [[ -f "$pid" ]] && kill "$(cat "$pid")" 2>/dev/null || true
  ip netns exec "$ns" dnsmasq --conf-file=/dev/null --port=0 --interface="$dev" --bind-interfaces \
    --dhcp-range=192.168.77.100,192.168.77.150,255.255.255.0,10m --dhcp-option=3 --dhcp-option=6 \
    --dhcp-authoritative --dhcp-leasefile="/var/lib/gatewaychef/dhcp-gcp$n.leases" --pid-file="$pid" --user=root
}

nat_up() {
  sysctl -qw net.ipv4.ip_forward=1
  nft list table ip gatewaychef >/dev/null 2>&1 && nft delete table ip gatewaychef
  nft -f - <<NFT
table ip gatewaychef {
  chain gc_post {
    type nat hook postrouting priority srcnat;
    ip saddr $TRANSFER.0.0/16 ip daddr != $TRANSFER.0.0/16 masquerade
  }
  chain gc_forward {
    type filter hook forward priority filter;
    ip saddr $TRANSFER.0.0/16 accept
    ip daddr $TRANSFER.0.0/16 ct state established,related accept
  }
}
NFT
}

down() {
  local n ifc vlan
  while read -r n ifc vlan; do
    [[ -f "/run/gatewaychef/dhcp-gcp$n.pid" ]] && kill "$(cat "/run/gatewaychef/dhcp-gcp$n.pid")" 2>/dev/null || true
    ip netns del "gcp$n" 2>/dev/null || true      # Interfaces fallen an den Host zurueck
    ip link del "gch$n" 2>/dev/null || true
    rm -rf "/etc/netns/gcp$n"
  done < <(ports)
  nft delete table ip gatewaychef 2>/dev/null || true
}

list() {
  local n ifc vlan out
  while read -r n ifc vlan; do
    lease=$(sort -rn "/var/lib/gatewaychef/dhcp-gcp$n.leases" 2>/dev/null | awk 'NR==1{print $3}')
    out=$( { [[ -n "$lease" ]] && ip netns exec "gcp$n" curl -s -m 2 "http://$lease/node-red/device-info"; } 2>/dev/null ||
          ip netns exec "gcp$n" curl -s -m 2 http://192.168.23.150/node-red/device-info 2>/dev/null ||
          ip netns exec "gcp$n" curl -s -m 2 http://192.168.1.1/node-red/device-info 2>/dev/null || true)
    printf "Port %-2s %-18s %s\n" "$n" "$ifc${vlan:+.$vlan}" "${out:-(kein Gateway)}" | cut -c1-160
  done < <(ports)
}

[[ $EUID -eq 0 ]] || { echo "bitte als root" >&2; exit 1; }
case "${1:-up}" in
  up)
    [[ -s "$CONF" ]] || { echo "keine Ports in $CONF" >&2; exit 0; }
    while read -r n ifc vlan; do up_port "$n" "$ifc" "$vlan"; done < <(ports)
    nat_up ;;
  down) down ;;
  list) list ;;
  *) echo "ports.sh up|down|list" >&2; exit 2 ;;
esac
