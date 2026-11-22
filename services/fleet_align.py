"""
Remote alignment of the fleet with our standard.

compare(fleet, gw)  -> what differs from the standard (profile for the gateway's
                       firmware without the risky VPN/cellular/network sections,
                       newest Node-RED flow)
align(fleet, ip)    -> bring one online gateway to the standard, only if it is
                       stable in the network right now.

Order and safety:
  1. Stability gate: STABLE_SAMPLES answers in a row over VPN, latency under
     STABLE_MAX_MS, Node-RED /lora/health ONLINE. Otherwise nothing is touched.
  2. Node-RED flow first (the LNS order needs flow >= 1.1.1 to ACK on 1702).
  3. Plain parameters (WLAN country, NTP, ...): written together, read back.
  4. LNS / packet forwarder targets last and alone: the old servs are kept,
     after writing the gateway must answer, /lora/health must be ONLINE and
     the forwarder must deliver fresh UDP packets. If not: the old servs are
     written back (rollback) and the result is "failed".
Firmware is only shown here; upgrades stay a separate, explicit action.
"""
import os
import time

import requests

from services import fleet as fl
from services import gateway_config as gc
from services import nodered as nr
from services.setup import checks

LNS_SECTION = ("yruo_loragw", "general_conf")


def _standard(profile):
    return {"firmware": profile.get("firmware"),
            "sections": [s for s in profile["sections"] if s["core"] not in fl.RISKY_CORES]}


def _vars(gw):
    return gc.device_vars_from_inventory(gw.get("vpn_ip"), None, gw.get("eui"), os.getenv("GATEWAY_WIFI_KEY", ""), None)


def _is_lns(change):
    return (change.core, change.base) == LNS_SECTION


def _changes_out(changes):
    return [{"label": c.label, "lns": _is_lns(c),
             "fields": {k: [gc._mask(k, a), gc._mask(k, b)] for k, (a, b) in c.fields.items()}} for c in changes]


def _lora_health(fleet, host):
    try:
        return fleet.http.get(f"http://{host}/node-red/lora/health", timeout=fleet.timeout).json()
    except (requests.RequestException, ValueError):
        return None


# ------------------------------------------------------------ compare
def compare(fleet, gw):
    host = gw["vpn_ip"]
    ok, detail, _ = fleet.identity(gw)
    if not ok:
        return {"vpn_ip": host, "result": "offline", "detail": detail}
    client = fleet._login(host)
    client.get("yruo_wifi", "yruo_wifi")
    profile = gc.load_profile(gc.profile_for_firmware(client.firmware))
    compat = gc.firmware_compat(client, profile)
    out = {"vpn_ip": host, "firmware": client.firmware, "profile": profile["name"], "firmware_compat": compat["status"]}
    if not compat["allowed"]:
        out.update(result="blocked", detail=f"Firmware {client.firmware} nicht freigegeben ({compat['status']})",
                   changes=[], client=client)
        return out
    plan = gc.plan(client, _standard(profile), _vars(gw), skip_missing=True)
    bundles = nr.load_bundles()
    latest = nr.latest_version(bundles)
    try:
        flow = nr.status(fleet.nodered_factory(host), bundles)
    except nr.NodeRedError as exc:
        flow = {"version": None, "modified": None, "error": str(exc)}
    flow_ok = flow.get("version") == latest and not flow.get("modified")
    newest_fw = max(fl.known_firmwares(), key=gc._version_key) if fl.known_firmwares() else None
    out.update(changes=_changes_out(plan["changes"]), plan=plan, client=client,
               flow={"current": flow.get("version"), "target": latest, "ok": flow_ok, "error": flow.get("error")},
               firmware_newest=newest_fw, firmware_ok=not newest_fw or client.firmware == newest_fw)
    n = len(plan["changes"]) + (0 if flow_ok else 1)
    out["result"] = "ok" if not n else "would_change"
    parts = [] if flow_ok else [f"Flow {flow.get('version') or '?'} -> {latest}"]
    parts += [c.label + (" (LNS)" if _is_lns(c) else "") for c in plan["changes"]]
    out["detail"] = "entspricht Standard" if not n else "; ".join(parts)
    if not out["firmware_ok"]:
        out["detail"] += f" | Firmware {client.firmware}, neueste {newest_fw} (separat aktualisieren)"
    return out


def public(res):
    return {k: v for k, v in res.items() if k not in ("plan", "client")}


# ------------------------------------------------------------ stability gate
def stability(fleet, gw, samples=None, interval=None, max_ms=None):
    samples = samples or int(os.getenv("STABLE_SAMPLES", "4"))
    interval = interval if interval is not None else int(os.getenv("STABLE_INTERVAL", "5"))
    max_ms = max_ms or int(os.getenv("STABLE_MAX_MS", "3000"))
    lat = []
    for i in range(samples):
        ok, detail, ms = fleet.identity(gw)
        if not ok:
            return False, f"Antwort {i + 1}/{samples} fehlt: {detail}"
        if ms is not None and ms > max_ms:
            return False, f"Latenz {ms} ms > {max_ms} ms"
        lat.append(ms or 0)
        if i < samples - 1:
            fleet.sleep(interval)
    health = _lora_health(fleet, gw["vpn_ip"]) or {}
    if health.get("status") != "ONLINE":
        return False, f"LNS nicht ONLINE ({health.get('status') or 'keine Antwort'})"
    return True, f"{samples}x erreichbar, max {max(lat)} ms, LNS ONLINE"


# ------------------------------------------------------------ align
def _write(client, changes):
    for ch in changes:
        client.set(ch.core, ch.base, ch.index, ch.set_value())
    try:
        client.apply()
    except gc.GatewayConfigError as exc:
        # forwarder restart can make the gateway answer late; the read-back decides
        if not isinstance(exc.__cause__, requests.ReadTimeout):
            raise


def _left(fleet, host, gw, changes):
    profile_like = {"firmware": None, "sections": [
        {"core": c.core, "base": c.base, "index": c.index, "label": c.label,
         "value": {k: t for k, (_, t) in c.fields.items()}} for c in changes]}
    return gc.plan(fleet._login(host), profile_like, _vars(gw))["changes"]


def _verify_lns(fleet, gw):
    ok, detail = fleet.wait_reachable(gw)
    if not ok:
        return False, f"nicht erreichbar: {detail}"
    deadline = time.monotonic() + int(os.getenv("LNS_VERIFY_WAIT", "90"))
    while True:
        health = _lora_health(fleet, gw["vpn_ip"]) or {}
        if health.get("status") == "ONLINE":
            break
        if time.monotonic() >= deadline:
            return False, f"LNS nicht ONLINE ({health.get('status') or 'keine Antwort'})"
        fleet.sleep(5)
    db_ok, db_info = checks.check_driveby(gw["vpn_ip"], wait_secs=int(os.getenv("DRIVEBY_WAIT", "75")),
                                          http=fleet.http, sleep=fleet.sleep)
    if db_ok is False:
        return False, f"Datenweg: {db_info}"
    return True, f"LNS ONLINE, {db_info}"


def align(fleet, vpn_ip, apply=False, force=False):
    gw = fleet._gateway(vpn_ip)
    cmp_ = compare(fleet, gw)
    if cmp_["result"] in ("offline", "blocked", "ok") or not apply:
        return public(cmp_)
    steps = []
    stable, why = (True, "uebersprungen (force)") if force else stability(fleet, gw)
    steps.append(("Stabil im Netz", stable, why))
    if not stable:
        return dict(public(cmp_), result="skipped", detail=f"nicht stabil: {why}", checks=_checks(steps))

    plan = cmp_["plan"]
    lns = [c for c in plan["changes"] if _is_lns(c)]
    plain = [c for c in plan["changes"] if not _is_lns(c)]

    if not cmp_["flow"]["ok"]:
        res = fleet.nodered_update(vpn_ip, cmp_["flow"]["target"], apply=True)
        good = res.get("result") in ("updated", "ok")
        steps.append((f"Flow {cmp_['flow']['target']}", good, res.get("detail") or res.get("result")))
        if not good:
            return dict(public(cmp_), result="failed", detail="Flow-Update fehlgeschlagen", checks=_checks(steps))

    if plain:
        client = fleet._login(vpn_ip)
        _write(client, plain)
        ok, detail = fleet.wait_reachable(gw)
        left = _left(fleet, vpn_ip, gw, plain) if ok else plain
        good = ok and not left
        steps.append(("Parameter", good, ", ".join(c.label for c in plain) if good else
                      (detail if not ok else "weicht noch ab: " + ", ".join(c.label for c in left))))
        if not good:
            return dict(public(cmp_), result="failed", detail="Parameter nicht uebernommen", checks=_checks(steps))

    if lns:
        ch = lns[0]
        before = {k: a for k, (a, _) in ch.fields.items()}
        _write(fleet._login(vpn_ip), lns)
        ok, info = _verify_lns(fleet, gw)
        steps.append(("LNS-Ziele", ok, info))
        if not ok:
            rb = gc.Change(ch.core, ch.base, ch.index, ch.label,
                           {k: (None, _strip_status(v)) for k, v in before.items()})
            try:
                _write(fleet._login(vpn_ip), [rb])
                rb_ok, rb_info = _verify_lns(fleet, gw)
            except gc.GatewayConfigError as exc:
                rb_ok, rb_info = False, str(exc)
            steps.append(("Zurueckgerollt", rb_ok, rb_info))
            return dict(public(cmp_), result="failed", detail="LNS-Umstellung zurueckgerollt",
                        rolled_back=True, rollback_ok=rb_ok, checks=_checks(steps))

    return dict(public(cmp_), result="changed", detail="an Standard angeglichen: " + cmp_["detail"],
                checks=_checks(steps))


def _strip_status(value):
    """Old servs as read contain status fields (connected); write only config."""
    if isinstance(value, list):
        return [{k: v for k, v in s.items() if k != "connected"} if isinstance(s, dict) else s for s in value]
    return value


def _checks(steps):
    return [{"label": a, "ok": b, "info": c} for a, b, c in steps]
