"""
Gateway setup pipeline: one gateway on the bench -> fully provisioned.

  1 Vorpruefung   adapters configured, gateway reachable, login, firmware
  2 Identitaet    EUI from gateway; VPN IP/key, serial, SIM, name from DB/args/Milesight
  3 Datenbank     write master data to gateway_inventory (IN_PROGRESS)
  4 Gateway       write config from profile (only differences), verify
  5 Netz          WireGuard up, Mobilfunk, Packet Forwarder -> LNS, VPN end-to-end
  6 Register      Milesight, ChirpStack, Webservice: find -> create -> find again
  7 Abschluss     all green -> DEPLOYED

Every step is idempotent: re-running on a finished gateway changes nothing
and reports ok. Without apply=True nothing is written anywhere.
"""
import os

from services import gateway_config as gc
from services.setup import checks
from services.setup.model import (CHANGED, FAIL, OK, SKIPPED, WARN, WOULD_CHANGE, Gateway, SetupError,
                                  StepResult, is_valid_eui, normalize_eui)
from utils.helpers import derive_wifi_ssid


class Pipeline:
    def __init__(self, host, profile_name, inventory, registries, gateway_client=None, gateway_user="admin",
                 gateway_password="", wifi_key="", vpn_server_public_key="", vpn_proxy_url="", vpn_proxy_token="",
                 vpn_wait_secs=90, http=None, sleep=None, driveby_wait_secs=None, on_step=None):
        import requests
        import time
        self.host = host
        self.profile_name = profile_name or "auto"
        self.profile = None if self.profile_name == "auto" else gc.load_profile(self.profile_name)
        self.fw_allowed = False
        self.inventory = inventory
        self.registries = registries
        self.client = gateway_client or gc.UG65Client(host)
        self.user, self.password = gateway_user, gateway_password
        self.wifi_key, self.vpn_server_public_key = wifi_key, vpn_server_public_key
        self.vpn_proxy_url, self.vpn_proxy_token, self.vpn_wait_secs = vpn_proxy_url, vpn_proxy_token, vpn_wait_secs
        self.http = http or requests
        self.sleep = sleep or time.sleep
        self.driveby_wait_secs = int(os.getenv("DRIVEBY_WAIT", "75")) if driveby_wait_secs is None else driveby_wait_secs
        self.results = []
        self.on_step = on_step  # called with each StepResult as soon as it is done (live progress)

    # ------------------------------------------------------------ helpers
    def _lns_address(self):
        for section in (self.profile or {}).get("sections", []):
            for serv in section.get("value", {}).get("servs", []):
                if serv.get("serv_type") == "semtech":
                    return serv.get("serv_addr")
        return None

    def _device_vars(self, gw):
        v = gc.device_vars_from_inventory(gw.vpn_ip, gw.private_key, gw.eui, self.wifi_key, gw.wifi_ssid)
        v["vpn_server_public_key"] = self.vpn_server_public_key or gw.server_public_key
        return v

    # ------------------------------------------------------------ steps
    def step_preflight(self, gw, apply):
        r = StepResult("Vorpruefung", OK)
        for reg in self.registries:
            missing = reg.missing_config()
            r.checks.append((f"{reg.name} konfiguriert", True if not missing else None,
                             "ok" if not missing else "fehlt: " + ", ".join(missing) + " (Schritt wird uebersprungen)"))
        try:
            self.inventory.get("0.0.0.0")
            r.checks.append((f"{self.inventory.name} erreichbar", True, "ok"))
        except SetupError as exc:
            r.checks.append((f"{self.inventory.name} erreichbar", False, str(exc)))
        try:
            info = checks.device_info(self.host, http=self.http)
            r.checks.append(("Gateway erreichbar (LAN)", True, self.host))
        except Exception as exc:  # noqa: BLE001
            r.checks.append(("Gateway erreichbar (LAN)", False, str(exc)[:120]))
            r.status = FAIL
            return r, None
        if not self.password:
            r.checks.append(("Gateway-Login", False, "GATEWAY_PASSWORD fehlt"))
            r.status = FAIL
            return r, info
        try:
            self.client.login(self.user, self.password)
            self.client.get("yruo_wifi", "yruo_wifi")   # also fills firmware/model
            r.checks.append(("Gateway-Login", True, self.user))
        except gc.GatewayConfigError as exc:
            r.checks.append(("Gateway-Login", False, str(exc)))
            r.status = FAIL
            return r, info
        if self.profile is None:
            self.profile = gc.load_profile(gc.profile_for_firmware(self.client.firmware))
        compat = gc.firmware_compat(self.client, self.profile)
        self.fw_allowed = compat["allowed"]
        fw, pfw = self.client.firmware, self.profile.get("firmware")
        if compat["status"] == "exact":
            r.checks.append(("Firmware freigegeben", True, f"{fw} (Profil {pfw})"))
        elif compat["allowed"]:
            r.checks.append(("Firmware freigegeben", None,
                             f"{fw} ohne eigenes Profil, Schnittstelle wie {pfw}: Profil wird verwendet"))
            for d in compat["deltas"]:
                r.checks.append(("  Delta", None, d))
            r.status = WARN
        else:
            why = "FIRMWARE_POLICY=strict" if compat["status"] == "compatible" else "Schnittstelle geaendert"
            r.checks.append(("Firmware freigegeben", False, f"{fw}, Profil {pfw}: {why}"))
            for d in compat["deltas"]:
                r.checks.append(("  Delta", False if compat["status"] == "incompatible" else None, d))
            r.status = FAIL
        if any(ok is False for _, ok, _ in r.checks):
            r.status = FAIL
        gw.model, gw.firmware = self.client.model, self.client.firmware
        return r, info

    def step_identity(self, gw, info, apply, allocate_new=False):
        r = StepResult("Identitaet", OK)
        device = (info or {}).get("device") or {}
        gw.mac = device.get("mac")
        gw.eui = normalize_eui(device.get("eui") or gw.eui)
        r.checks.append(("EUI gueltig", is_valid_eui(gw.eui), gw.eui))
        if not is_valid_eui(gw.eui):
            r.status = FAIL
            return r

        by_eui = self.inventory.find_by_eui(gw.eui)
        if not gw.vpn_ip and by_eui:
            gw.vpn_ip = by_eui["vpn_ip"]
            r.checks.append(("VPN-IP aus DB (per EUI)", True, gw.vpn_ip))
        if not gw.vpn_ip and allocate_new:
            if apply:
                free = self.inventory.reserve(gw.eui)
                r.checks.append(("VPN-IP reserviert (atomar)", True, free["vpn_ip"]))
            else:
                free = self.inventory.next_free()
                r.checks.append(("Freie VPN-IP aus Pool (Vorschau, nicht reserviert)", True, free["vpn_ip"]))
            gw.vpn_ip = free["vpn_ip"]
        if not gw.vpn_ip:
            r.checks.append(("VPN-IP bekannt", False, "weder --vpn-ip noch DB-Eintrag zur EUI (--new fuer freie IP)"))
            r.status = FAIL
            return r
        if by_eui and by_eui["vpn_ip"] != gw.vpn_ip:
            r.checks.append(("EUI nicht doppelt vergeben", False, f"EUI steht in DB schon bei {by_eui['vpn_ip']}"))
            r.status = FAIL
            return r

        record = self.inventory.get(gw.vpn_ip)
        if not record:
            r.checks.append(("DB-Eintrag zur VPN-IP", False, f"{gw.vpn_ip} nicht in gateway_inventory"))
            r.status = FAIL
            return r
        rec_eui = normalize_eui(record.get("eui"))
        if rec_eui and rec_eui != gw.eui:
            r.checks.append(("VPN-IP frei fuer dieses Geraet", False, f"{gw.vpn_ip} gehoert in DB zu EUI {rec_eui}"))
            r.status = FAIL
            return r
        gw.private_key = record.get("private_key")
        r.checks.append(("WireGuard-Key in DB", bool(gw.private_key), "vorhanden" if gw.private_key else "fehlt"))
        gw.server_public_key = record.get("server_public_key")
        if self.vpn_server_public_key and gw.server_public_key and self.vpn_server_public_key != gw.server_public_key:
            r.checks.append(("VPN-Server-Key", False, ".env und Cloud liefern verschiedene Server-Keys"))
            r.status = FAIL
            return r
        key_src = "Cloud" if gw.server_public_key else (".env" if self.vpn_server_public_key else None)
        r.checks.append(("VPN-Server-Key", bool(key_src) or None, f"aus {key_src}" if key_src else "fehlt (Cloud: VPN_SERVER_PUBLIC_KEY setzen)"))
        gw.serial_number = gw.serial_number or record.get("serial_number")
        gw.name = gw.name or record.get("gateway_name")
        gw.sim_iccid = gw.sim_iccid or record.get("sim_iccid")
        gw.sim_id = gw.sim_id or record.get("sim_id")
        gw.sim_vendor_id = gw.sim_vendor_id or record.get("sim_vendor_id")
        gw.wifi_ssid = derive_wifi_ssid(gw.vpn_ip)
        gw.lns_address = self._lns_address()

        if not gw.serial_number:
            for reg in self.registries:
                if reg.name == "milesight" and not reg.missing_config():
                    try:
                        found = reg.find(gw)
                    except SetupError:
                        found = None
                    if found and found.get("sn"):
                        gw.serial_number = found["sn"]
                        r.checks.append(("Seriennummer aus Milesight", True, gw.serial_number))
        if not gw.name:
            suffix = ".".join(gw.vpn_ip.split(".")[-2:])
            client = " - ".join(p for p in (gw.client_id, gw.client_name) if p)
            gw.name = f"{suffix} {client}".strip()
        r.checks.append(("Seriennummer", bool(gw.serial_number), gw.serial_number or "fehlt (--serial)"))
        r.checks.append(("SIM ICCID", bool(gw.sim_iccid), gw.sim_iccid or "fehlt (--iccid)"))
        r.checks.append(("Name", bool(gw.name), gw.name))
        if not gw.private_key:
            r.status = FAIL
        elif not (gw.serial_number and gw.sim_iccid):
            r.status = WARN
        return r

    def step_database(self, gw, apply):
        r = StepResult("Datenbank", OK)
        record = self.inventory.get(gw.vpn_ip) or {}
        want = {"eui": gw.eui, "serial_number": gw.serial_number, "gateway_name": gw.name,
                "wifi_ssid": gw.wifi_ssid, "sim_iccid": gw.sim_iccid}
        diff = {k: (record.get(k), v) for k, v in want.items()
                if v and str(record.get(k) or "").upper() != str(v).upper()}
        if diff and gw.sim_iccid and record.get("sim_iccid") != gw.sim_iccid and not gw.sim_vendor_id:
            r.checks.append(("SIM-Vendor bekannt", False, "neue ICCID braucht --sim-vendor-id"))
            r.status = FAIL
            return r
        for k, (have, want_v) in diff.items():
            r.checks.append((f"{k}", None, f"{have!r} -> {want_v!r}"))
        if not diff:
            r.detail = "Stammdaten aktuell"
            return r
        if not apply:
            r.status = WOULD_CHANGE
            return r
        result = self.inventory.save(gw) or {}
        gw.sim_id = gw.sim_id or result.get("sim_id")
        r.status, r.detail = CHANGED, "gateway_inventory aktualisiert (IN_PROGRESS)"
        return r

    def step_gateway_config(self, gw, apply, force_firmware=False, reboot=False):
        r = StepResult("Gateway-Konfiguration", OK)
        dv = self._device_vars(gw)
        plan = gc.plan(self.client, self.profile, dv, skip_missing=not apply)
        for ch in plan["changes"]:
            for key, (have, want) in ch.fields.items():
                r.checks.append((f"{ch.label}.{key}", None, f"{gc._mask(key, have)!r} -> {gc._mask(key, want)!r}"))
            for op in ch.peers:
                r.checks.append((f"{ch.label}.peer {op.get('name')}", None, "anlegen" if op["action"] == 1 else "aendern"))
        for item in plan["skipped"]:
            r.checks.append((item, None, "nicht geprueft (Wert fehlt)"))
        if not plan["changes"]:
            r.detail = "entspricht Profil"
            if plan["skipped"]:
                r.status = WARN
            return r
        if not apply:
            r.status = WOULD_CHANGE
            return r
        gc.execute(self.client, plan, force_firmware=force_firmware or self.fw_allowed)
        verify = gc.plan(self.client, self.profile, dv)
        if verify["changes"]:
            r.status, r.detail = FAIL, "nach dem Schreiben weichen Werte ab: " + ", ".join(c.label for c in verify["changes"])
            return r
        r.status, r.detail = CHANGED, f"{len(plan['changes'])} Bereich(e) geschrieben, zurueckgelesen ok"
        if reboot:
            self.client.reboot()
            r.detail += ", Neustart ausgeloest"
        return r

    def step_network(self, gw, apply):
        r = StepResult("Netz & VPN", OK)
        try:
            info = checks.device_info(self.host, http=self.http)
            lora = checks.lora_info(self.host, http=self.http)
        except Exception as exc:  # noqa: BLE001
            r.status, r.detail = FAIL, f"Gateway antwortet nicht: {exc}"
            return r
        wg_ok, wg_info = checks.check_wireguard_up(info, gw.vpn_ip)
        r.checks.append(("WireGuard-Tunnel am Gateway", wg_ok, wg_info))
        cell_ok, cell_info = checks.check_cellular(info)
        r.checks.append(("Mobilfunk", cell_ok, cell_info))
        lns_ok, lns_info = checks.check_lns_connected(lora, gw.lns_address)
        r.checks.append(("LNS-Verbindung", lns_ok, lns_info))
        health_ok, health_info = checks.check_lora_health(self.host, http=self.http)
        r.checks.append(("Node-RED LoRa-Health", health_ok, health_info))
        vpn_ok, vpn_info = checks.check_vpn_reachable(
            gw.vpn_ip, gw.eui, self.vpn_proxy_url, self.vpn_proxy_token,
            wait_secs=self.vpn_wait_secs if wg_ok else 0, http=self.http, sleep=self.sleep)
        r.checks.append(("VPN-Zugriff Ende-zu-Ende", vpn_ok, vpn_info))
        db_ok, db_info = checks.check_driveby(self.host, wait_secs=self.driveby_wait_secs, http=self.http,
                                              sleep=self.sleep)
        r.checks.append(("Drive-by-Datenweg (Log -> Node-RED)", db_ok, db_info))
        if not (wg_ok and vpn_ok and lns_ok) or db_ok is False:
            r.status = FAIL
        elif not (cell_ok and health_ok and db_ok):
            r.status = WARN
        return r

    def step_registry(self, reg, gw, apply):
        r = StepResult(f"Register: {reg.name}", OK)
        missing = reg.missing_config()
        if missing:
            r.status, r.detail = SKIPPED, "nicht konfiguriert: " + ", ".join(missing)
            return r
        found = reg.find(gw)
        if found:
            r.detail = "Eintrag vorhanden"
            return r
        lacking = [f for f in reg.required_fields() if not getattr(gw, f)]
        if lacking:
            r.status, r.detail = FAIL, "fehlende Angaben: " + ", ".join(lacking)
            return r
        r.checks.append(("anlegen", None, str(reg.describe_create(gw))[:300]))
        if not apply:
            r.status = WOULD_CHANGE
            return r
        reg.create(gw)
        for _ in range(3):
            if reg.find(gw):
                r.status, r.detail = CHANGED, "angelegt und bestaetigt"
                return r
            self.sleep(2)
        r.status, r.detail = WARN, "angelegt, Bestaetigung steht noch aus"
        return r

    def step_finish(self, gw, apply):
        r = StepResult("Abschluss", OK)
        blocking = [x.step for x in self.results if x.status in (FAIL, WOULD_CHANGE, SKIPPED)]
        if blocking:
            r.status, r.detail = SKIPPED, "nicht DEPLOYED, offen: " + ", ".join(blocking)
            return r
        record = self.inventory.get(gw.vpn_ip) or {}
        if record.get("status_overall") == "DEPLOYED":
            r.detail = "bereits DEPLOYED"
            return r
        if not apply:
            r.status = WOULD_CHANGE
            return r
        self.inventory.mark_deployed(gw.vpn_ip)
        r.status, r.detail = CHANGED, "Status DEPLOYED"
        return r

    # ------------------------------------------------------------ run
    def run(self, gw, apply=False, allocate_new=False, force_firmware=False, reboot=False, only_check=False):
        def add(result):
            self.results.append(result)
            if self.on_step:
                self.on_step(result)
            return result

        pre, info = self.step_preflight(gw, apply)
        if add(pre).failed and not (force_firmware and pre.checks and all(
                ok is not False for label, ok, _ in pre.checks if label not in ("Firmware freigegeben", "  Delta"))):
            return self.results
        try:
            if add(self.step_identity(gw, info, apply and not only_check, allocate_new)).failed:
                return self.results
            if not only_check:
                if add(self.step_database(gw, apply)).failed:
                    return self.results
            if add(self.step_gateway_config(gw, apply and not only_check, force_firmware, reboot)).failed:
                return self.results
            if reboot and apply:
                self.sleep(90)
            add(self.step_network(gw, apply))
            for reg in self.registries:
                try:
                    add(self.step_registry(reg, gw, apply and not only_check))
                except SetupError as exc:
                    add(StepResult(f"Register: {reg.name}", FAIL, str(exc)))
            if not only_check:
                add(self.step_finish(gw, apply))
        except (SetupError, gc.GatewayConfigError) as exc:
            add(StepResult("Abbruch", FAIL, str(exc)))
        return self.results


SYMBOL = {OK: "OK  ", CHANGED: "NEU ", WOULD_CHANGE: "DIFF", SKIPPED: "--  ", WARN: "WARN", FAIL: "FEHL"}


def format_results(results, gw=None):
    lines = []
    for res in results:
        lines.append(f"[{SYMBOL[res.status]}] {res.step}" + (f": {res.detail}" if res.detail else ""))
        for label, ok, info in res.checks:
            mark = "  ." if ok is None else ("  +" if ok else "  !")
            lines.append(f"     {mark} {label}: {info}")
    if gw:
        lines.append(f"\nGateway: EUI {gw.eui} · VPN {gw.vpn_ip} · SN {gw.serial_number} · {gw.name}")
    return "\n".join(lines)


def exit_code(results):
    if any(r.status == FAIL for r in results):
        return 2
    if any(r.status == WOULD_CHANGE for r in results):
        return 1
    return 0


def from_env(host, profile_name, **kw):
    from services.setup.factory import build_inventory, build_registries
    return Pipeline(
        host, profile_name, build_inventory(), build_registries(),
        gateway_user=os.getenv("GATEWAY_USER", "admin"), gateway_password=os.getenv("GATEWAY_PASSWORD", ""),
        wifi_key=os.getenv("GATEWAY_WIFI_KEY", ""), vpn_server_public_key=os.getenv("VPN_SERVER_PUBLIC_KEY", ""),
        vpn_proxy_url=os.getenv("VPN_PING_PROVIDER_URL", ""), vpn_proxy_token=os.getenv("VPN_PING_SERVICE_TOKEN", ""),
        **kw)
