#!/usr/bin/env python3
"""
Prototype: configure a Milesight UG65 from a profile.

Default is a DRY RUN (read + diff, nothing is written).

Secrets come from environment variables (or .env), never from arguments:
  GATEWAY_PASSWORD           admin password of the gateway web UI (required)
  GATEWAY_USER               default: admin
  GATEWAY_WIFI_KEY           WLAN password to set
  GATEWAY_VPN_PRIVATE_KEY    WireGuard private key of this gateway (else: --from-db)
  VPN_SERVER_PUBLIC_KEY      public key of the WireGuard server peer

Examples:
  python scripts/gateway_autoconfig.py --vpn-ip 172.30.0.116
  python scripts/gateway_autoconfig.py --vpn-ip 172.30.0.116 --from-db --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402  (loads .env)
from services.gateway_config import (  # noqa: E402
    GatewayConfigError,
    UG65Client,
    device_vars_from_inventory,
    execute,
    format_plan,
    load_profile,
    plan,
)


def _private_key_from_db(vpn_ip):
    from db.connection import get_db_connection
    from services.provisioning_service import ProvisioningService

    conn = get_db_connection()
    try:
        return ProvisioningService(conn).fetch_vpn_key(vpn_ip)["private_key"]
    finally:
        conn.close()


def _gateway_eui(host):
    import requests
    from utils.helpers import calculate_eui

    payload = requests.get(f"http://{host}/node-red/device-info", timeout=5).json()
    device = payload.get("device", {})
    return device.get("eui") or calculate_eui(device.get("mac") or "")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=config.GATEWAY_IP)
    parser.add_argument("--profile", default="ug65-60.0.0.49")
    parser.add_argument("--vpn-ip", required=True)
    parser.add_argument("--eui", help="Gateway EUI (default: read from gateway)")
    parser.add_argument("--from-db", action="store_true", help="WireGuard private key aus gateway_inventory laden")
    parser.add_argument("--apply", action="store_true", help="Aenderungen wirklich schreiben")
    parser.add_argument("--reboot", action="store_true", help="nach --apply neu starten")
    parser.add_argument("--force-firmware", action="store_true")
    args = parser.parse_args(argv)

    password = os.getenv("GATEWAY_PASSWORD")
    if not password:
        print("GATEWAY_PASSWORD fehlt (Umgebung oder .env).", file=sys.stderr)
        return 2

    try:
        private_key = _private_key_from_db(args.vpn_ip) if args.from_db else os.getenv("GATEWAY_VPN_PRIVATE_KEY")
        device_vars = device_vars_from_inventory(
            vpn_ip=args.vpn_ip,
            private_key=private_key,
            gateway_eui=args.eui or _gateway_eui(args.host),
            wifi_key=os.getenv("GATEWAY_WIFI_KEY"),
        )
        device_vars["vpn_server_public_key"] = os.getenv("VPN_SERVER_PUBLIC_KEY")

        client = UG65Client(args.host)
        client.login(os.getenv("GATEWAY_USER", "admin"), password)
        result = plan(client, load_profile(args.profile), device_vars, skip_missing=not args.apply)
        print(format_plan(result))

        if not args.apply:
            print("\nDry-Run: nichts geschrieben. Mit --apply ausfuehren.")
            return 0 if not result["changes"] else 1

        count = execute(client, result, force_firmware=args.force_firmware)
        print(f"\n{count} Bereich(e) geschrieben und uebernommen.")
        verify = plan(client, load_profile(args.profile), device_vars)
        if verify["changes"]:
            print("!! Nach dem Schreiben weichen noch Werte ab:\n" + format_plan(verify))
            return 3
        print("Zurueckgelesen: OK.")
        if args.reboot:
            client.reboot()
            print("Neustart ausgeloest.")
        return 0
    except GatewayConfigError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
