import os
import unittest
from unittest import mock

from services import fleet_align as fa
from services import gateway_config as gc

GW = {"vpn_ip": "172.30.0.9", "eui": "24E124FFFE000009"}


class FakeClient:
    firmware = "60.0.0.50"

    def __init__(self, log, connected=1):
        self.log, self.connected = log, connected

    def get(self, core, base):
        return [{"value": {"servs": [
            {"serv_enabled": True, "serv_type": "semtech", "serv_addr": "127.0.0.1", "connected": 1},
            {"serv_enabled": True, "serv_type": "semtech", "serv_addr": "lns.example", "connected": self.connected}]}}]

    def set(self, core, base, index, value):
        self.log.append(("set", core, value))

    def apply(self):
        self.log.append(("apply",))


class FakeFleet:
    timeout = 1

    def __init__(self, answers=None, latency=100, lora="ONLINE", connected=1):
        self.answers = list(answers or [])
        self.latency, self.lora, self.log, self.connected = latency, lora, [], connected
        self.sleep = lambda s: None
        self.http = self

    def _gateway(self, ip):
        return dict(GW)

    def identity(self, gw):
        ok = self.answers.pop(0) if self.answers else True
        return ok, "ok" if ok else "timeout", self.latency

    def get(self, url, timeout=None):
        lora = self.lora

        class R:
            def json(self_inner):
                return {"status": lora}
        return R()

    def _login(self, host):
        return FakeClient(self.log, self.connected)

    def wait_reachable(self, gw):
        return True, "ok"

    def nodered_update(self, ip, version, apply=False):
        self.log.append(("flow", version))
        return {"result": "updated"}


def _cmp(changes, flow_ok=True):
    plan = {"changes": changes, "skipped": []}
    return {"vpn_ip": GW["vpn_ip"], "result": "would_change", "detail": "x", "plan": plan, "client": None,
            "changes": fa._changes_out(changes), "flow": {"current": "1.1", "target": "1.1.1", "ok": flow_ok}}


LNS = gc.Change("yruo_loragw", "general_conf", 0, "Packet Forwarder",
                {"servs": ([{"id": 0, "serv_addr": "localhost", "connected": 1}], [{"id": 0, "serv_addr": "127.0.0.1"}])})
WIFI = gc.Change("yruo_wifi", "yruo_wifi", 0, "WLAN", {"country_code": ("CN", "DE")})


class AlignTest(unittest.TestCase):
    def test_unstable_gateway_is_not_touched(self):
        f = FakeFleet(answers=[True, False])
        with mock.patch.object(fa, "compare", return_value=_cmp([WIFI, LNS], flow_ok=False)):
            res = fa.align(f, GW["vpn_ip"], apply=True)
        self.assertEqual(res["result"], "skipped")
        self.assertEqual(f.log, [])

    def test_lns_offline_blocks(self):
        f = FakeFleet(connected=0)
        ok, why = fa.stability(f, GW, samples=2, interval=0)
        self.assertFalse(ok)
        self.assertIn("lns.example nicht verbunden", why)

    def test_nodered_display_does_not_block(self):
        # /lora/health OFFLINE/UNKNOWN on older flows while the forwarder is connected: stable
        f = FakeFleet(lora="UNKNOWN")
        ok, why = fa.stability(f, GW, samples=2, interval=0)
        self.assertTrue(ok, why)
        self.assertIn("lns.example verbunden", why)

    def test_order_flow_params_lns(self):
        f = FakeFleet()
        with mock.patch.object(fa, "compare", return_value=_cmp([LNS, WIFI], flow_ok=False)), \
                mock.patch.object(fa, "_left", return_value=[]), \
                mock.patch.object(fa, "_verify_lns", return_value=(True, "ok")):
            res = fa.align(f, GW["vpn_ip"], apply=True)
        self.assertEqual(res["result"], "changed", res)
        kinds = [e[1] if e[0] in ("flow", "set") else e[0] for e in f.log]
        self.assertEqual(kinds, ["1.1.1", "yruo_wifi", "apply", "yruo_loragw", "apply"])

    def test_lns_failure_rolls_back_old_servs(self):
        f = FakeFleet()
        with mock.patch.object(fa, "compare", return_value=_cmp([LNS])), \
                mock.patch.object(fa, "_verify_lns", side_effect=[(False, "kein Empfang"), (True, "ok")]):
            res = fa.align(f, GW["vpn_ip"], apply=True)
        self.assertEqual(res["result"], "failed")
        self.assertTrue(res["rolled_back"] and res["rollback_ok"])
        sets = [e for e in f.log if e[0] == "set"]
        self.assertEqual(sets[-1][2], {"servs": [{"id": 0, "serv_addr": "localhost"}]})  # status field stripped

    def test_timeout_while_writing_lns_still_verifies(self):
        import requests
        f = FakeFleet()

        class Slow(FakeClient):
            def set(self, core, base, index, value):
                super().set(core, base, index, value)
                if core == "yruo_loragw" and len([e for e in self.log if e[0] == "set"]) == 1:
                    try:
                        raise requests.ReadTimeout("slow")
                    except requests.ReadTimeout as exc:
                        raise gc.GatewayConfigError("Gateway nicht erreichbar") from exc
        f._login = lambda host: Slow(f.log)
        with mock.patch.object(fa, "compare", return_value=_cmp([LNS])), \
                mock.patch.object(fa, "_verify_lns", return_value=(True, "ok")) as verify:
            res = fa.align(f, GW["vpn_ip"], apply=True)
        self.assertEqual(res["result"], "changed", res)
        verify.assert_called_once()

    def test_standard_lns_is_driveby_udp_forward(self):
        prof = {"firmware": "60.0.0.50", "sections": [
            {"core": "yruo_loragw", "base": "general_conf", "index": 0, "value": {"servs": [{"id": 0, "serv_addr": "127.0.0.1"}]}}]}
        for fwv in ("60.0.0.48-r2", "60.0.0.50"):
            servs = fa._standard(prof, fwv)["sections"][0]["value"]["servs"]
            self.assertEqual([x["serv_addr"] for x in servs], ["localhost", "ball-b-cs.cortex-media.de", "127.0.0.1"])
        self.assertEqual(prof["sections"][0]["value"]["servs"][0]["serv_addr"], "127.0.0.1")  # profile untouched

    def test_profiles_use_standard_lns(self):
        import glob, json
        for path in glob.glob(os.path.join(os.path.dirname(__file__), "..", "gateway_profiles", "ug65-*.json")):
            for sec in json.load(open(path))["sections"]:
                if sec["core"] == "yruo_loragw" and "servs" in sec["value"]:
                    self.assertEqual(sec["value"]["servs"], fa.LEGACY_SERVS, path)

    def test_without_admin_lns_is_not_written(self):
        f = FakeFleet()
        with mock.patch.object(fa, "compare", return_value=_cmp([LNS, WIFI])), \
                mock.patch.object(fa, "_left", return_value=[]):
            res = fa.align(f, GW["vpn_ip"], apply=True, lns=False)
        self.assertEqual(res["result"], "changed", res)
        self.assertNotIn("yruo_loragw", [e[1] for e in f.log if e[0] == "set"])
        with mock.patch.object(fa, "compare", return_value=_cmp([LNS])):
            res = fa.align(FakeFleet(), GW["vpn_ip"], apply=True, lns=False)
        self.assertEqual(res["result"], "skipped")
        self.assertTrue(res["needs_admin"])

    def test_dry_run_writes_nothing(self):
        f = FakeFleet()
        with mock.patch.object(fa, "compare", return_value=_cmp([WIFI])):
            res = fa.align(f, GW["vpn_ip"], apply=False)
        self.assertEqual(res["result"], "would_change")
        self.assertNotIn("plan", res)
        self.assertEqual(f.log, [])


if __name__ == "__main__":
    unittest.main()
