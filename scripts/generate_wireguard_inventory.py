#!/usr/bin/env python3
import argparse
import csv
import ipaddress
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate WireGuard peers and SQL inventory rows for a VPN IP range."
    )
    parser.add_argument(
        "--start-ip",
        required=True,
        help="First VPN IP to generate, e.g. 172.30.1.1",
    )
    parser.add_argument(
        "--end-ip",
        required=True,
        help="Last VPN IP to generate, e.g. 172.30.1.254",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated files.",
    )
    parser.add_argument(
        "--status",
        default="FREE",
        help="Initial gateway_inventory.status_overall value. Default: FREE",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Use ON CONFLICT (vpn_ip) DO NOTHING in SQL output.",
    )
    return parser.parse_args()


def ensure_wg_available():
    try:
        subprocess.run(
            ["wg", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit("ERROR: 'wg' command not found. Install WireGuard tools first.") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ERROR: 'wg --version' failed: {exc.stderr.strip()}") from exc


def run_wg(command, stdin_text=None):
    result = subprocess.run(
        command,
        input=stdin_text,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def generate_keypair():
    private_key = run_wg(["wg", "genkey"])
    public_key = run_wg(["wg", "pubkey"], stdin_text=private_key + "\n")
    return private_key, public_key


def derive_wifi_ssid(vpn_ip):
    parts = str(vpn_ip).split(".")
    return f"bbdbmon_{parts[-2]}.{parts[-1]}"


def sql_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def iter_ip_range(start_ip, end_ip):
    start = ipaddress.ip_address(start_ip)
    end = ipaddress.ip_address(end_ip)

    if start.version != 4 or end.version != 4:
        raise SystemExit("ERROR: only IPv4 addresses are supported.")
    if int(start) > int(end):
        raise SystemExit("ERROR: --start-ip must be <= --end-ip.")

    current = int(start)
    last = int(end)
    while current <= last:
        yield ipaddress.ip_address(current)
        current += 1


def build_sql(rows, status, skip_existing):
    values = []
    for row in rows:
        values.append(
            "("
            + ", ".join(
                [
                    sql_quote(row["vpn_ip"]),
                    sql_quote(row["private_key"]),
                    sql_quote(row["wifi_ssid"]),
                    sql_quote(status),
                ]
            )
            + ")"
        )

    conflict = "\nON CONFLICT (vpn_ip) DO NOTHING" if skip_existing else ""
    return (
        "INSERT INTO gateway_inventory (vpn_ip, private_key, wifi_ssid, status_overall)\n"
        "VALUES\n  "
        + ",\n  ".join(values)
        + conflict
        + ";\n"
    )


def build_server_peers(rows):
    blocks = []
    for row in rows:
        blocks.append(
            "\n".join(
                [
                    f"# {row['vpn_ip']} {row['wifi_ssid']}",
                    "[Peer]",
                    f"PublicKey = {row['public_key']}",
                    f"AllowedIPs = {row['vpn_ip']}/32",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["vpn_ip", "wifi_ssid", "private_key", "public_key"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()
    ensure_wg_available()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for vpn_ip in iter_ip_range(args.start_ip, args.end_ip):
        private_key, public_key = generate_keypair()
        rows.append(
            {
                "vpn_ip": str(vpn_ip),
                "wifi_ssid": derive_wifi_ssid(vpn_ip),
                "private_key": private_key,
                "public_key": public_key,
            }
        )

    sql_path = output_dir / "gateway_inventory.sql"
    peers_path = output_dir / "wireguard_peers.conf"
    csv_path = output_dir / "peer_inventory.csv"

    sql_path.write_text(build_sql(rows, args.status, args.skip_existing), encoding="utf-8")
    peers_path.write_text(build_server_peers(rows), encoding="utf-8")
    write_csv(csv_path, rows)

    print(f"Generated {len(rows)} peers.")
    print(f"SQL: {sql_path}")
    print(f"Server peers: {peers_path}")
    print(f"Inventory CSV: {csv_path}")
    print("WARNING: output contains private keys. Store and transport carefully.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        message = stderr or str(exc)
        print(f"ERROR: WireGuard command failed: {message}", file=sys.stderr)
        sys.exit(1)
