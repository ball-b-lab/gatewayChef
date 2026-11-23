"""Statistics for the single-gateway view: ChirpStack metrics and the VPN peer entry."""
import datetime as dt
import os

import requests

from config import CHIRPSTACK_API_TOKEN, CHIRPSTACK_URL

PEERS_URL = os.getenv("VPN_PEERS_URL", "http://172.30.0.1:8787/peers.json")


def _series(metric):
    ds = (metric or {}).get("datasets") or []
    return {"timestamps": (metric or {}).get("timestamps") or [],
            "values": [sum(v or 0 for v in col) for col in zip(*[d.get("data") or [] for d in ds])] if ds else []}


def chirpstack(eui, days=1, http=requests):
    """{last_seen, rx, tx, rx_per_freq} or {error}. Hourly for 1 day, daily for 7."""
    if not eui:
        return {"error": "keine EUI in der Datenbank"}
    if not CHIRPSTACK_API_TOKEN:
        return {"error": "ChirpStack nicht konfiguriert"}
    head = {"Authorization": f"Bearer {CHIRPSTACK_API_TOKEN}"}
    base = f"{CHIRPSTACK_URL.rstrip('/')}/api/gateways/{eui}"
    try:
        g = http.get(base, headers=head, timeout=8)
        if g.status_code == 404:
            return {"error": "Gateway nicht in ChirpStack"}
        g.raise_for_status()
        end = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        q = {"start": (end - dt.timedelta(days=days)).isoformat().replace("+00:00", "Z"),
             "end": end.isoformat().replace("+00:00", "Z"), "aggregation": "HOUR" if days == 1 else "DAY"}
        m = http.get(base + "/metrics", headers=head, params=q, timeout=15)
        m.raise_for_status()
        m = m.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": f"ChirpStack: {exc}"}
    freq = {d.get("label"): sum(v or 0 for v in d.get("data") or [])
            for d in (m.get("rxPacketsPerFreq") or {}).get("datasets") or []}
    meta = (g.json().get("gateway") or {}).get("metadata") or {}
    return {"last_seen": g.json().get("lastSeenAt"), "rx": _series(m.get("rxPackets")), "tx": _series(m.get("txPackets")),
            "rx_per_freq": dict(sorted(freq.items())), "metadata": meta, "aggregation": q["aggregation"]}


def vpn_peer(ip, http=requests):
    try:
        r = http.get(PEERS_URL, timeout=(2, 5))
        r.raise_for_status()
        doc = r.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": f"VPN-Server: {exc}"}
    peer = next((p for p in doc.get("peers", []) if p.get("ip") == ip), None)
    return dict(peer, generated=doc.get("generated")) if peer else {"error": "kein VPN-Peer mit dieser IP"}
