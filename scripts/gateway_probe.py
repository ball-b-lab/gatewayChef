"""
Is a gateway plugged in? Prints one JSON line, used by the station per port:
  {"host": "192.168.23.150", "eui": "24E124...", "device": {...}}   or   {"host": null}
Reads only Node-RED /device-info (no login). Exit 0 found, 3 nothing answers.
"""
import json
import os
import sys

import requests


def probe(candidates, http=requests):
    for host in [h.strip() for h in candidates.split(",") if h.strip()]:
        try:
            resp = http.get(f"http://{host}/node-red/device-info", timeout=2)
            if resp.status_code == 200:
                info = resp.json()
                dev = info.get("device") or {}
                return {"host": host, "eui": (dev.get("eui") or "").upper() or None, "device": dev}
        except (requests.RequestException, ValueError):
            continue
    return {"host": None}


def main():
    cands = os.getenv("GATEWAY_LAN_CANDIDATES") or "192.168.23.150,192.168.1.1"
    out = probe(cands)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["host"] else 3


if __name__ == "__main__":
    sys.exit(main())
