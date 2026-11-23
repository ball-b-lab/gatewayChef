"""
Where is the gateway on the station's LAN port?

Gateways come either with a fixed factory address (192.168.1.1 / 192.168.23.150) or, once
set up by us, with eth0 on DHCP. The station serves DHCP on its gateway port (dnsmasq, see
scripts/linux/gatewaychef-dhcp@.service and ports.sh) and writes a lease file. Candidates are
tried in this order: newest DHCP leases first, then GATEWAY_LAN_CANDIDATES (or GATEWAY_IP plus
192.168.23.150). The first address whose Node-RED /device-info answers is the gateway.

Lease file: GATEWAY_DHCP_LEASES, else /var/lib/gatewaychef/dhcp-gcp<N>.leases inside a station
port namespace (GATEWAYCHEF_PORT=N), else /var/lib/gatewaychef/dhcp-lan.leases.
"""
import os
import time

import requests

LEASE_DIR = "/var/lib/gatewaychef"
DEVICE_INFO_PATH = "/node-red/device-info"
_CACHE_SECS = 20
_cache = {"host": None, "at": 0.0}


def lease_file():
    explicit = os.getenv("GATEWAY_DHCP_LEASES")
    if explicit:
        return explicit
    port = os.getenv("GATEWAYCHEF_PORT")
    return os.path.join(LEASE_DIR, f"dhcp-gcp{port}.leases" if port else "dhcp-lan.leases")


def lease_hosts(path=None):
    """IPs from a dnsmasq lease file, newest lease first. Missing file -> []."""
    path = path or lease_file()
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                # <expiry-epoch> <mac> <ip> <hostname> <client-id>
                if len(parts) >= 3 and parts[0].isdigit():
                    rows.append((int(parts[0]), parts[2]))
    except OSError:
        return []
    rows.sort(reverse=True)
    return [ip for _, ip in rows]


def static_candidates():
    raw = os.getenv("GATEWAY_LAN_CANDIDATES") or (os.getenv("GATEWAY_IP", "192.168.1.1") + ",192.168.23.150")
    return [h.strip() for h in raw.split(",") if h.strip()]


def candidates(lease_path=None):
    out = []
    for h in lease_hosts(lease_path) + static_candidates():
        if h not in out:
            out.append(h)
    return out


def answers(host, http=requests, timeout=2):
    try:
        return http.get(f"http://{host}{DEVICE_INFO_PATH}", timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def find_host(http=requests, lease_path=None, use_cache=False, timeout=2):
    """First candidate that answers; None if none does."""
    now = time.monotonic()
    if use_cache and _cache["host"] and now - _cache["at"] < _CACHE_SECS:
        return _cache["host"]
    for h in candidates(lease_path):
        if answers(h, http=http, timeout=timeout):
            _cache.update(host=h, at=now)
            return h
    _cache.update(host=None, at=0.0)
    return None


def base_url(http=requests):
    """URL for the web UI routes: detected gateway, else the first candidate (keeps old errors)."""
    host = find_host(http=http, use_cache=True) or (candidates() or ["192.168.1.1"])[0]
    return f"http://{host}"
