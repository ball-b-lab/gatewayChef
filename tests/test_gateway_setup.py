import unittest

from services.setup import checks
from services.setup.adapters.base import Inventory, Registry
from services.setup.adapters.webservice import Ws1Webservice, Ws2Webservice
from services.setup.model import CHANGED, FAIL, OK, SKIPPED, WARN, WOULD_CHANGE, Gateway
from services.setup.pipeline import Pipeline, exit_code
from tests.test_gateway_config import VARS, FakeSession, _configured_state
from services.gateway_config import UG65Client

EUI = VARS["gateway_id"]
VPN = "172.30.0.116"


class Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.content, self.text = payload, status, b"x", str(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeHttp:
    """Gateway LAN endpoints + VPN endpoint."""
    def __init__(self, vpn_eui=EUI, wg_ip=VPN, vpn_up=True):
        self.vpn_eui, self.wg_ip, self.vpn_up = vpn_eui, wg_ip, vpn_up

    def get(self, url, timeout=None):
        if url.endswith("/node-red/device-info"):
            if VPN in url:
                if not self.vpn_up:
                    raise checks.requests.ConnectionError("no route")
                return Resp({"device": {"eui": self.vpn_eui}})
            return Resp({"device": {"eui": EUI, "mac": "24:E1:24:F7:83:E6", "interfaces": {
                "wg0": {"up": True, "ip": self.wg_ip}, "cellular0": {"up": True, "ip": "10.0.0.1"}}}})
        if url.endswith("/device-info-lora"):
            return Resp({"servs": [{"servAddr": "ball-b-cs.cortex-media.de", "servEnabled": True, "connected": 1}]})
        if url.endswith("/lora/health"):
            return Resp({"status": "OK", "lns_connected": True, "seconds_since_ack": 3})
        raise AssertionError(url)

    def post(self, url, json=None, headers=None, timeout=None):
        raise AssertionError("no proxy configured")


class MemInventory(Inventory):
    name = "inventory(mem)"

    def __init__(self, rows):
        self.rows = rows
        self.saved, self.deployed = [], []

    def get(self, vpn_ip):
        return self.rows.get(vpn_ip)

    def find_by_eui(self, eui):
        return next((r for r in self.rows.values() if (r.get("eui") or "").upper() == eui), None)

    def next_free(self):
        return next({"vpn_ip": k, "private_key": r["private_key"]} for k, r in self.rows.items()
                    if r["status_overall"] == "FREE")

    def save(self, gw):
        self.saved.append(gw.vpn_ip)
        self.rows[gw.vpn_ip].update(eui=gw.eui, serial_number=gw.serial_number, gateway_name=gw.name,
                                    wifi_ssid=gw.wifi_ssid, sim_iccid=gw.sim_iccid, status_overall="IN_PROGRESS")
        return {"sim_id": "S1"}

    def mark_deployed(self, vpn_ip):
        self.deployed.append(vpn_ip)
        self.rows[vpn_ip]["status_overall"] = "DEPLOYED"


class MemRegistry(Registry):
    def __init__(self, name, exists=False, missing=()):
        self.name, self.exists, self._missing, self.created = name, exists, list(missing), 0

    def missing_config(self):
        return self._missing

    def find(self, gw):
        return {"ok": 1} if self.exists else None

    def create(self, gw):
        self.created += 1
        self.exists = True


def _row(**kw):
    base = {"vpn_ip": VPN, "private_key": "PRIVKEY", "eui": None, "serial_number": None, "gateway_name": None,
            "sim_iccid": None, "sim_id": None, "sim_vendor_id": None, "status_overall": "FREE", "wifi_ssid": "bbdbmon_0.116"}
    base.update(kw)
    return base


def _pipeline(inv, regs, state=None, http=None):
    return Pipeline("192.168.1.1", "ug65-60.0.0.49", inv, regs,
                    gateway_client=UG65Client(session=FakeSession(state or _configured_state())),
                    gateway_password="pw", wifi_key="wifipass", vpn_server_public_key="SERVERPUB",
                    vpn_wait_secs=0, http=http or FakeHttp(), sleep=lambda s: None)


def _status(results):
    return {r.step: r.status for r in results}


class PipelineTest(unittest.TestCase):
    def test_new_gateway_dry_run_writes_nothing(self):
        inv = MemInventory({VPN: _row()})
        ws = MemRegistry("webservice")
        gw = Gateway(serial_number="SN1", sim_iccid="8949", sim_vendor_id="1", client_id="10999")
        results = _pipeline(inv, [ws]).run(gw, allocate_new=True)
        st = _status(results)
        self.assertEqual(st["Datenbank"], WOULD_CHANGE)
        self.assertEqual(st["Register: webservice"], WOULD_CHANGE)
        self.assertEqual(st["Abschluss"], SKIPPED)
        self.assertEqual((inv.saved, ws.created, inv.deployed), ([], 0, []))
        self.assertEqual(exit_code(results), 1)
        self.assertEqual(gw.name, "0.116 10999")

    def test_new_gateway_apply_then_rerun_is_noop(self):
        inv = MemInventory({VPN: _row()})
        ws, ms = MemRegistry("webservice"), MemRegistry("milesight")
        gw = Gateway(serial_number="SN1", sim_iccid="8949", sim_vendor_id="1", client_id="10999")
        state = _configured_state()
        results = _pipeline(inv, [ms, ws], state).run(gw, apply=True, allocate_new=True)
        st = _status(results)
        self.assertEqual(st["Datenbank"], CHANGED)
        self.assertEqual(st["Register: webservice"], CHANGED)
        self.assertEqual(st["Abschluss"], CHANGED, results)
        self.assertEqual(inv.deployed, [VPN])

        again = _pipeline(inv, [ms, ws], state).run(Gateway(), apply=True)
        self.assertTrue(all(r.status == OK for r in again), [(r.step, r.status, r.detail) for r in again])
        self.assertEqual(ws.created, 1)

    def test_eui_already_on_other_vpn_ip_fails(self):
        inv = MemInventory({VPN: _row(), "172.30.0.5": _row(vpn_ip="172.30.0.5", eui=EUI)})
        results = _pipeline(inv, []).run(Gateway(vpn_ip=VPN))
        self.assertEqual(results[-1].status, FAIL)
        self.assertIn("172.30.0.5", str(results[-1].checks))

    def test_vpn_ip_owned_by_other_eui_fails(self):
        inv = MemInventory({VPN: _row(eui="24E124FFFE000001")})
        results = _pipeline(inv, []).run(Gateway(vpn_ip=VPN))
        self.assertEqual(results[-1].status, FAIL)

    def test_vpn_answering_device_must_be_this_gateway(self):
        inv = MemInventory({VPN: _row(eui=EUI, serial_number="SN", sim_iccid="1", gateway_name="n")})
        results = _pipeline(inv, [], http=FakeHttp(vpn_eui="24E124FFFE000001")).run(Gateway())
        net = next(r for r in results if r.step == "Netz & VPN")
        self.assertEqual(net.status, FAIL)
        self.assertIn("anderes Geraet", str(net.checks))

    def test_vpn_down_fails_and_blocks_deployed(self):
        inv = MemInventory({VPN: _row(eui=EUI, serial_number="SN", sim_iccid="1", gateway_name="n")})
        results = _pipeline(inv, [], http=FakeHttp(vpn_up=False)).run(Gateway(), apply=True)
        st = _status(results)
        self.assertEqual(st["Netz & VPN"], FAIL)
        self.assertEqual(st["Abschluss"], SKIPPED)
        self.assertEqual(inv.deployed, [])

    def test_unconfigured_registry_is_skipped_not_fatal(self):
        inv = MemInventory({VPN: _row(eui=EUI, serial_number="SN", sim_iccid="1", gateway_name="n")})
        results = _pipeline(inv, [MemRegistry("webservice", missing=["WEBSERVICE_USER"])]).run(Gateway())
        st = _status(results)
        self.assertEqual(st["Vorpruefung"], OK)
        self.assertEqual(st["Register: webservice"], SKIPPED)

    def test_wrong_firmware_stops_early(self):
        inv = MemInventory({VPN: _row()})
        p = _pipeline(inv, [])
        p.client = UG65Client(session=FakeSession(_configured_state(), firmware="60.0.0.50"))
        results = p.run(Gateway(vpn_ip=VPN), apply=True)
        self.assertEqual([r.step for r in results], ["Vorpruefung"])
        self.assertEqual(results[0].status, FAIL)


class ChecksTest(unittest.TestCase):
    def test_proxy_gateway_http_error_means_tunnel_works(self):
        class Proxy:
            def __init__(self, status, msg):
                self.r = Resp({"ok": False, "data": None, "error": {"message": msg}}, status)

            def post(self, *a, **k):
                return self.r

        ok, _ = checks.check_vpn_reachable(VPN, EUI, proxy_url="https://p", wait_secs=0,
                                           http=Proxy(503, "Gateway Health Fehler 503"))
        self.assertTrue(ok)
        ok, info = checks.check_vpn_reachable(VPN, EUI, proxy_url="https://p", wait_secs=0,
                                              http=Proxy(502, "Gateway Health Fehler: No route to host"))
        self.assertFalse(ok)
        self.assertIn("No route", info)

    def test_wireguard_wrong_ip(self):
        ok, info = checks.check_wireguard_up({"device": {"interfaces": {"wg0": {"up": True, "ip": "172.30.0.9"}}}}, VPN)
        self.assertFalse(ok)


class WebserviceAdapterTest(unittest.TestCase):
    def test_ws1_and_ws2_payloads(self):
        gw = Gateway(eui=EUI, name="0.116 10999", serial_number="SN1", sim_iccid="8949", sim_id="S1",
                     client_id="10999", lns_address="lns.example", model="UG65")
        ws1 = Ws1Webservice("https://ws", "u", "p").describe_create(gw)
        self.assertEqual((ws1["clientId"], ws1["gatewayEui"], ws1["lns"]), (10999, EUI.lower(), 2))
        ws2 = Ws2Webservice("https://ws2", "r", "w").describe_create(gw)
        self.assertEqual(ws2["identifiers"][0], {"type": "eui", "identifier": EUI.lower(), "isPrimary": True})
        self.assertEqual({i["type"] for i in ws2["identifiers"]}, {"eui", "serial", "iccid"})
        self.assertEqual(Ws2Webservice("", "", "").missing_config(), ["WS2_URL", "WS2_READ_KEY", "WS2_WRITE_KEY"])


if __name__ == "__main__":
    unittest.main()
