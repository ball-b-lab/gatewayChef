import copy
import unittest

from services import fleet as fl
from services import nodered as nr
from services import profile_check as pc
from services.gateway_config import UG65Client, load_profile
from tests.test_gateway_config import FakeSession, _configured_state

EUI = "24E124FFFEF783E6"
GW = {"vpn_ip": "172.30.0.116", "eui": EUI, "gateway_name": "JK_Test", "status_overall": "DEPLOYED"}
FLOW_V1 = [{"id": "c1", "type": "comment", "name": "gatewaychef-flow 1.0.0", "x": 10, "y": 10},
           {"id": "n1", "type": "http in", "url": "/lora/health", "x": 100, "y": 50}]
FLOW_V2 = FLOW_V1[:1] + [dict(FLOW_V1[1], url="/lora/health2")]
FLOW_V2[0] = dict(FLOW_V2[0], name="gatewaychef-flow 1.1.0")


class Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.content = payload, status, b"x"

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(self.status_code)


class Http:
    def __init__(self, eui=EUI, up=True):
        self.eui, self.up = eui, up

    def get(self, url, timeout=None):
        import requests
        if not self.up:
            raise requests.ConnectionError("down")
        if url.endswith("/device-info"):
            return Resp({"device": {"eui": self.eui}})
        return Resp({"status": "OK"})


class Inv:
    def list_gateways(self):
        return [GW]


class FakeNodeRed:
    def __init__(self, flows, break_on=None):
        self.flows, self.rev, self.deploys, self.break_on = copy.deepcopy(flows), "r1", [], break_on

    def login(self):
        pass

    def settings(self):
        return {"version": "3.1.0"}

    def get_flows(self):
        return {"rev": self.rev, "flows": copy.deepcopy(self.flows)}

    def deploy(self, flows, rev=None):
        self.deploys.append(nr.flow_hash(flows))
        self.flows, self.rev = copy.deepcopy(flows), self.rev + "x"


def bundles():
    return {"1.0.0": {"flows": FLOW_V1, "hash": nr.flow_hash(FLOW_V1)},
            "1.1.0": {"flows": FLOW_V2, "hash": nr.flow_hash(FLOW_V2)}}


class NodeRedTest(unittest.TestCase):
    def test_layout_moves_do_not_change_hash(self):
        moved = [dict(n, x=n["x"] + 40) for n in reversed(FLOW_V1)]
        self.assertEqual(nr.flow_hash(moved), nr.flow_hash(FLOW_V1))

    def test_identify_known_modified_unknown(self):
        b = bundles()
        self.assertEqual(nr.identify(FLOW_V1, b)["version"], "1.0.0")
        edited = FLOW_V1[:1] + [dict(FLOW_V1[1], url="/x")]
        self.assertEqual((nr.identify(edited, b)["version"], nr.identify(edited, b)["modified"]), ("1.0.0", True))
        self.assertIsNone(nr.identify(FLOW_V1[1:], b)["version"])
        self.assertEqual(nr.latest_version({"1.9.0": 1, "1.10.0": 1}), "1.10.0")

    def test_update_success_and_rollback(self):
        client = FakeNodeRed(FLOW_V1)
        out = nr.update(client, bundles()["1.1.0"], lambda: (True, "ok"), sleep=lambda s: None)
        self.assertEqual(out["result"], "updated")
        self.assertEqual(nr.flow_hash(client.flows), nr.flow_hash(FLOW_V2))

        client = FakeNodeRed(FLOW_V1)
        checks = iter([(False, "health tot"), (True, "wieder ok")])
        out = nr.update(client, bundles()["1.1.0"], lambda: next(checks), sleep=lambda s: None)
        self.assertEqual((out["result"], out["rolled_back"], out["rollback_ok"]), ("failed", True, True))
        self.assertEqual(nr.flow_hash(client.flows), nr.flow_hash(FLOW_V1))


def _fleet(state=None, http=None, nodered=None):
    session = FakeSession(state or _configured_state())
    return fl.Fleet(Inv(), gateway_password="pw", http=http or Http(), sleep=lambda s: None, reachable_wait=0,
                    client_factory=lambda host: UG65Client(host, session=session),
                    nodered_factory=lambda host: nodered or FakeNodeRed(FLOW_V1)), session


class HealthHttp(Http):
    def get(self, url, timeout=None):
        if url.endswith("/driveby/health"):
            return Resp({"source": "udp:1702", "flow_version": "1.1.0", "seconds_since_stat": 12,
                         "seconds_since_rxpk": 40, "counts": {"rxpk": 7},
                         "app": {"seconds_since_poll": 3, "last_poll": "2026-11-20T08:00:00Z",
                                 "client": "192.168.1.50", "polls": 99}})
        return super().get(url, timeout)


class FleetTest(unittest.TestCase):
    def test_gateway_without_flow_is_online_via_web_login(self):
        class NoFlow(Http):
            def get(self, url, timeout=None):
                return Resp({}, status=404)
        f, _ = _fleet(http=NoFlow())
        ok, detail, _ = f.identity(GW)
        self.assertTrue(ok)
        self.assertIn("ohne Drive-by-Flow", detail)
        f, _ = _fleet(http=Http(up=False))
        self.assertFalse(f.identity(GW)[0])

    def test_status_shows_driveby_and_app_poll(self):
        f, _ = _fleet(http=HealthHttp())
        d = f.status()[0]["driveby"]
        self.assertEqual((d["flow_version"], d["receiving"], d["rxpk"], d["app_seconds_since_poll"], d["app_client"]),
                         ("1.1.0", True, 7, 3, "192.168.1.50"))

    def test_status_old_flow_has_no_driveby(self):
        f, _ = _fleet()
        self.assertIsNone(f.status()[0]["driveby"])

    def test_status_shows_wrong_eui(self):
        f, _ = _fleet(http=Http(eui="24E124FFFE000001"))
        row = f.status()[0]
        self.assertFalse(row["online"])
        self.assertIn("DB erwartet", row["identity"])

    def test_deep_status(self):
        state = _configured_state()
        state[("yruo_wifi", "yruo_wifi")][0]["value"]["country_code"] = "CN"
        f, _ = _fleet(state)
        row = f.probe(GW, deep=True, bundles=bundles())
        self.assertEqual((row["firmware"], row["profile_ok"], row["wifi_country"]), ("60.0.0.49", True, "CN"))
        self.assertEqual(row["flow"]["version"], "1.0.0")
        self.assertFalse(row["flow"]["up_to_date"])

    def test_wifi_patch_dry_apply_verify(self):
        state = _configured_state()
        state[("yruo_wifi", "yruo_wifi")][0]["value"]["country_code"] = "CN"
        f, session = _fleet(state)
        patch = fl.load_patch("wifi-country-de")
        self.assertEqual(f.patch(GW["vpn_ip"], patch)["result"], "would_change")
        self.assertEqual(state[("yruo_wifi", "yruo_wifi")][0]["value"]["country_code"], "CN")
        res = f.patch(GW["vpn_ip"], patch, apply=True)
        self.assertEqual(res["result"], "changed", res)
        self.assertEqual(state[("yruo_wifi", "yruo_wifi")][0]["value"]["country_code"], "DE")
        self.assertEqual(f.patch(GW["vpn_ip"], patch)["result"], "ok")

    def test_risky_patch_blocked_and_wrong_firmware_skipped(self):
        f, _ = _fleet()
        risky = {"name": "x", "sections": [{"core": "yruo_wireguard", "base": "yruo_wireguard", "index": 1,
                                            "value": {"port": 1}}]}
        with self.assertRaises(fl.FleetError):
            f.patch(GW["vpn_ip"], risky, apply=True)
        # other firmware, field still there -> written with note
        patch = dict(fl.load_patch("wifi-country-de"), firmware=["99.0"])
        state = _configured_state()
        state[("yruo_wifi", "yruo_wifi")][0]["value"]["country_code"] = "CN"
        f, _ = _fleet(state)
        res = f.patch(GW["vpn_ip"], patch, apply=True)
        self.assertEqual(res["result"], "changed", res)
        self.assertIn("ungeprueft", res["detail"])
        # other firmware, field renamed -> skipped, nothing written
        state = _configured_state()
        wifi = state[("yruo_wifi", "yruo_wifi")][0]["value"]
        wifi["region"] = wifi.pop("country_code")
        f, session = _fleet(state)
        res = f.patch(GW["vpn_ip"], patch, apply=True)
        self.assertEqual(res["result"], "skipped")
        self.assertIn("country_code", res["detail"])
        self.assertFalse([c for c in session.calls if c["function"] == "set"])

    def test_patch_offline_gateway_not_written(self):
        f, session = _fleet(http=Http(up=False))
        self.assertEqual(f.patch(GW["vpn_ip"], fl.load_patch("wifi-country-de"), apply=True)["result"], "offline")
        self.assertEqual(session.calls, [])

    def test_nodered_update_via_fleet(self):
        client = FakeNodeRed(FLOW_V1)
        f, _ = _fleet(nodered=client)
        orig = nr.load_bundles
        nr.load_bundles = lambda *a: bundles()
        try:
            self.assertEqual(f.nodered_update(GW["vpn_ip"])["result"], "would_change")
            self.assertEqual(client.deploys, [])
            res = f.nodered_update(GW["vpn_ip"], apply=True)
            self.assertEqual((res["result"], res["before"], res["version"]), ("updated", "1.0.0", "1.1.0"))
            self.assertEqual(f.nodered_update(GW["vpn_ip"])["result"], "ok")
        finally:
            nr.load_bundles = orig


class ProfileCheckTest(unittest.TestCase):
    def test_same_firmware_is_compatible(self):
        client = UG65Client(session=FakeSession(_configured_state()))
        self.assertTrue(pc.check(client, load_profile("ug65-60.0.0.49"))["compatible"])

    def test_renamed_field_and_missing_section(self):
        state = _configured_state()
        wifi = state[("yruo_wifi", "yruo_wifi")][0]["value"]
        wifi["region"] = wifi.pop("country_code")
        del state[("yruo_system", "general")]

        class S(FakeSession):
            def post(self, url, data, timeout):
                import json
                body = json.loads(data)
                if body["function"] == "get" and (body["core"], body["values"][0]["base"]) not in self.state:
                    from tests.test_gateway_config import FakeResponse
                    return FakeResponse({"status": 0, "rtver": "60.0.0.60", "model": "UG65",
                                         "result": [{"error": "unknown base"}]})
                return super().post(url, data, timeout)

        client = UG65Client(session=S(state, firmware="60.0.0.60"))
        result = pc.check(client, load_profile("ug65-60.0.0.49"))
        problems = {(r["label"], r["problem"]) for r in result["report"]}
        self.assertIn(("WLAN", "Feld fehlt"), problems)
        self.assertIn(("System-Dienste", "Abschnitt fehlt"), problems)
        self.assertFalse(result["compatible"])
        draft_wifi = next(s for s in result["draft"]["sections"] if s["label"] == "WLAN")
        self.assertNotIn("country_code", draft_wifi["value"])
        self.assertEqual(result["draft"]["firmware"], "60.0.0.60")


if __name__ == "__main__":
    unittest.main()
