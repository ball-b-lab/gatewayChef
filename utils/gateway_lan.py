"""
Where is the gateway on the station's LAN port?

Gateways come either with a fixed factory address (192.168.1.1 / 192.168.23.150) or, once
set up by us, with eth0 on DHCP. The station serves DHCP on its gateway port (dnsmasq, see
scripts/linux/gatewaychef-dhcp@.service and ports.sh) and writes a lease file. Candidates are
tried in this order: newest DHCP leases first, then GATEWAY_LAN_CANDIDATES (or GATEWAY_IP plus
192.168.23.150). The first address whose Node-RED /device-info answers is the gateway; a new gateway
without our flow is found by its web UI instead (identity then via the gateway API login).

Lease file: GATEWAY_DHCP_LEASES, else /var/lib/gatewaychef/dhcp-gcp<N>.leases inside a station
port namespace (GATEWAYCHEF_PORT=N), else /var/lib/gatewaychef/dhcp-lan.leases.
"""
import os
import time

import requests
import urllib3

# gateways with newer firmware redirect to HTTPS with a self-signed certificate
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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


def _tls(http):
    """Self-signed HTTPS on newer firmware: no certificate check (only with real requests)."""
    return {"verify": False} if http is requests or isinstance(http, requests.Session) else {}


def web_answers(host, http=requests, timeout=2):
    """Factory UG65 (no Node-RED flow yet): its web UI answers on http://<host>/."""
    try:
        # newer firmware redirects to HTTPS with a self-signed certificate
        resp = http.get(f"http://{host}/", timeout=timeout, **_tls(http))
        if resp.status_code != 200:
            return False
        if any(k in resp.text.lower() for k in ("milesight", "ursalink", "ug65", "ug67")):
            return True
        # page without a brand word: assume it is a gateway and try to log in and read a value
        return bool(_tls(http)) and cgi_login(host) is not None
    except (requests.RequestException, ValueError):
        return False


def gateway_passwords():
    """Our admin password first, then the factory one (new gateways still have it)."""
    out = []
    for pw in (os.getenv("GATEWAY_PASSWORD", ""), os.getenv("GATEWAY_FACTORY_PASSWORD", "password")):
        if pw and pw not in out:
            out.append(pw)
    return out


def cgi_login(host, client_factory=None):
    """Logged-in UG65Client (our password, then factory) or None."""
    from services import gateway_config as gc
    user = os.getenv("GATEWAY_USER", "admin")
    for pw in gateway_passwords():
        client = (client_factory or (lambda h: gc.UG65Client(h, timeout=8)))(host)
        try:
            client.login(user, pw)
            return client
        except gc.GatewayConfigError:
            continue
    return None


def cgi_identity(host, client_factory=None):
    """EUI (packet forwarder gateway_id) and firmware via the gateway API: {"eui", "firmware"} or None."""
    from services import gateway_config as gc
    client = cgi_login(host, client_factory)
    if not client:
        return None
    try:
        conf = client.get("yruo_loragw", "general_conf")
    except gc.GatewayConfigError:
        return None
    eui = ((conf[0] if conf else {}).get("value") or {}).get("gateway_id")
    return {"eui": (eui or "").upper() or None, "firmware": client.firmware}


def answers(host, http=requests, timeout=2):
    try:
        return http.get(f"http://{host}{DEVICE_INFO_PATH}", timeout=timeout, **_tls(http)).status_code == 200
    except requests.RequestException:
        return False


def find_host(http=requests, lease_path=None, use_cache=False, timeout=2):
    """First candidate that answers; None if none does."""
    now = time.monotonic()
    if use_cache and _cache["host"] and now - _cache["at"] < _CACHE_SECS:
        return _cache["host"]
    cands = candidates(lease_path)
    for check in (answers, web_answers):   # with our flow first, then a factory gateway without flow
        for h in cands:
            if check(h, http=http, timeout=timeout):
                _cache.update(host=h, at=now)
                return h
    _cache.update(host=None, at=0.0)
    return None


def base_url(http=requests):
    """URL for the web UI routes: detected gateway, else the first candidate (keeps old errors)."""
    host = find_host(http=http, use_cache=True) or (candidates() or ["192.168.1.1"])[0]
    return f"http://{host}"
