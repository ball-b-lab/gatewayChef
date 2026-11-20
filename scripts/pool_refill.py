#!/usr/bin/env python3
"""
Keep the VPN pool (gateway_inventory, status FREE) filled.

Two phases, so no gateway can get a key the VPN server does not know yet:

  1. check / generate
       python scripts/pool_refill.py                         # only report free/total
       python scripts/pool_refill.py --generate               # if free < --min-free: write files
     writes to --out (default ./out/pool-<timestamp>/, mode 600):
       wg0_peers.conf     [Peer] blocks for the VPN server
       peer_inventory.csv rows for gateway_inventory (contains private keys)

  2. after the peers are live on the VPN server:
       python scripts/pool_refill.py --import ./out/pool-<timestamp>

Uses the same inventory backend as the setup (INVENTORY_BACKEND / cloud API),
so it runs on the operator PC without DB credentials. Exit: 0 ok, 1 pool low, 2 error.
"""
import argparse
import base64
import csv
import ipaddress
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402,F401  (loads .env)
from services.setup.factory import build_inventory  # noqa: E402
from services.setup.model import SetupError  # noqa: E402
from utils.helpers import derive_wifi_ssid  # noqa: E402

DEFAULT_RANGES = "172.30.1.1-172.30.9.254"
CSV_FIELDS = ["profile", "vpn_ip", "wifi_ssid", "private_key", "public_key", "inventory_enabled", "inventory_status"]


def generate_keypair():
    """WireGuard keys (Curve25519), no wg binary needed."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    private = X25519PrivateKey.generate()
    raw = serialization.Encoding.Raw
    priv = private.private_bytes(raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = private.public_key().public_bytes(raw, serialization.PublicFormat.Raw)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def iter_ranges(spec):
    for part in spec.split(","):
        start, _, end = part.strip().partition("-")
        lo, hi = ipaddress.IPv4Address(start), ipaddress.IPv4Address(end or start)
        if hi < lo:
            raise SetupError(f"Bereich falsch herum: {part}")
        for n in range(int(lo), int(hi) + 1):
            ip = ipaddress.IPv4Address(n)
            if ip.packed[-1] not in (0, 255):
                yield str(ip)


def pick_free_ips(ranges, used, count):
    used = set(used)
    picked = []
    for ip in iter_ranges(ranges):
        if ip not in used:
            picked.append(ip)
            if len(picked) == count:
                break
    return picked


def build_rows(ips, keygen=generate_keypair):
    rows = []
    for ip in ips:
        priv, pub = keygen()
        rows.append({"profile": "gateway", "vpn_ip": ip, "wifi_ssid": derive_wifi_ssid(ip), "private_key": priv,
                     "public_key": pub, "inventory_enabled": "true", "inventory_status": "FREE"})
    return rows


def server_peers(rows):
    # Only the /32 per peer: WireGuard AllowedIPs must be unique, a shared
    # 192.168.1.0/24 would always route to the last peer only.
    return "\n".join(
        f"[Peer]\n# ug65_{r['vpn_ip'].split('.', 2)[2]}\nPublicKey = {r['public_key']}\n"
        f"AllowedIPs = {r['vpn_ip']}/32\nPersistentKeepalive = 25\n"
        for r in rows)


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def rows_to_csv(rows):
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ranges", default=os.getenv("POOL_RANGES", DEFAULT_RANGES),
                    help="Gateway-Bereiche, kommagetrennt (Standard POOL_RANGES oder %(default)s)")
    ap.add_argument("--min-free", type=int, default=int(os.getenv("POOL_MIN_FREE", "20")))
    ap.add_argument("--batch", type=int, default=int(os.getenv("POOL_BATCH", "50")))
    ap.add_argument("--generate", action="store_true", help="Dateien erzeugen, wenn der Pool zu klein ist")
    ap.add_argument("--force", action="store_true", help="mit --generate: auch erzeugen, wenn genug frei ist")
    ap.add_argument("--out", help="Zielordner fuer --generate")
    ap.add_argument("--import", dest="import_dir", help="Ordner aus --generate in die DB uebernehmen")
    args = ap.parse_args(argv)

    try:
        inventory = build_inventory()
        if args.import_dir:
            csv_path = Path(args.import_dir) / "peer_inventory.csv"
            result = inventory.import_csv(csv_path.read_text(encoding="utf-8"))
            print(f"Importiert: {result}")
            return 0

        status = inventory.pool_status()
        free, total = status["free"], status["total"]
        low = free < args.min_free
        print(f"VPN-Pool: {free} frei von {total} (Minimum {args.min_free}){'  -> ZU WENIG' if low else ''}")
        if not args.generate or not (low or args.force):
            return 1 if low else 0

        ips = pick_free_ips(args.ranges, status["vpn_ips"], args.batch)
        if not ips:
            raise SetupError(f"Bereich {args.ranges} ist voll, neuen Bereich in POOL_RANGES eintragen.")
        out = Path(args.out or f"out/pool-{datetime.now():%Y%m%d-%H%M%S}")
        out.mkdir(parents=True, exist_ok=True)
        rows = build_rows(ips)
        write_private(out / "wg0_peers.conf", server_peers(rows))
        write_private(out / "peer_inventory.csv", rows_to_csv(rows))
        print(f"{len(rows)} Plaetze erzeugt: {ips[0]} .. {ips[-1]}")
        print(f"1. {out / 'wg0_peers.conf'} an /etc/wireguard/wg0.conf auf dem VPN-Server anhaengen,")
        print("   dann: wg syncconf wg0 <(wg-quick strip wg0)")
        print(f"2. python scripts/pool_refill.py --import {out}")
        print("Die Dateien enthalten Private Keys. Nach dem Import loeschen.")
        return 0
    except (SetupError, OSError, KeyError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
