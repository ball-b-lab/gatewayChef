"""
Is a gateway plugged in? Prints one JSON line, used by the station per port:
  {"host": "192.168.23.150", "eui": "24E124...", "device": {...}}   or   {"host": null}
Reads only Node-RED /device-info (no login). Exit 0 found, 3 nothing answers.
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import gateway_lan  # noqa: E402


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
    out = probe(",".join(gateway_lan.candidates()))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["host"] else 3


if __name__ == "__main__":
    sys.exit(main())
