#!/usr/bin/env python3
import argparse
import csv
import ipaddress
import subprocess
import sys
from pathlib import Path

PROFILE_DEFAULTS = {
    "gateway": {
        "peer_name_prefix": "ug65",
        "extra_allowed_ip": "192.168.1.0/24",
        "persistent_keepalive": 25,
        "inventory_enabled": True,
        "inventory_status": "FREE",
    },
    "workstation": {
        "peer_name_prefix": "ws",
        "extra_allowed_ip": "",
        "persistent_keepalive": 25,
        "inventory_enabled": False,
        "inventory_status": "RESERVED",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate WireGuard peers and SQL inventory rows for one or more VPN IP ranges."
    )
    parser.add_argument(
        "--profile-range",
        dest="profile_ranges",
        action="append",
        required=True,
        help=(
            "Profile plus IP range in the form PROFILE:START-END, e.g. "
            "gateway:172.30.1.1-172.30.1.254 or workstation:172.30.100.1-172.30.100.254. "
            "Repeat for multiple blocks."
        ),
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated files.",
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


def iter_requested_rows(profile_range_specs):
    seen = set()
    for spec in profile_range_specs:
        profile_name, sep, range_part = spec.partition(":")
        if not sep or not profile_name or not range_part:
            raise SystemExit(
                "ERROR: invalid --profile-range. Expected PROFILE:START-END, "
                "e.g. gateway:172.30.1.1-172.30.1.254."
            )
        profile_name = profile_name.strip().lower()
        if profile_name not in PROFILE_DEFAULTS:
            valid = ", ".join(sorted(PROFILE_DEFAULTS))
            raise SystemExit(f"ERROR: unknown profile '{profile_name}'. Valid profiles: {valid}")

        start_ip, sep, end_ip = range_part.partition("-")
        if not sep or not start_ip or not end_ip:
            raise SystemExit(
                f"ERROR: invalid range in '{spec}'. Expected format PROFILE:START-END."
            )
        for vpn_ip in iter_ip_range(start_ip.strip(), end_ip.strip()):
            value = str(vpn_ip)
            if value in seen:
                raise SystemExit(f"ERROR: duplicate IP generated across profile ranges: {value}")
            seen.add(value)
            yield profile_name, vpn_ip


def build_sql(rows, skip_existing):
    values = []
    for row in rows:
        if not row["inventory_enabled"]:
            continue
        values.append(
            "("
            + ", ".join(
                [
                    sql_quote(row["vpn_ip"]),
                    sql_quote(row["private_key"]),
                    sql_quote(row["wifi_ssid"]),
                    sql_quote(row["inventory_status"]),
                ]
            )
            + ")"
        )

    if not values:
        return "-- No gateway_inventory rows generated for the selected profiles.\n"

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
        last_octet = row["vpn_ip"].split(".")[-1]
        allowed_ips = [f"{row['vpn_ip']}/32"]
        if row["extra_allowed_ip"]:
            allowed_ips.append(row["extra_allowed_ip"])
        blocks.append(
            "\n".join(
                [
                    "[Peer]",
                    f"# {row['peer_name_prefix']}_{last_octet}",
                    f"# profile: {row['profile']}",
                    f"PublicKey = {row['public_key']}",
                    f"AllowedIPs = {', '.join(allowed_ips)}",
                    f"PersistentKeepalive = {row['persistent_keepalive']}",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "profile",
                "vpn_ip",
                "wifi_ssid",
                "private_key",
                "public_key",
                "inventory_enabled",
                "inventory_status",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()
    ensure_wg_available()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for profile_name, vpn_ip in iter_requested_rows(args.profile_ranges):
        defaults = PROFILE_DEFAULTS[profile_name]
        private_key, public_key = generate_keypair()
        rows.append(
            {
                "profile": profile_name,
                "vpn_ip": str(vpn_ip),
                "wifi_ssid": derive_wifi_ssid(vpn_ip),
                "private_key": private_key,
                "public_key": public_key,
                "peer_name_prefix": defaults["peer_name_prefix"],
                "extra_allowed_ip": defaults["extra_allowed_ip"],
                "persistent_keepalive": defaults["persistent_keepalive"],
                "inventory_enabled": defaults["inventory_enabled"],
                "inventory_status": defaults["inventory_status"],
            }
        )

    sql_path = output_dir / "gateway_inventory.sql"
    peers_path = output_dir / "wg0_extension.conf"
    csv_path = output_dir / "peer_inventory.csv"

    sql_path.write_text(build_sql(rows, args.skip_existing), encoding="utf-8")
    peers_path.write_text(build_server_peers(rows), encoding="utf-8")
    write_csv(csv_path, rows)

    print(f"Generated {len(rows)} peers.")
    print(f"SQL: {sql_path}")
    print(f"WG config extension: {peers_path}")
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
