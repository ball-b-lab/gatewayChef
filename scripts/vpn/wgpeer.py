#!/usr/bin/env python3
"""wgpeer - single tool to manage peers of the gateway VPN server (wg0).

Replaces WireGuard UI. wg0.conf stays the one source of truth; every change:
  1. renders the new file, 2. shows a diff (keys redacted),
  3. only with --apply: backup, atomic write, `wg syncconf` (no tunnel restart).

Usage (on the VPN server, as root):
  wgpeer list [--range R] [--all]    peers ever seen (--all: incl. never-connected pool)
  wgpeer free [--range R]            free IPs per range
  wgpeer add NAME --pubkey K [--range R | --ip IP] [--apply]
  wgpeer remove IP [--apply]
  wgpeer rename IP NAME [--apply]
  wgpeer normalize [--apply]         sort, one name comment, drop 192.168.1.0/24
  wgpeer seen                        merge last handshakes into the history file

Ranges: infra 172.30.0.2-99 (servers, people, cloud) | gw 172.30.0.100-254,
172.30.1.x, 172.30.2.x (gateways) | station 172.30.100.x (workstations).
"""
import argparse
import difflib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time

CONF = os.environ.get("WGPEER_CONF", "/etc/wireguard/wg0.conf")
IFACE = os.environ.get("WGPEER_IFACE", "wg0")
SEEN = os.environ.get("WGPEER_SEEN", "/var/lib/wgpeer/lastseen.json")
DROP_NETS = {"192.168.1.0/24"}  # gateway LAN, ambiguous on 559 peers, not needed server-side


def _hosts(a, b):
    return [str(ipaddress.ip_address(i)) for i in range(int(ipaddress.ip_address(a)), int(ipaddress.ip_address(b)) + 1)]


RANGES = {
    "infra": _hosts("172.30.0.2", "172.30.0.99"),
    "gw": _hosts("172.30.0.100", "172.30.0.254") + _hosts("172.30.1.1", "172.30.1.254") + _hosts("172.30.2.1", "172.30.2.254"),
    "station": _hosts("172.30.100.1", "172.30.100.254"),
}
KEY_RE = re.compile(r"^\s*(PrivateKey|PresharedKey|PublicKey)\s*=.*$", re.M)


class Peer:
    def __init__(self):
        self.name, self.fields, self.comments = "", [], []

    def get(self, key):
        return next((v for k, v in self.fields if k == key), None)

    def set(self, key, value):
        for i, (k, _) in enumerate(self.fields):
            if k == key:
                self.fields[i] = (key, value)
                return
        self.fields.append((key, value))

    @property
    def ip(self):
        for net in (self.get("AllowedIPs") or "").split(","):
            net = net.strip()
            if net.endswith("/32"):
                return net[:-3]
        return ""

    def render(self):
        out = ["[Peer]", f"# {self.name}" if self.name else "# (ohne Name)"]
        out += [f"{k} = {v}" for k, v in self.fields]
        return "\n".join(out)


def parse(text):
    """Returns (interface_lines, peers). Name = last short '# x' comment or UI '# Name:' line."""
    iface, peers, cur, pending = [], [], None, []
    in_iface = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[Interface]":
            in_iface, cur, pending = True, None, []
            iface.append(line)
            continue
        if line == "[Peer]":
            in_iface = False
            cur = Peer()
            peers.append(cur)
            cur.comments, pending = pending, []
            continue
        if in_iface:
            if line.startswith("#"):
                pending.append(line)
            elif line:
                iface.append(line)
            continue
        if line.startswith("#"):
            (cur.comments if cur and not cur.fields else pending).append(line)
            continue
        if "=" in line and cur is not None:
            k, v = line.split("=", 1)
            cur.fields.append((k.strip(), v.strip()))
    for p in peers:
        for c in p.comments:
            m = re.match(r"#\s*Name:\s*(.+)", c)
            if m:
                p.name = m.group(1).strip()
        if not p.name:
            short = [c.lstrip("# ").strip() for c in p.comments if ":" not in c and c.lstrip("# ").strip()]
            p.name = short[-1] if short else ""
    return iface, peers


def render(iface, peers):
    head = ["# Managed by wgpeer (gatewayChef/scripts/vpn/wgpeer.py). Do not edit by hand,",
            "# use `wgpeer add/remove/rename`. Changes apply via `wg syncconf` without restart.", ""]
    body = [l for l in iface if not l.split("=")[0].strip() in ("PostUp", "PreDown", "PostDown") or l.split("=", 1)[1].strip()]
    return "\n".join(head + body) + "\n\n" + "\n\n".join(p.render() for p in peers) + "\n"


def _sortkey(p):
    try:
        return (0, int(ipaddress.ip_address(p.ip)))
    except ValueError:
        return (1, 0)


def normalize(peers):
    for p in peers:
        nets = [n.strip() for n in (p.get("AllowedIPs") or "").split(",") if n.strip() and n.strip() not in DROP_NETS]
        p.set("AllowedIPs", ", ".join(nets))
    return sorted(peers, key=_sortkey)


def load():
    with open(CONF) as fh:
        return fh.read()


def redact(text):
    return KEY_RE.sub(lambda m: f"{m.group(1)} = <key>", text)


def commit(old, new, apply):
    diff = list(difflib.unified_diff(redact(old).splitlines(), redact(new).splitlines(), "wg0.conf (alt)", "wg0.conf (neu)", lineterm="", n=1))
    if not diff:
        print("Keine Änderung.")
        return 0
    print("\n".join(diff))
    print(f"\n{sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))} Zeilen neu, "
          f"{sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))} entfernt.")
    if not apply:
        print("Trockenlauf. Mit --apply übernehmen.")
        return 0
    watcher = subprocess.run(["systemctl", "is-active", "wg-quick-watcher@%s.path" % IFACE], capture_output=True, text=True).stdout.strip()
    if watcher == "active":
        sys.exit("Abbruch: wg-quick-watcher@%s.path ist aktiv und würde den Tunnel neu starten. Erst deaktivieren." % IFACE)
    backup = f"{CONF}.bak.{time.strftime('%Y%m%d_%H%M%S')}_wgpeer"
    shutil.copy2(CONF, backup)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(new)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONF)
    stripped = subprocess.run(["wg-quick", "strip", IFACE], capture_output=True, text=True, check=True).stdout
    subprocess.run(["wg", "syncconf", IFACE, "/dev/stdin"], input=stripped, text=True, check=True)
    # routes for added/removed AllowedIPs (wg syncconf does not touch the routing table)
    want = {n.strip() for l in new.splitlines() if l.startswith("AllowedIPs") for n in l.split("=", 1)[1].split(",") if n.strip()}
    have = set(subprocess.run(["ip", "-4", "route", "show", "dev", IFACE], capture_output=True, text=True).stdout.split("\n"))
    have = {l.split()[0] for l in have if l.strip()}
    iface_net = next((str(ipaddress.ip_interface(a.strip()).network) for l in new.splitlines() if l.startswith("Address")
                      for a in l.split("=", 1)[1].split(",") if "." in a), None)
    for net in sorted(want - have):
        if ":" not in net and net != iface_net and not (iface_net and ipaddress.ip_network(net).subnet_of(ipaddress.ip_network(iface_net))):
            subprocess.run(["ip", "route", "replace", net, "dev", IFACE], check=False)
    for net in sorted(have - want):
        if net != iface_net:
            subprocess.run(["ip", "route", "del", net, "dev", IFACE], check=False)
    print(f"Übernommen (Backup {backup}), ohne Neustart.")
    return 0


def handshakes():
    out = subprocess.run(["wg", "show", IFACE, "latest-handshakes"], capture_output=True, text=True).stdout
    return {l.split()[0]: int(l.split()[1]) for l in out.splitlines() if len(l.split()) == 2}


def load_seen():
    try:
        with open(SEEN) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def in_range(ip, rng):
    return not rng or ip in set(RANGES[rng])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wgpeer", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "free"):
        s = sub.add_parser(name)
        s.add_argument("--range", choices=RANGES)
        if name == "list":
            s.add_argument("--all", action="store_true", help="auch nie verbundene Pool-Plätze")
    s = sub.add_parser("add")
    s.add_argument("name")
    s.add_argument("--pubkey", required=True)
    s.add_argument("--range", choices=RANGES, default="infra")
    s.add_argument("--ip")
    s.add_argument("--apply", action="store_true")
    s = sub.add_parser("remove")
    s.add_argument("ip")
    s.add_argument("--apply", action="store_true")
    s = sub.add_parser("rename")
    s.add_argument("ip")
    s.add_argument("name")
    s.add_argument("--apply", action="store_true")
    s = sub.add_parser("normalize")
    s.add_argument("--apply", action="store_true")
    sub.add_parser("seen")
    s = sub.add_parser("json", help="Peer-Liste ohne Schlüssel als JSON (für die GatewayChef-Seite /vpn)")
    s.add_argument("--out")
    a = ap.parse_args(argv)

    old = load()
    iface, peers = parse(old)
    by_ip = {p.ip: p for p in peers}

    if a.cmd == "list":
        hs, seen = handshakes(), load_seen()
        now = time.time()
        for p in sorted(peers, key=_sortkey):
            if not in_range(p.ip, a.range):
                continue
            pk = p.get("PublicKey") or ""
            t = hs.get(pk) or seen.get(pk, 0)
            if not t and not a.all:
                continue
            age = "nie" if not t else f"{(now - t) / 86400:.1f} d" if now - t > 3600 else f"{int((now - t) / 60)} min"
            print(f"{p.ip:<16} {p.name or '-':<28} {age}")
        return 0
    if a.cmd == "free":
        for rng, ips in RANGES.items():
            if a.range and rng != a.range:
                continue
            free = [i for i in ips if i not in by_ip]
            print(f"{rng:<8} {len(free):>4} frei von {len(ips):>4}  nächste: {', '.join(free[:3])}")
        return 0
    if a.cmd == "json":
        hs, seen = handshakes(), load_seen()
        rx = {}
        for l in subprocess.run(["wg", "show", IFACE, "transfer"], capture_output=True, text=True).stdout.splitlines():
            f = l.split()
            if len(f) == 3:
                rx[f[0]] = (int(f[1]), int(f[2]))
        rng = {ip: r for r, ips in RANGES.items() for ip in ips}
        rows = []
        for p in sorted(peers, key=_sortkey):
            pk = p.get("PublicKey") or ""
            live = hs.get(pk) or 0
            rows.append({"ip": p.ip, "name": p.name, "range": rng.get(p.ip, "other"),
                         "handshake": live or seen.get(pk) or None, "live": bool(live),
                         "rx": rx.get(pk, (0, 0))[0], "tx": rx.get(pk, (0, 0))[1]})
        doc = json.dumps({"generated": int(time.time()), "peers": rows})
        if not a.out:
            print(doc)
            return 0
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out + ".tmp", "w") as fh:
            fh.write(doc)
        os.chmod(a.out + ".tmp", 0o644)
        os.replace(a.out + ".tmp", a.out)
        return 0
    if a.cmd == "seen":
        seen = load_seen()
        for pk, t in handshakes().items():
            if t:
                seen[pk] = max(t, seen.get(pk, 0))
        os.makedirs(os.path.dirname(SEEN), exist_ok=True)
        with open(SEEN + ".tmp", "w") as fh:
            json.dump(seen, fh)
        os.replace(SEEN + ".tmp", SEEN)
        return 0

    new_peers = list(peers)
    if a.cmd == "add":
        if any(p.get("PublicKey") == a.pubkey for p in peers):
            sys.exit("Schlüssel ist schon eingetragen.")
        ip = a.ip or next((i for i in RANGES[a.range] if i not in by_ip), None)
        if not ip:
            sys.exit(f"Bereich {a.range} ist voll.")
        if ip in by_ip:
            sys.exit(f"{ip} ist schon belegt ({by_ip[ip].name}).")
        p = Peer()
        p.name = a.name
        p.fields = [("PublicKey", a.pubkey), ("AllowedIPs", f"{ip}/32"), ("PersistentKeepalive", "25")]
        new_peers.append(p)
        print(f"{a.name} -> {ip}")
    elif a.cmd == "remove":
        if a.ip not in by_ip:
            sys.exit(f"{a.ip} nicht gefunden.")
        new_peers = [p for p in peers if p.ip != a.ip]
    elif a.cmd == "rename":
        if a.ip not in by_ip:
            sys.exit(f"{a.ip} nicht gefunden.")
        by_ip[a.ip].name = a.name
    new_peers = normalize(new_peers) if a.cmd == "normalize" else sorted(new_peers, key=_sortkey)
    return commit(old, render(iface, new_peers), a.apply)


if __name__ == "__main__":
    sys.exit(main())
