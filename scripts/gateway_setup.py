#!/usr/bin/env python3
"""
GatewayChef setup: ein Gateway am Arbeitsplatz -> komplett eingerichtet.

Standard ist PRUEFEN (Dry-Run): alles lesen, nichts schreiben.

  python scripts/gateway_setup.py                      # Dry-Run, VPN-IP ueber EUI aus DB
  python scripts/gateway_setup.py --new                # neues Gateway, freie VPN-IP aus Pool
  python scripts/gateway_setup.py --check              # nur Pruefungen (z. B. nach Versand)
  python scripts/gateway_setup.py --apply --serial 6223D... --iccid 8949... --sim-vendor-id 2 --client-id 10999

Backends (austauschbar, .env): INVENTORY_BACKEND=db|api, WEBSERVICE_BACKEND=ws1|ws2|off,
MILESIGHT_ENABLED, CHIRPSTACK_ENABLED. Geheimwerte nur aus .env.
Exit: 0 alles ok, 1 Dry-Run mit Aenderungen, 2 Fehler.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402,F401  (loads .env)
from services.setup.model import Gateway  # noqa: E402
from utils import gateway_lan  # noqa: E402
from services.setup.pipeline import exit_code, format_results, from_env, verdict  # noqa: E402


def find_gateway(candidates, http=None):
    """First LAN address that answers like a UG65 (Node-RED device-info). Falls back to the first one."""
    import requests
    http = http or requests
    hosts = [h.strip() for h in candidates.split(",") if h.strip()]
    for h in hosts:
        try:
            if http.get(f"http://{h}/node-red/device-info", timeout=2).status_code == 200:
                if len(hosts) > 1:
                    print(f"Gateway gefunden unter {h}")
                return h
        except requests.RequestException:
            continue
    for h in hosts:   # new gateway without our flow: only the web UI answers
        if gateway_lan.web_answers(h, http=http):
            print(f"Gateway ohne Drive-by-Flow gefunden unter {h}")
            return h
    return hosts[0]


def _live(result):
    print(format_results([result]), flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", help="Gateway-IP im LAN. Standard: erste antwortende aus GATEWAY_LAN_CANDIDATES "
                   "(kommagetrennt), sonst GATEWAY_IP und 192.168.23.150; DHCP-Leases der Station zuerst")
    p.add_argument("--profile", default=os.getenv("GATEWAY_PROFILE", "auto"))
    p.add_argument("--vpn-ip")
    p.add_argument("--new", action="store_true", help="freie VPN-IP aus dem Pool nehmen")
    p.add_argument("--serial")
    p.add_argument("--iccid")
    p.add_argument("--sim-vendor-id")
    p.add_argument("--client-id")
    p.add_argument("--client-name")
    p.add_argument("--name", help="Gateway-Name (Standard: '<x.y> <Kunde>')")
    p.add_argument("--apply", action="store_true", help="wirklich schreiben")
    p.add_argument("--check", action="store_true", help="nur pruefen, nichts anlegen")
    p.add_argument("--reboot", action="store_true")
    p.add_argument("--force-firmware", action="store_true")
    p.add_argument("--vpn-wait", type=int, default=90, help="Sekunden auf VPN warten")
    p.add_argument("--wlan", action="store_true",
                   help="dieser PC haengt im WLAN des Gateways: beim Umbenennen des WLAN automatisch mitwechseln")
    p.add_argument("--live", action="store_true",
                   help="jeden Schritt sofort ausgeben und am Ende eine @@RESULT-Zeile (fuer die Station)")
    a = p.parse_args(argv)

    gw = Gateway(vpn_ip=a.vpn_ip, serial_number=a.serial, sim_iccid=a.iccid, sim_vendor_id=a.sim_vendor_id,
                 client_id=a.client_id, client_name=a.client_name, name=a.name)
    host = a.host or find_gateway(",".join(gateway_lan.candidates()))
    try:
        pipeline = from_env(host, a.profile, vpn_wait_secs=a.vpn_wait, on_step=_live if a.live else None)
        pipeline.wlan_follow = a.wlan
    except ValueError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    results = pipeline.run(gw, apply=a.apply, allocate_new=a.new, force_firmware=a.force_firmware,
                           reboot=a.reboot, only_check=a.check)
    code = exit_code(results)
    if a.live:
        print(f"\nGateway: EUI {gw.eui} · VPN {gw.vpn_ip} · SN {gw.serial_number} · {gw.name}")
        print("@@RESULT " + json.dumps({
            "code": code, "eui": gw.eui, "vpn_ip": gw.vpn_ip, "serial": gw.serial_number, "name": gw.name,
            "verdict": verdict(results, gw, applied=a.apply and not a.check),
            "steps": [{"step": r.step, "status": r.status, "detail": r.detail} for r in results]},
            ensure_ascii=False), flush=True)
    else:
        print(format_results(results, gw))
    if not a.apply and code == 1:
        print("\nDry-Run: nichts geschrieben. Mit --apply ausfuehren.")
    return code


if __name__ == "__main__":
    sys.exit(main())
