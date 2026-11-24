"""
Read-only checks against the gateway itself (LAN) and over the VPN.
Each returns (ok: bool, info: str).
"""
import re
import time

import requests

from services.setup.model import normalize_eui
from utils.gateway_lan import _tls


def zero_mac(info):
    """Node-RED device-info flow (<= 1.3.0; fixed in 1.3.1) keeps the MAC in flow context and clears it after each
    answer; with two requests at once one of them gets 00:00:00:00:00:00. Treat that as transient."""
    mac = str(((info or {}).get("device") or {}).get("mac") or "")
    return bool(mac) and not mac.replace(":", "").strip("0")


def device_info(host, timeout=5, http=requests, tries=4, sleep=time.sleep):
    for attempt in range(tries):
        resp = http.get(f"http://{host}/node-red/device-info", timeout=timeout, **_tls(http))
        resp.raise_for_status()
        info = resp.json()
        if not zero_mac(info) or attempt == tries - 1:
            return info
        sleep(1.0 + attempt)
    return info


def lora_info(host, timeout=5, http=requests):
    resp = http.get(f"http://{host}/node-red/device-info-lora", timeout=timeout, **_tls(http))
    resp.raise_for_status()
    return resp.json()


def check_wireguard_up(info, vpn_ip):
    wg = ((info.get("device") or {}).get("interfaces") or {}).get("wg0") or {}
    if not wg.get("up"):
        return False, "wg0 ist nicht aktiv"
    if wg.get("ip") != vpn_ip:
        return False, f"wg0 hat IP {wg.get('ip')}, erwartet {vpn_ip}"
    return True, f"wg0 aktiv mit {vpn_ip}"


def check_cellular(info):
    cell = ((info.get("device") or {}).get("interfaces") or {}).get("cellular0") or {}
    if cell.get("up") and cell.get("ip"):
        primary = "" if cell.get("primary") else " (nicht primaer, LAN aktiv)"
        return True, f"Mobilfunk verbunden, IP {cell['ip']}{primary}"
    return False, "Mobilfunk ohne IP (SIM/APN/Antenne pruefen)"


def check_lns_connected(lora, lns_address):
    for serv in lora.get("servs") or []:
        if serv.get("servAddr") == lns_address:
            if serv.get("servEnabled") and serv.get("connected") == 1:
                return True, f"Packet Forwarder verbunden mit {lns_address}"
            return False, f"{lns_address} konfiguriert, aber nicht verbunden"
    return False, f"kein Packet-Forwarder-Ziel {lns_address}"


def check_vpn_reachable(vpn_ip, expected_eui, proxy_url="", proxy_token="", wait_secs=60, interval=5, http=requests, sleep=time.sleep):
    """End-to-end: is THIS gateway reachable through the tunnel?

    Direct: GET http://<vpn_ip>/node-red/device-info from this machine (needs
    the operator to be in the VPN). Proxy: the cloud gatewayChef does the
    request from inside the VPN (VPN_PING_PROVIDER_URL). The EUI in the answer
    must match -> catches duplicate VPN IPs / wrong keys, not just "something answers".
    """
    deadline_tries = max(1, int(wait_secs / interval) + 1)
    last = "keine Antwort"
    for attempt in range(deadline_tries):
        try:
            if proxy_url:
                headers = {"X-Ping-Service-Token": proxy_token} if proxy_token else {}
                resp = http.post(f"{proxy_url.rstrip('/')}/api/network/gateway-health", json={"host": vpn_ip},
                                 headers=headers, timeout=8)
                payload = resp.json() or {}
                data = payload.get("data") or {}
                message = ((payload.get("error") or {}).get("message")) or ""
                if resp.status_code == 200 and data.get("ok"):
                    return True, f"ueber VPN erreichbar (Cloud-Proxy, Versuch {attempt + 1})"
                # The proxy reached the gateway, which answered with an HTTP error
                # (e.g. 503 from its own health flow): the tunnel works.
                if re.fullmatch(r"Gateway Health Fehler \d{3}", message):
                    return True, f"ueber VPN erreichbar (Cloud-Proxy, Gateway antwortet {message[-3:]})"
                last = message[:120] or f"Proxy HTTP {resp.status_code}"
            else:
                resp = http.get(f"http://{vpn_ip}/node-red/device-info", timeout=5, **_tls(http))
                eui = normalize_eui(((resp.json() or {}).get("device") or {}).get("eui"))
                if eui == normalize_eui(expected_eui):
                    return True, f"ueber VPN erreichbar, EUI bestaetigt (Versuch {attempt + 1})"
                last = f"unter {vpn_ip} antwortet ein anderes Geraet (EUI {eui})"
                return False, last
        except (requests.RequestException, ValueError) as exc:
            last = type(exc).__name__
        if attempt < deadline_tries - 1:
            sleep(interval)
    return False, f"{vpn_ip} ueber VPN nicht erreichbar ({last})"


def check_lora_health(host, timeout=5, http=requests):
    """Node-RED health flow on the gateway (own view of the LNS link)."""
    try:
        resp = http.get(f"http://{host}/node-red/lora/health", timeout=timeout, **_tls(http))
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return False, f"Health-Endpunkt nicht lesbar ({type(exc).__name__})"
    if data.get("lns_connected"):
        return True, f"{data.get('status')}, letzte Bestaetigung vor {data.get('seconds_since_ack')} s"
    return False, f"{data.get('status')} (seconds_since_stat={data.get('seconds_since_stat')})"


def _status_items(host, since=None, timeout=5, http=requests):
    url = f"http://{host}/node-red/status" + (f"?since={since}" if since is not None else "")
    data = http.get(url, timeout=timeout).json()
    return data.get("latest_seq") or 0, data.get("items") or []


def _kind(item):
    text = str(item.get("payload") or "")
    if '"rxpk"' in text:
        return "rxpk"
    if '"stat"' in text:
        return "stat"
    return None


def _driveby_health(host, http, timeout=5):
    """Flow >= 1.1.0 (UDP source) exposes /node-red/driveby/health; None for older flows."""
    try:
        resp = http.get(f"http://{host}/node-red/driveby/health", timeout=timeout, **_tls(http))
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("source") else None


def _check_driveby_udp(host, health, wait_secs, need_rxpk, interval, http, sleep, clock):
    start_rx = (health.get("counts") or {}).get("rxpk", 0)
    deadline = clock() + wait_secs
    while True:
        stat_age = health.get("seconds_since_stat")
        rx_now = (health.get("counts") or {}).get("rxpk", 0)
        stat_ok = stat_age is not None and stat_age < 65
        if stat_ok and rx_now > start_rx:
            return True, f"UDP-Empfang ok (stat vor {stat_age}s), {rx_now - start_rx} neue Funkpaket(e)"
        if clock() >= deadline:
            break
        sleep(interval)
        health = _driveby_health(host, http) or health
    if not stat_ok:
        return False, (f"keine stat-Meldung per UDP (zuletzt: {stat_age}s): 3. Ziel 127.0.0.1:1702 im Packet "
                       "Forwarder fehlt? (Patch driveby-udp-forward)")
    msg = f"UDP-Empfang ok (stat vor {stat_age}s), aber kein neues Funkpaket: LoRa-Testsender senden lassen"
    return (False if need_rxpk else None), msg


def check_driveby(host, wait_secs=90, need_rxpk=False, interval=5, http=requests, sleep=None, clock=None):
    """
    Drive-by data path on the gateway: packet-forwarder log -> Node-RED tail
    -> filter -> /node-red/status buffer.

    Two stages, waits for NEW entries only (old buffer content proves nothing):
      stat  arrives every stat_interval (30 s) without any LoRa device -> log parsing works
      rxpk  needs a LoRa device sending nearby -> uplinks reach the buffer
    Returns (ok, detail); ok None = parsing works but no uplink seen (warn).
    """
    import time as _t
    sleep = sleep or _t.sleep
    clock = clock or _t.monotonic
    health = _driveby_health(host, http)
    if health is not None:
        return _check_driveby_udp(host, health, wait_secs, need_rxpk, interval, http, sleep, clock)
    try:
        start_seq, _ = _status_items(host, http=http)
    except (requests.RequestException, ValueError) as exc:
        return False, f"/node-red/status nicht lesbar ({type(exc).__name__}): Drive-by-Flow fehlt?"
    seen = {"stat": 0, "rxpk": 0}
    deadline = clock() + wait_secs
    since = start_seq
    while True:
        try:
            since, items = _status_items(host, since=since, http=http)
        except (requests.RequestException, ValueError):
            items = []
        for item in items:
            kind = _kind(item)
            if kind:
                seen[kind] += 1
        if seen["rxpk"] and seen["stat"]:
            return True, f"Log-Auswertung ok, {seen['rxpk']} Funkpaket(e) empfangen"
        if clock() >= deadline:
            break
        sleep(interval)
    if seen["rxpk"]:
        return True, f"{seen['rxpk']} Funkpaket(e) empfangen (kein stat im Zeitfenster)"
    if seen["stat"]:
        msg = "Log-Auswertung ok (stat), aber kein Funkpaket: LoRa-Testsender in der Naehe senden lassen"
        return (False if need_rxpk else None), msg
    return False, (f"keine neuen Eintraege in {wait_secs}s: Log-Format oder Pfad geaendert? "
                   "(Flow erwartet 'JSON up 0:' in /etc/urlog/lora-pkt-fwd.log)")
