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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402,F401  (loads .env)
from services.setup.model import Gateway  # noqa: E402
from services.setup.pipeline import exit_code, format_results, from_env  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default=os.getenv("GATEWAY_IP", "192.168.1.1"))
    p.add_argument("--profile", default=os.getenv("GATEWAY_PROFILE", "ug65-60.0.0.49"))
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
    a = p.parse_args(argv)

    gw = Gateway(vpn_ip=a.vpn_ip, serial_number=a.serial, sim_iccid=a.iccid, sim_vendor_id=a.sim_vendor_id,
                 client_id=a.client_id, client_name=a.client_name, name=a.name)
    try:
        pipeline = from_env(a.host, a.profile, vpn_wait_secs=a.vpn_wait)
    except ValueError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    results = pipeline.run(gw, apply=a.apply, allocate_new=a.new, force_firmware=a.force_firmware,
                           reboot=a.reboot, only_check=a.check)
    print(format_results(results, gw))
    code = exit_code(results)
    if not a.apply and code == 1:
        print("\nDry-Run: nichts geschrieben. Mit --apply ausfuehren.")
    return code


if __name__ == "__main__":
    sys.exit(main())
