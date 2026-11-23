#!/usr/bin/env bash
# GatewayChef station setup (Debian/Ubuntu, also Raspberry Pi OS). Run as root:
#   sudo bash install.sh --gw-port enx00e04c680001
# --gw-port   network interface the gateway is plugged into (direct cable, no switch)
# Idempotent: running it again updates the unit and keeps /etc/gatewaychef/env.
set -euo pipefail
GW_PORT=""
REPO="${GATEWAYCHEF_REPO:-https://github.com/ball-b-lab/gatewayChef.git}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gw-port) GW_PORT="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    *) echo "unbekannte Option $1" >&2; exit 2 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "bitte mit sudo starten" >&2; exit 1; }
HOME_DIR=/opt/gatewaychef

echo ".. Pakete"
apt-get update -qq
apt-get install -y -qq git curl wireguard-tools ca-certificates >/dev/null

id gatewaychef >/dev/null 2>&1 || useradd --system --home "$HOME_DIR" --create-home --shell /usr/sbin/nologin gatewaychef
if [[ ! -x "$HOME_DIR/.local/bin/uv" ]]; then
  echo ".. uv"
  sudo -u gatewaychef env HOME="$HOME_DIR" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' >/dev/null
fi
if [[ ! -d "$HOME_DIR/app/.git" ]]; then
  echo ".. Code"
  sudo -u gatewaychef git clone --quiet "$REPO" "$HOME_DIR/app"
fi

install -d -m 750 -o root -g gatewaychef /etc/gatewaychef
if [[ ! -f /etc/gatewaychef/env ]]; then
  install -m 640 -o root -g gatewaychef "$HOME_DIR/app/.env.example" /etc/gatewaychef/env
  echo "!! /etc/gatewaychef/env angelegt: Zugangsdaten eintragen (siehe docs/LINUX_STATION.md)"
fi

if [[ -n "$GW_PORT" ]]; then
  echo ".. Gateway-Port $GW_PORT"
  # Two addresses so both possible factory defaults of the UG65 are reachable
  # (192.168.1.1 and 192.168.23.150). No default route, no DNS on this port.
  if command -v nmcli >/dev/null; then
    nmcli -t -f NAME con show | grep -qx gw-lan || nmcli con add type ethernet ifname "$GW_PORT" con-name gw-lan >/dev/null
    nmcli con mod gw-lan ipv4.method manual ipv4.addresses "192.168.1.200/24,192.168.23.200/24" \
      ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.method disabled connection.autoconnect yes
    nmcli con up gw-lan >/dev/null || echo "   (gw-lan kommt hoch, sobald ein Gateway steckt)"
  else
    cat > /etc/systemd/network/50-gw-lan.network <<NET
[Match]
Name=$GW_PORT

[Network]
Address=192.168.1.200/24
Address=192.168.23.200/24
ConfigureWithoutCarrier=yes
NET
    systemctl enable --now systemd-networkd >/dev/null
    networkctl reload
  fi
fi

if [[ -n "$GW_PORT" ]]; then
  # Eingerichtete Gateways haben eth0 auf DHCP: Station verteilt Adressen auf dem Gateway-Port
  # (192.168.1.100-150, ohne Route/DNS). GatewayChef liest die Leases (utils/gateway_lan.py).
  echo ".. DHCP auf $GW_PORT"
  apt-get install -y -qq dnsmasq-base >/dev/null
  install -d -m 755 /var/lib/gatewaychef
  install -m 644 "$HOME_DIR/app/scripts/linux/gatewaychef-dhcp@.service" /etc/systemd/system/gatewaychef-dhcp@.service
  systemctl daemon-reload
  systemctl enable "gatewaychef-dhcp@$GW_PORT" >/dev/null
  systemctl restart "gatewaychef-dhcp@$GW_PORT"
fi

echo ".. Einrichtungs-Ports (ein Netz-Namespace je Gateway)"
apt-get install -y -qq iproute2 nftables dnsmasq-base >/dev/null
[[ -f /etc/gatewaychef/ports ]] || cat > /etc/gatewaychef/ports <<'PORTS'
# Eine Zeile je Port, ein Gateway je Port. Alle UG65 haben dieselbe feste Werks-IP, jeder Port
# bekommt deshalb ein eigenes Netz-Namespace (scripts/linux/ports.sh).
#   <N> <interface>            USB-Ethernet-Adapter, Gateway direkt dran
#   <N> <trunk-interface> <V>  VLAN-Switch: Switch-Port = VLAN V
# 1 enx00e04c680001
# 2 enx00e04c680002
# 3 enp2s0 13
PORTS
chmod 644 /etc/gatewaychef/ports
chmod +x "$HOME_DIR/app/scripts/linux/ports.sh"
install -m 755 -o root -g root "$HOME_DIR/app/scripts/linux/gatewaychef-port" /usr/local/sbin/gatewaychef-port
echo 'gatewaychef ALL=(root) NOPASSWD: /usr/local/sbin/gatewaychef-port *' > /etc/sudoers.d/gatewaychef
chmod 440 /etc/sudoers.d/gatewaychef
visudo -cf /etc/sudoers.d/gatewaychef >/dev/null
install -d -m 750 -o gatewaychef -g gatewaychef /var/log/gatewaychef
grep -q '^STATION_LOG_DIR=' /etc/gatewaychef/env || echo 'STATION_LOG_DIR=/var/log/gatewaychef' >> /etc/gatewaychef/env
install -m 644 "$HOME_DIR/app/scripts/linux/gatewaychef-ports.service" /etc/systemd/system/gatewaychef-ports.service

install -m 644 "$HOME_DIR/app/scripts/linux/gatewaychef.service" /etc/systemd/system/gatewaychef.service
chmod +x "$HOME_DIR/app/scripts/linux/gatewaychef-run.sh"
ln -sf "$HOME_DIR/app/scripts/linux/gatewaychef-run.sh" /usr/local/bin/gatewaychef
systemctl daemon-reload
systemctl enable gatewaychef-ports >/dev/null
systemctl restart gatewaychef-ports || echo "!! Ports: /etc/gatewaychef/ports pruefen, dann systemctl restart gatewaychef-ports"
systemctl enable --now gatewaychef >/dev/null

echo
echo "Fertig. Weboberflaeche: http://$(hostname -I | awk '{print $1}'):5000  (Flotte: /fleet)"
echo "VPN fuer die Flotte: /etc/wireguard/ballb.conf ablegen (Workstation-Peer 172.30.100.x), dann:"
echo "  systemctl enable --now wg-quick@ballb"
echo "Mehrere Gateways: Ports in /etc/gatewaychef/ports eintragen, systemctl restart gatewaychef-ports,"
echo "  dann http://<station>:5000/station"
echo "Kommandozeile: sudo -H -u gatewaychef gatewaychef setup | fleet status | pool"
