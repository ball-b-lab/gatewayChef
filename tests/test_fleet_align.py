import unittest
from unittest import mock

from services import fleet_align as fa
from services import gateway_config as gc

GW = {"vpn_ip": "172.30.0.9", "eui": "24E124FFFE000009"}


class FakeClient:
    firmware = "60.0.0.50"

    def __init__(self, log):
        self.log = log

    def set(self, core, base, index, value):
        self.log.append(("set", core, value))

    def apply(self):
        self.log.append(("apply",))


class FakeFleet:
    timeout = 1

    def __init__(self, answers=None, latency=100, lora="ONLINE"):
        self.answers = list(answers or [])
        self.latency, self.lora, self.log = latency, lora, []
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
        return FakeClient(self.log)

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
        f = FakeFleet(lora="OFFLINE")
        ok, why = fa.stability(f, GW, samples=2, interval=0)
        self.assertFalse(ok)
        self.assertIn("LNS", why)

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

    def test_dry_run_writes_nothing(self):
        f = FakeFleet()
        with mock.patch.object(fa, "compare", return_value=_cmp([WIFI])):
            res = fa.align(f, GW["vpn_ip"], apply=False)
        self.assertEqual(res["result"], "would_change")
        self.assertNotIn("plan", res)
        self.assertEqual(f.log, [])


if __name__ == "__main__":
    unittest.main()
