"""
Remote alignment of the fleet with our standard.

compare(fleet, gw)  -> what differs from the standard (profile for the gateway's
                       firmware without the risky VPN/cellular/network sections,
                       newest Node-RED flow)
align(fleet, ip)    -> bring one online gateway to the standard, only if it is
                       stable in the network right now.

Order and safety:
  1. Stability gate: STABLE_SAMPLES answers in a row over VPN, latency under
     STABLE_MAX_MS, cloud LNS connected as the packet forwarder reports it
     (servs[].connected). Otherwise nothing is touched.
  2. Node-RED flow first (the LNS order needs flow >= 1.1.1 to ACK on 1702).
  3. Plain parameters (WLAN country, NTP, ...): written together, read back.
  4. LNS / packet forwarder targets last and alone: the old servs are kept,
     after writing the gateway must answer, the forwarder must report the cloud LNS connected and
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
# Our standard LNS order (profiles, patch lns-nodered-first): Node-RED UDP 127.0.0.1:1702 first, Cortex 2nd.
# Everyone may switch a gateway to it. Only where tested: on 60.0.0.48 the forwarder log then lacks the
# Cortex ACK lines and /lora/health shows OFFLINE although Cortex is connected (0.115, 22.11.2026);
# older firmware keeps LEGACY_SERVS. Any other LNS order is admin only (patches).
LNS_FIRST_FW = [v.strip() for v in os.getenv("LNS_NODERED_FIRST_FW", "60.0.0.50").split(",") if v.strip()]
LEGACY_SERVS = [
    {"id": 0, "serv_enabled": True, "serv_addr": "localhost", "serv_type": "ursalink", "serv_port_up": 1700,
     "serv_port_down": 1700, "serv_mqtt_port": 1883, "sync_freq_plan": False},
    {"id": 1, "serv_enabled": True, "serv_addr": "ball-b-cs.cortex-media.de", "serv_type": "semtech",
     "serv_port_up": 1700, "serv_port_down": 1700, "sync_freq_plan": False},
    {"id": 2, "serv_enabled": True, "serv_addr": "127.0.0.1", "serv_type": "semtech", "serv_port_up": 1702,
     "serv_port_down": 1702, "sync_freq_plan": False},
]


def _standard(profile, firmware=None):
    import copy
    sections = [copy.deepcopy(s) for s in profile["sections"] if s["core"] not in fl.RISKY_CORES]
    if firmware and firmware.split("-")[0] not in LNS_FIRST_FW:
        for sec in sections:
            if (sec["core"], sec["base"]) == LNS_SECTION and "servs" in sec["value"]:
                sec["value"]["servs"] = copy.deepcopy(LEGACY_SERVS)
    return {"firmware": profile.get("firmware"), "sections": sections}


def _vars(gw):
    return gc.device_vars_from_inventory(gw.get("vpn_ip"), None, gw.get("eui"), os.getenv("GATEWAY_WIFI_KEY", ""), None)


def _is_lns(change):
    return (change.core, change.base) == LNS_SECTION


def _changes_out(changes):
    return [{"label": c.label, "lns": _is_lns(c),
             "fields": {k: [gc._mask(k, a), gc._mask(k, b)] for k, (a, b) in c.fields.items()}} for c in changes]


def cloud_lns(fleet, host):
    """(connected, detail) of the cloud LNS as the packet forwarder itself reports it
    (servs[].connected). Source of truth: Node-RED /lora/health parses log lines and is
    unreliable on older flows / firmware (UNKNOWN, LNS_DISCONNECTED although data flows)."""
    try:
        val = fleet._login(host).get(*LNS_SECTION)
        val = val[0]["value"] if isinstance(val, list) else val
    except (gc.GatewayConfigError, requests.RequestException, KeyError, IndexError, TypeError) as exc:
        return False, f"Forwarder-Status nicht lesbar ({type(exc).__name__})"
    servs = [s for s in val.get("servs", []) if s.get("serv_enabled") and s.get("serv_type") == "semtech"
             and s.get("serv_addr") not in ("127.0.0.1", "localhost")]
    if not servs:
        return False, "kein Cloud-LNS eingetragen"
    s = servs[0]
    return bool(s.get("connected")), f"{s['serv_addr']} {'verbunden' if s.get('connected') else 'nicht verbunden'}"


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
    plan = gc.plan(client, _standard(profile, client.firmware), _vars(gw), skip_missing=True)
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
    lns_ok, lns_info = cloud_lns(fleet, gw["vpn_ip"])
    if not lns_ok:
        return False, f"LNS: {lns_info}"
    return True, f"{samples}x erreichbar, max {max(lat)} ms, {lns_info}"


# ------------------------------------------------------------ align
def _write(client, changes):
    """Write and apply. A timeout is not an error here: the packet forwarder restarts
    while answering, the read-back / verification afterwards decides."""
    try:
        for ch in changes:
            client.set(ch.core, ch.base, ch.index, ch.set_value())
        client.apply()
    except gc.GatewayConfigError as exc:
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
        lns_ok, lns_info = cloud_lns(fleet, gw["vpn_ip"])
        if lns_ok:
            break
        if time.monotonic() >= deadline:
            return False, f"LNS: {lns_info}"
        fleet.sleep(5)
    db_ok, db_info = checks.check_driveby(gw["vpn_ip"], wait_secs=int(os.getenv("DRIVEBY_WAIT", "75")),
                                          http=fleet.http, sleep=fleet.sleep)
    if db_ok is False:
        return False, f"Datenweg: {db_info}"
    return True, f"{lns_info}, {db_info}"


def align(fleet, vpn_ip, apply=False, force=False, lns=True):
    """lns=False (no admin): LNS / packet forwarder targets are left as they are."""
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
    lns_ok_to_write = lns
    lns = [c for c in plan["changes"] if _is_lns(c)]
    if lns and not lns_ok_to_write:
        steps.append(("LNS-Ziele", None, "weichen ab, nicht geändert: nur Admins dürfen das LNS umstellen"))
        lns = []
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
        try:
            _write(fleet._login(vpn_ip), lns)
            ok, info = _verify_lns(fleet, gw)
        except gc.GatewayConfigError as exc:   # whatever happens after touching the LNS: verify or roll back
            ok, info = False, str(exc)
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

    if not plain and not lns and cmp_["flow"]["ok"]:
        return dict(public(cmp_), result="skipped", detail="nur LNS weicht ab: das darf nur ein Admin ändern",
                    checks=_checks(steps), needs_admin=True)
    return dict(public(cmp_), result="changed", detail="an Standard angeglichen: " + cmp_["detail"],
                checks=_checks(steps))


def _strip_status(value):
    """Old servs as read contain status fields (connected); write only config."""
    if isinstance(value, list):
        return [{k: v for k, v in s.items() if k != "connected"} if isinstance(s, dict) else s for s in value]
    return value


def _checks(steps):
    return [{"label": a, "ok": b, "info": c} for a, b, c in steps]
