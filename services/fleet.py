"""
Fleet management over the VPN: status of all gateways, remote patches,
Node-RED updates. Runs on a machine inside the VPN (the Linux station as a
WireGuard workstation peer, or the cloud instance).

Each gateway is addressed by its VPN IP; the EUI that answers is always
compared with the DB, so a wrong IP or a swapped key never gets written to.

Every write is: plan -> write -> read back -> post-check (gateway still
answers over VPN with the right EUI). Node-RED additionally rolls back.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from services import gateway_config as gc
from services import firmware as fw
from services import nodered as nr
from services.setup import checks
from services.setup.model import normalize_eui

PATCH_DIR = os.path.join(gc.PROFILE_DIR, "patches")
# A remote patch on these sections can cut the gateway off the VPN.
RISKY_CORES = {"yruo_wireguard", "yruo_cell", "yruo_network", "yruo_wan", "yruo_upgrade"}


class FleetError(Exception):
    pass


def drive_by_summary(health):
    """Compact view of /node-red/driveby/health (flow >= 1.1.0); None for older flows."""
    if not health:
        return None
    app = health.get("app") or {}
    counts = health.get("counts") or {}
    stat = health.get("seconds_since_stat")
    return {
        "flow_version": health.get("flow_version"),
        "receiving": stat is not None and stat < 65,
        "seconds_since_stat": stat,
        "seconds_since_rxpk": health.get("seconds_since_rxpk"),
        "rxpk": counts.get("rxpk", 0),
        "app_seconds_since_poll": app.get("seconds_since_poll"),
        "app_last_poll": app.get("last_poll"),
        "app_client": app.get("client"),
        "app_polls": app.get("polls", 0),
        "radio": health.get("radio"),  # flow >= 1.2.0: CRC error rate, RSSI/SNR, last 30 min (1.3.0: sf, tx_failed)
        "devices": health.get("devices"),  # flow >= 1.3.0: sensors heard in the last 24 h
    }


def _num(text):
    """'-105dBm' -> -105.0, '20asu (-73dBm)' -> -73.0 (the value in brackets wins)."""
    import re
    m = re.search(r"\((-?\d+(?:\.\d+)?)", text or "") or re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group(1) if m.re.groups else m.group(0)) if m else None


def gateway_health(client):
    """Device status read over the gateway's own API (no flow needed). No IMSI/ICCID/IMEI/cell IDs."""
    out = {}
    summ = client.get("yruo_status", "summary")
    sysv = next((e.get("value") or {} for e in summ if (e.get("type") or "").lower() == "system"), {})
    if sysv:
        out["system"] = {
            "uptime_s": sysv.get("uptime"), "cpu_load": sysv.get("cpu_load"),
            "memory_free": sysv.get("memory_free"), "memory_avail_percent": sysv.get("memory_avail_percent"),
            "storage_free": sysv.get("emmc_free"), "storage_avail_percent": sysv.get("emmc_avail_percent"),
            "local_time": sysv.get("local_time"),
            "lns": [{"addr": d.get("serv_addr"), "connected": d.get("connected")}
                    for d in ((sysv.get("packet_forwarder") or {}).get("destinations") or []) if d.get("serv_enabled")],
        }
    try:
        cell = client._call("yruo_status", "get", [{"base": "yruo_celluar"}])
        rows = (cell[0] if cell and isinstance(cell[0], dict) else {}).get("get") or []
    except gc.GatewayConfigError:
        rows = []
    modem = next((e.get("value") or {} for e in rows if e.get("type") == "cellular_modem"), {})
    net = next((e.get("value") or {} for e in rows if e.get("type") == "cellular_network"), {})
    if modem:
        out["cellular"] = {
            "status": net.get("status"), "connected_for": net.get("time"),
            "provider": modem.get("net_provider"), "net_type": modem.get("net_type"), "band": modem.get("band"),
            "register": modem.get("register"), "sim": modem.get("cur_sim"),
            "signal_dbm": _num(modem.get("signal")), "rsrp_dbm": _num(modem.get("rsrp")),
            "rsrq_db": _num(modem.get("rsrq")), "sinr_db": _num(modem.get("sinr")),
            "data_usage": modem.get("sim1_flow") if modem.get("cur_sim") != "SIM2" else modem.get("sim2_flow"),
        }
    return out


def list_patches():
    out = {}
    for name in sorted(os.listdir(PATCH_DIR)) if os.path.isdir(PATCH_DIR) else []:
        if name.endswith(".json"):
            out[name[:-5]] = load_patch(name[:-5])
    return out


def load_patch(name):
    path = name if os.path.isfile(name) else os.path.join(PATCH_DIR, f"{name}.json")
    with open(path, encoding="utf-8") as fh:
        patch = json.load(fh)
    patch.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    return patch


def patch_touches_lns(patch):
    """LNS / packet forwarder targets: only admins may change them (standard: driveby-udp-forward)."""
    return any((s["core"], s["base"]) == ("yruo_loragw", "general_conf") for s in patch["sections"])


STANDARD_LNS_PATCHES = {"lns-nodered-first"}   # our standard LNS order: everyone may write it


def patch_admin_only(patch):
    """Risky sections, or an LNS order other than our standard."""
    return bool(patch_is_risky(patch) or (patch_touches_lns(patch) and patch.get("name") not in STANDARD_LNS_PATCHES))


def patch_is_risky(patch):
    return sorted({s["core"] for s in patch["sections"]} & RISKY_CORES)


def known_firmwares():
    return sorted(f[len("ug65-"):-len(".json")] for f in os.listdir(gc.PROFILE_DIR)
                  if f.startswith("ug65-") and f.endswith(".json"))


class Fleet:
    def __init__(self, inventory, gateway_user="admin", gateway_password="", nodered_user="", nodered_password="",
                 timeout=8, workers=16, backup_dir=None, http=requests, client_factory=None,
                 nodered_factory=None, sleep=time.sleep, reachable_wait=120):
        self.inventory = inventory
        self.gateway_user, self.gateway_password = gateway_user, gateway_password
        self.nodered_user, self.nodered_password = nodered_user, nodered_password
        self.timeout, self.workers = timeout, workers
        self.backup_dir = backup_dir
        self.http, self.sleep = http, sleep
        self.reachable_wait = reachable_wait
        self.client_factory = client_factory or (lambda host: gc.UG65Client(host, timeout=timeout))
        self.nodered_factory = nodered_factory or (
            lambda host: nr.NodeRedClient(host, nodered_user, nodered_password, timeout=timeout))

    # ------------------------------------------------------------ helpers
    def gateways(self):
        return self.inventory.list_gateways()

    def _gateway(self, vpn_ip):
        gw = next((g for g in self.gateways() if g["vpn_ip"] == vpn_ip), None)
        if not gw:
            raise FleetError(f"{vpn_ip} ist kein vergebenes Gateway in der DB")
        return gw

    def _login(self, host):
        client = self.client_factory(host)
        client.login(self.gateway_user, self.gateway_password)
        return client

    def identity(self, gw):
        """(ok, detail): gateway answers over VPN and is the one the DB expects."""
        t0 = time.monotonic()
        try:
            info = checks.device_info(gw["vpn_ip"], timeout=self.timeout, http=self.http)
        except (requests.HTTPError, ValueError) as exc:
            # the gateway answers, but without our Node-RED flow (new gateway): web login counts as online
            try:
                self._login(gw["vpn_ip"])
            except Exception:  # noqa: BLE001
                return False, f"keine Antwort ({type(exc).__name__})", None
            return True, "Weboberflaeche (noch ohne Drive-by-Flow)", int((time.monotonic() - t0) * 1000)
        except requests.RequestException as exc:
            return False, f"keine Antwort ({type(exc).__name__})", None
        ms = int((time.monotonic() - t0) * 1000)
        eui = normalize_eui(((info.get("device") or {}).get("eui")))
        want = normalize_eui(gw.get("eui"))
        if want and eui != want:
            return False, f"antwortet mit EUI {eui}, DB erwartet {want}", ms
        return True, eui, ms

    def wait_reachable(self, gw):
        deadline = time.monotonic() + self.reachable_wait
        while True:
            ok, detail, _ = self.identity(gw)
            if ok or time.monotonic() >= deadline:
                return ok, detail
            self.sleep(5)

    # ------------------------------------------------------------ status
    def probe(self, gw, deep=False, bundles=None):
        row = dict(gw)
        ok, detail, ms = self.identity(gw)
        row.update(online=ok, latency_ms=ms, identity=detail)
        if ok:
            row["driveby"] = drive_by_summary(checks._driveby_health(gw["vpn_ip"], self.http))
        if not ok or not deep:
            return row
        try:
            client = self._login(gw["vpn_ip"])
            wifi = client.get("yruo_wifi", "yruo_wifi")
            row["firmware"] = client.firmware
            row["profile_ok"] = client.firmware in known_firmwares()
            row["profile"] = gc.profile_for_firmware(client.firmware)
            if not row["profile_ok"]:
                # no exact profile: the newest one is used if the gateway's interface is compatible
                compat = gc.firmware_compat(client, gc.load_profile(row["profile"]))
                row["firmware_compat"] = compat["status"]
                row["firmware_deltas"] = compat["deltas"]
            row["wifi_country"] = ((wifi[0] if wifi else {}).get("value") or {}).get("country_code")
            try:
                row["health"] = gateway_health(client)
            except Exception as exc:  # extra info only, never fail the deep check because of it
                row["health_error"] = str(exc)[:200]
        except gc.GatewayConfigError as exc:
            row["cgi_error"] = str(exc)
        try:
            row["flow"] = nr.status(self.nodered_factory(gw["vpn_ip"]), bundles if bundles is not None else nr.load_bundles())
        except nr.NodeRedError as exc:
            row["flow_error"] = str(exc)
        return row

    def status(self, deep=False, only=None):
        gws = [g for g in self.gateways() if not only or g["vpn_ip"] in only]
        bundles = nr.load_bundles() if deep else None
        # mostly waiting on VPN timeouts of offline gateways: many threads, few CPU
        with ThreadPoolExecutor(max_workers=max(self.workers, 64)) as pool:
            return list(pool.map(lambda g: self.probe(g, deep, bundles), gws))

    # ------------------------------------------------------------ remote patch
    def patch(self, vpn_ip, patch, apply=False, allow_risky=False):
        gw = self._gateway(vpn_ip)
        risky = patch_is_risky(patch)
        if risky and not allow_risky:
            raise FleetError(f"Patch beruehrt {', '.join(risky)}: kann das Gateway vom VPN trennen. "
                             "Nur mit allow_risky und Zugang vor Ort.")
        ok, detail, _ = self.identity(gw)
        if not ok:
            return {"vpn_ip": vpn_ip, "result": "offline", "detail": detail}
        client = self._login(vpn_ip)
        result = gc.plan(client, {"firmware": None, "sections": patch["sections"]}, {})
        fw_note = ""
        if patch.get("firmware") and client.firmware not in patch["firmware"]:
            compat = gc.firmware_compat(client, {"name": patch["name"], "firmware": patch["firmware"][-1],
                                                 "sections": patch["sections"]})
            if not compat["allowed"]:
                return {"vpn_ip": vpn_ip, "result": "skipped",
                        "detail": f"Firmware {client.firmware} nicht in {patch['firmware']}: "
                                  + ("; ".join(compat["deltas"]) or "FIRMWARE_POLICY=strict")}
            fw_note = f" (FW {client.firmware} ungeprueft, Felder vorhanden)"
        changes = [{"label": c.label, "fields": {k: [gc._mask(k, a), gc._mask(k, b)] for k, (a, b) in c.fields.items()}}
                   for c in result["changes"]]
        if not result["changes"]:
            return {"vpn_ip": vpn_ip, "result": "ok", "detail": "entspricht bereits dem Patch", "changes": []}
        if not apply:
            return {"vpn_ip": vpn_ip, "result": "would_change", "changes": changes, "detail": fw_note.strip()}
        gc.execute(client, result)
        reach_ok, reach = self.wait_reachable(gw)
        if not reach_ok:
            return {"vpn_ip": vpn_ip, "result": "failed", "changes": changes,
                    "detail": f"nach dem Schreiben nicht mehr erreichbar: {reach}"}
        left = gc.plan(self._login(vpn_ip), {"firmware": None, "sections": patch["sections"]}, {})["changes"]
        if left:
            return {"vpn_ip": vpn_ip, "result": "failed", "changes": changes,
                    "detail": "Zuruecklesen: " + ", ".join(c.label for c in left) + " weicht noch ab"}
        return {"vpn_ip": vpn_ip, "result": "changed", "changes": changes, "detail": "geschrieben, geprueft" + fw_note}

    # ------------------------------------------------------------ firmware
    def firmware_upgrade(self, vpn_ip, version, apply=False, images=None, wait_secs=None, force=False):
        return firmware_upgrade(self, self._gateway(vpn_ip), version, apply, images, wait_secs, force)

    # ------------------------------------------------------------ node-red
    def post_update_check(self, gw):
        """After a flow deploy: right gateway answers, Node-RED HTTP endpoints serve again."""
        ok, detail = self.wait_reachable(gw)
        if not ok:
            return False, f"device-info: {detail}"
        try:
            resp = self.http.get(f"http://{gw['vpn_ip']}/node-red/lora/health", timeout=self.timeout)
            health = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return False, f"lora/health antwortet nicht ({type(exc).__name__})"
        return True, f"device-info ok, lora/health: {health.get('status')}"

    def nodered_update(self, vpn_ip, version=None, apply=False):
        gw = self._gateway(vpn_ip)
        bundles = nr.load_bundles()
        version = version or nr.latest_version(bundles)
        if version not in bundles:
            raise FleetError(f"Flow-Version {version} nicht in gateway_profiles/flows/")
        ok, detail, _ = self.identity(gw)
        if not ok:
            return {"vpn_ip": vpn_ip, "result": "offline", "detail": detail}
        client = self.nodered_factory(vpn_ip)
        current = nr.status(client, bundles)
        if current["version"] == version and not current["modified"]:
            return {"vpn_ip": vpn_ip, "result": "ok", "detail": f"Flow {version} bereits installiert"}
        if not apply:
            return {"vpn_ip": vpn_ip, "result": "would_change",
                    "detail": f"Flow {current['version'] or 'unbekannt'} -> {version}"}
        backup = os.path.join(self.backup_dir, normalize_eui(gw.get("eui")) or vpn_ip) if self.backup_dir else None
        out = nr.update(client, bundles[version], lambda: self.post_update_check(gw), backup_dir=backup,
                        sleep=self.sleep)
        out.update(vpn_ip=vpn_ip, version=version, before=current["version"])
        return out


def _flow_hash(fleet, host):
    try:
        client = fleet.nodered_factory(host)
        client.login()
        return nr.flow_hash(client.get_flows()["flows"])
    except nr.NodeRedError:
        return None


def _heartbeat(say, text, every=30):
    """Say `text ... N s` every `every` seconds until the returned stop() is called."""
    import threading
    done = threading.Event()
    t0 = time.monotonic()

    def run():
        while not done.wait(every):
            say(f"{text} ... {int(time.monotonic() - t0)} s")
    threading.Thread(target=run, daemon=True).start()
    return done.set


def firmware_upgrade(fleet, gw, version, apply=False, images=None, wait_secs=None, force=False, progress=None):
    say = progress or (lambda msg: None)
    host = gw["vpn_ip"]
    images = images if images is not None else fw.find_images()
    if version not in images:
        raise FleetError(f"Firmware {version} nicht in FIRMWARE_DIR ({', '.join(sorted(images)) or 'leer'})")
    image = images[version]
    ok, detail, _ = fleet.identity(gw)
    if not ok:
        return {"vpn_ip": host, "result": "offline", "detail": detail}
    client = fleet._login(host)
    client.get("yruo_wifi", "yruo_wifi")
    before = client.firmware
    if before == version:
        return {"vpn_ip": host, "result": "ok", "detail": f"Firmware {before} bereits installiert"}
    from services.setup.firmware_step import MIN_FROM, is_older
    if is_older(before, MIN_FROM.get(version, "")):
        return {"vpn_ip": host, "result": "skipped",
                "detail": f"{before} -> {version} geht laut Milesight erst ab {MIN_FROM[version]}: zuerst Zwischenversion einspielen"}
    plan_txt = f"{before} -> {image['label']} ({image['size'] // 1_000_000} MB Upload)"
    if not apply:
        return {"vpn_ip": host, "result": "would_change", "detail": plan_txt}
    fw.upload_form()  # refuse before touching anything if the form values are unknown
    if not force:
        # ~141 MB over the SIM and a reboot: only when the gateway is stable in the network right now
        from services.fleet_align import stability
        stable, why = stability(fleet, gw)
        if not stable:
            return {"vpn_ip": host, "result": "skipped", "detail": f"nicht stabil, kein Upload: {why}",
                    "checks": [{"label": "Stabil im Netz", "ok": False, "info": why}]}
    flows_before = _flow_hash(fleet, host)
    say(f"Upload startet: {plan_txt}")
    stop = _heartbeat(say, "Upload laeuft")
    try:
        up = fw.upload(client, host, image)
    finally:
        stop()
    say(f"Upload fertig: {up}")
    wait = wait_secs or int(os.getenv("FIRMWARE_UPGRADE_WAIT", "1200"))
    # The upload host can vanish with the reboot (WLAN of the gateway): also accept the
    # gateway coming back on one of its fallback hosts (its VPN IP) and check from there.
    candidates = [gw] + [dict(gw, vpn_ip=h) for h in gw.get("fallback_hosts") or [] if h and h != host]
    seen = {}

    def _is_up():
        for cand in candidates:
            if fleet.identity(cand)[0]:
                seen["gw"] = cand
                return True
        return False

    back, back_detail = fw.wait_reboot(_is_up, wait, sleep=fleet.sleep, progress=say)
    checks_out = [("Upload", True, up), ("Neustart", back, back_detail)]
    if back and seen["gw"]["vpn_ip"] != host:
        host = seen["gw"]["vpn_ip"]
        checks_out.append(("Nachpruefung ueber", None, f"{host} (Upload-Host nach Neustart weg)"))
    if back:
        say("Nachpruefung: Firmware, Schnittstelle, Drive-by")
        client = fleet._login(host)
        client.get("yruo_wifi", "yruo_wifi")
        checks_out.append(("Firmware", client.firmware == version, f"{before} -> {client.firmware}"))
        err = fw.upgrade_error(host, http=fleet.http)
        checks_out.append(("upgrade_error", err in (None, 0, "0"), str(err)))
        compat = gc.firmware_compat(client, gc.load_profile(gc.profile_for_firmware(client.firmware)))
        checks_out.append(("Schnittstelle", compat["allowed"], compat["status"] + (": " + "; ".join(
            d for d in compat["deltas"] if "neue Felder" not in d) if compat["status"] != "exact" else "")))
        if flows_before is None:   # new gateway without our flow: nothing to check yet (comes in a later step)
            checks_out.append(("Drive-by-Datenweg", None, "noch kein Flow (wird danach installiert)"))
        else:
            db_ok, db_info = checks.check_driveby(host, wait_secs=int(os.getenv("DRIVEBY_WAIT", "75")),
                                                  http=fleet.http, sleep=fleet.sleep)
            checks_out.append(("Drive-by-Datenweg", db_ok, db_info))
        flows_after = _flow_hash(fleet, host)
        checks_out.append(("Node-RED-Flows erhalten", None if flows_before is None else flows_after == flows_before,
                           f"{flows_before} -> {flows_after}"))
    failed = [c for c in checks_out if c[1] is False]
    return {"vpn_ip": host, "result": "failed" if failed else "updated", "detail": plan_txt,
            "checks": [{"label": a, "ok": b, "info": c} for a, b, c in checks_out]}


def from_env(**kw):
    from services.setup.factory import build_inventory
    return Fleet(
        build_inventory(),
        gateway_user=os.getenv("GATEWAY_USER", "admin"),
        gateway_password=kw.pop("gateway_password", None) or os.getenv("GATEWAY_PASSWORD", ""),
        nodered_user=os.getenv("NODERED_USER", os.getenv("GATEWAY_USER", "admin")),
        nodered_password=os.getenv("NODERED_PASSWORD", os.getenv("GATEWAY_PASSWORD", "")),
        backup_dir=os.getenv("FLEET_BACKUP_DIR", os.path.join(os.path.expanduser("~"), ".gatewaychef", "backups")),
        **kw)
