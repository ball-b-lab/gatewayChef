"""
Read-only checks against the gateway itself (LAN) and over the VPN.
Each returns (ok: bool, info: str).
"""
import re
import time

import requests

from services.setup.model import normalize_eui


def device_info(host, timeout=5, http=requests):
    resp = http.get(f"http://{host}/node-red/device-info", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def lora_info(host, timeout=5, http=requests):
    resp = http.get(f"http://{host}/node-red/device-info-lora", timeout=timeout)
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
                resp = http.get(f"http://{vpn_ip}/node-red/device-info", timeout=5)
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
        resp = http.get(f"http://{host}/node-red/lora/health", timeout=timeout)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return False, f"Health-Endpunkt nicht lesbar ({type(exc).__name__})"
    if data.get("lns_connected"):
        return True, f"{data.get('status')}, letzte Bestaetigung vor {data.get('seconds_since_ack')} s"
    return False, f"{data.get('status')} (seconds_since_stat={data.get('seconds_since_stat')})"
