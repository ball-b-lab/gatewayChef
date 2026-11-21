#!/usr/bin/env python3
"""
Fleet tools (run inside the VPN, e.g. on the Linux station):

  status [--deep] [--ip IP ...]               Erreichbarkeit, EUI; --deep: Firmware, WLAN-Region, Flow-Version
  patch NAME (--ip IP ... | --all) [--apply] [--allow-risky]
                                              Parameter aus gateway_profiles/patches/NAME.json schreiben
  nodered (--ip IP ... | --all) [--version V] [--apply]
                                              Node-RED-Flows aktualisieren, Nachtest, Rollback bei Fehler
  firmware --version V (--ip IP ... | --all | --host LAN-IP) [--apply]
                                              Firmware-Update anstossen, warten, Nachtest; --all stoppt beim ersten Fehler
  driveby (--ip IP | --host LAN-IP) [--need-rxpk] [--wait S]
                                              Drive-by-Datenweg testen (stat; mit Testsender auch Funkpakete)
  nodered-export --host IP --version V        Flows eines Referenzgeraets als Bundle speichern
  profile-check --host IP [--profile NAME]    neue Firmware: passt die Schnittstelle noch zum Profil?

Ohne --apply wird nur geprueft. Exit: 0 ok, 1 Aenderungen offen, 2 Fehler.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402,F401  (loads .env)
from services import fleet as fl  # noqa: E402
from services import gateway_config as gc  # noqa: E402
from services import nodered as nr  # noqa: E402
from services import profile_check as pc  # noqa: E402


def _targets(fleet, args):
    if getattr(args, "all", False):
        return [g["vpn_ip"] for g in fleet.gateways() if g.get("status_overall") == "DEPLOYED"]
    return args.ip or []


def _ago(s):
    if s is None:
        return "nie"
    return f"{s}s" if s < 90 else f"{round(s / 60)}min" if s < 5400 else f"{round(s / 3600)}h"


def _driveby_txt(d):
    if not d:
        return "Drive-by: kein UDP-Flow"
    return (f"Empfang {'ok' if d['receiving'] else 'AUS'} (Funk {_ago(d['seconds_since_rxpk'])})"
            f"  dbmonitor {_ago(d['app_seconds_since_poll'])}")


def _print_status(rows):
    for r in rows:
        flow = r.get("flow") or {}
        flow_txt = (flow.get("version") or "unbekannt") + (" (geaendert)" if flow.get("modified") else "") if flow else r.get("flow_error", "")
        print(f"{r['vpn_ip']:<15} {'online ' if r['online'] else 'OFFLINE'} {str(r.get('latency_ms') or ''):>5}ms "
              f"{(r.get('gateway_name') or '')[:28]:<28} FW {r.get('firmware', '-'):<10} "
              f"WLAN {r.get('wifi_country', '-'):<3} Flow {flow_txt or (r.get('driveby') or {}).get('flow_version') or '-'}"
              f"  {_driveby_txt(r.get('driveby'))}  {'' if r['online'] else r['identity']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--deep", action="store_true")
    s.add_argument("--ip", nargs="*")
    s.add_argument("--json", action="store_true")
    for name in ("patch", "nodered"):
        p = sub.add_parser(name)
        if name == "patch":
            p.add_argument("name")
            p.add_argument("--allow-risky", action="store_true")
        else:
            p.add_argument("--version")
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--ip", nargs="+")
        g.add_argument("--all", action="store_true", help="alle Gateways mit Status DEPLOYED")
        p.add_argument("--apply", action="store_true")
    fwp = sub.add_parser("firmware")
    fwp.add_argument("--version", required=True)
    g = fwp.add_mutually_exclusive_group(required=True)
    g.add_argument("--ip", nargs="+")
    g.add_argument("--all", action="store_true")
    g.add_argument("--host", help="Gateway im LAN (Station), ohne DB-Abgleich")
    fwp.add_argument("--apply", action="store_true")
    d = sub.add_parser("driveby")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--ip")
    g.add_argument("--host")
    d.add_argument("--need-rxpk", action="store_true", help="Funkpaket Pflicht (Testsender in der Naehe)")
    d.add_argument("--wait", type=int, default=120)
    e = sub.add_parser("nodered-export")
    e.add_argument("--host", required=True)
    e.add_argument("--version", required=True)
    c = sub.add_parser("profile-check")
    c.add_argument("--host", required=True)
    c.add_argument("--profile", default=os.getenv("GATEWAY_PROFILE", "auto"))
    args = ap.parse_args(argv)

    try:
        if args.cmd == "profile-check":
            client = gc.UG65Client(args.host)
            client.login(os.getenv("GATEWAY_USER", "admin"), os.getenv("GATEWAY_PASSWORD", ""))
            if args.profile == "auto":
                client.get("yruo_wifi", "yruo_wifi")  # fills client.firmware
                args.profile = gc.profile_for_firmware(client.firmware)
            result = pc.check(client, gc.load_profile(args.profile))
            print(pc.format_check(result, args.profile))
            if result["firmware"] != gc.load_profile(args.profile).get("firmware"):
                path = os.path.join(gc.PROFILE_DIR, f"ug65-{result['firmware']}.json.draft")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(result["draft"], fh, indent=2, ensure_ascii=False)
                print(f"Entwurf: {path}")
            return 0 if result["compatible"] else 1

        if args.cmd == "driveby":
            from services.setup import checks
            ok, info = checks.check_driveby(args.ip or args.host, wait_secs=args.wait, need_rxpk=args.need_rxpk)
            print(f"{'OK' if ok else 'WARN' if ok is None else 'FEHLER'}: {info}")
            return 0 if ok else (1 if ok is None else 2)

        if args.cmd == "nodered-export":
            client = nr.NodeRedClient(args.host, os.getenv("NODERED_USER", os.getenv("GATEWAY_USER", "admin")),
                                      os.getenv("NODERED_PASSWORD", os.getenv("GATEWAY_PASSWORD", "")))
            client.login()
            flows = client.get_flows()["flows"]
            if nr.declared_version(flows) != args.version:
                print(f"Hinweis: Kommentar-Node 'gatewaychef-flow {args.version}' fehlt im Flow. "
                      "Bitte in Node-RED anlegen und erneut exportieren.", file=sys.stderr)
            path = os.path.join(nr.FLOW_DIR, f"{args.version}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(flows, fh, indent=1, ensure_ascii=False)
            print(f"{len(flows)} Nodes -> {path} (Hash {nr.flow_hash(flows)})")
            return 0

        fleet = fl.from_env()
        if args.cmd == "firmware":
            from services import firmware as fwm
            rc = 0
            targets = [{"vpn_ip": args.host, "eui": None}] if args.host else None
            for ip in ([args.host] if args.host else _targets(fleet, args)):
                try:
                    gw = targets[0] if targets else fleet._gateway(ip)
                    res = fl.firmware_upgrade(fleet, gw, args.version, apply=args.apply)
                except (fl.FleetError, gc.GatewayConfigError, nr.NodeRedError, fwm.FirmwareError) as exc:
                    res = {"vpn_ip": ip, "result": "error", "detail": str(exc)}
                print(f"{ip:<15} {res['result']:<13} {res.get('detail') or ''}")
                for c in res.get("checks") or []:
                    mark = {True: "+", False: "!", None: "."}[c["ok"]]
                    print(f"    {mark} {c['label']}: {c['info']}")
                if res["result"] in ("error", "failed"):
                    print("Abbruch: weitere Gateways werden nicht aktualisiert.")
                    return 2
                rc = max(rc, 1 if res["result"] == "would_change" else 0)
            return rc
        if args.cmd == "status":
            rows = fleet.status(deep=args.deep, only=args.ip)
            print(json.dumps(rows, indent=1, default=str)) if args.json else _print_status(rows)
            print(f"{sum(r['online'] for r in rows)}/{len(rows)} online")
            return 0 if all(r["online"] for r in rows) else 1

        results = []
        for ip in _targets(fleet, args):
            try:
                if args.cmd == "patch":
                    res = fleet.patch(ip, fl.load_patch(args.name), apply=args.apply, allow_risky=args.allow_risky)
                else:
                    res = fleet.nodered_update(ip, args.version, apply=args.apply)
            except (fl.FleetError, gc.GatewayConfigError, nr.NodeRedError) as exc:
                res = {"vpn_ip": ip, "result": "error", "detail": str(exc)}
            results.append(res)
            extra = "; ".join(f"{c['label']}: " + ", ".join(f"{k} {a!r}->{b!r}" for k, (a, b) in c["fields"].items())
                              for c in res.get("changes") or [])
            rb = " [zurueckgerollt: " + ("ok" if res.get("rollback_ok") else "FEHLER") + "]" if res.get("rolled_back") else ""
            print(f"{ip:<15} {res['result']:<13} {res.get('detail') or ''} {extra}{rb}")
        if any(r["result"] in ("error", "failed") for r in results):
            return 2
        return 1 if any(r["result"] == "would_change" for r in results) else 0
    except (fl.FleetError, gc.GatewayConfigError, nr.NodeRedError, OSError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
