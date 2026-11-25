"""
Is a gateway plugged in? Prints one JSON line, used by the station per port:
  {"host": "192.168.23.150", "eui": "24E124...", "device": {...}}   or   {"host": null}
Reads Node-RED /device-info (no login); a new gateway without flow is found by its web UI and
identified by a gateway API login (flow: false). Exit 0 found, 3 nothing answers.
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import gateway_lan  # noqa: E402


def probe(candidates, http=requests):
    for host in [h.strip() for h in candidates.split(",") if h.strip()]:
        try:
            resp = http.get(f"http://{host}/node-red/device-info", timeout=2)
            if resp.status_code == 200:
                info = resp.json()
                for _ in range(3):   # flow <= 1.3.0 answers concurrent requests with MAC 00:00:...
                    mac = (info.get("device") or {}).get("mac") or ""
                    if not mac or mac.replace(":", "").strip("0"):
                        break
                    time.sleep(1)
                    info = http.get(f"http://{host}/node-red/device-info", timeout=2).json()
                dev = info.get("device") or {}
                return {"host": host, "eui": (dev.get("eui") or "").upper() or None, "device": dev,
                        "sn": dev.get("sn") or dev.get("serial") or None}
        except (requests.RequestException, ValueError):
            continue
    # new gateway: no flow yet, only the web UI answers; EUI via gateway API login
    for host in [h.strip() for h in candidates.split(",") if h.strip()]:
        if gateway_lan.web_answers(host, http=http):
            ident = gateway_lan.cgi_identity(host) or {}
            return {"host": host, "eui": ident.get("eui"), "flow": False, "firmware": ident.get("firmware"),
                    "sn": ident.get("sn"),
                    "device": {}, "note": "neues Gateway ohne Drive-by-Flow" if ident else
                    "neues Gateway ohne Flow, Login fehlgeschlagen (GATEWAY_FACTORY_PASSWORD?)"}
    return {"host": None}


def main():
    out = probe(",".join(gateway_lan.candidates()))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["host"] else 3


if __name__ == "__main__":
    sys.exit(main())
