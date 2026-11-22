#!/bin/sh
# Bring the cloud container into the gateway VPN (WireGuard), then start the app.
# Only active when WG_PRIVATE_KEY is set. Any VPN failure is logged and the app
# starts anyway (the DB API must never depend on the tunnel).
#
# Env:
#   WG_PRIVATE_KEY        private key of this peer (Coolify secret, never in git)
#   WG_ADDRESS            VPN address of this peer, default 172.30.0.20/32
#   VPN_SERVER_PUBLIC_KEY public key of the WireGuard server (same as for gateways)
#   WG_ENDPOINT           server endpoint, default 88.99.172.109:51820
#   WG_ALLOWED_IPS        routed through the tunnel, default 172.30.0.0/16
# Container needs: --cap-add=NET_ADMIN (and the wireguard kernel module on the host).

vpn_up() {
    [ -n "$WG_PRIVATE_KEY" ] || { echo "VPN: WG_PRIVATE_KEY nicht gesetzt, kein Tunnel"; return 0; }
    [ -n "$VPN_SERVER_PUBLIC_KEY" ] || { echo "VPN: VPN_SERVER_PUBLIC_KEY fehlt, kein Tunnel"; return 1; }
    addr="${WG_ADDRESS:-172.30.0.20/32}"
    endpoint="${WG_ENDPOINT:-88.99.172.109:51820}"
    allowed="${WG_ALLOWED_IPS:-172.30.0.0/16}"
    ip link del wg0 2>/dev/null
    ip link add wg0 type wireguard || { echo "VPN: wg0 nicht anlegbar (NET_ADMIN / Kernelmodul?)"; return 1; }
    keyfile=$(mktemp) && printf '%s' "$WG_PRIVATE_KEY" > "$keyfile"
    wg set wg0 private-key "$keyfile" peer "$VPN_SERVER_PUBLIC_KEY" \
        endpoint "$endpoint" allowed-ips "$allowed" persistent-keepalive 25
    rc=$?; rm -f "$keyfile"
    [ $rc -eq 0 ] || { echo "VPN: wg set fehlgeschlagen"; return 1; }
    ip address add "$addr" dev wg0 && ip link set mtu 1380 up dev wg0 || return 1
    for net in $(echo "$allowed" | tr ',' ' '); do ip route replace "$net" dev wg0 || return 1; done
    echo "VPN: wg0 $addr -> $endpoint ($allowed)"
}

vpn_up || echo "VPN: Tunnel nicht aktiv, App startet ohne VPN"
exec "$@"
