import base64
import copy
import json
import unittest

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from services.gateway_config import (
    GatewayConfigError,
    UG65Client,
    device_vars_from_inventory,
    encrypt_login_password,
    execute,
    format_plan,
    load_profile,
    plan,
)

VARS = {
    "gateway_id": "24E124FFFEF783E6",
    "vpn_address": "172.30.0.116/32",
    "vpn_private_key": "PRIVKEY",
    "wifi_ssid": "bbdbmon_0.116",
    "wifi_key": "wifipass",
    "vpn_server_public_key": "SERVERPUB",
}


def _configured_state():
    """Gateway state that matches the profile exactly."""
    profile = load_profile("ug65-60.0.0.49")
    state = {}
    from services.gateway_config import render

    for section in render(profile["sections"], VARS):
        value = copy.deepcopy(section["value"])
        value["extra_field"] = "untouched"
        state[(section["core"], section["base"])] = [{"type": section["base"], "index": section["index"], "value": value}]
    return state


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, state, firmware="60.0.0.49"):
        self.state = state
        self.firmware = firmware
        self.calls = []

    def post(self, url, data, timeout):
        body = json.loads(data)
        self.calls.append(body)
        core, fn = body["core"], body["function"]
        result = []
        if fn == "get":
            result = [{"get": copy.deepcopy(self.state[(core, body["values"][0]["base"])])}]
        elif fn == "set":
            item = body["values"][0]
            entry = self.state[(core, item["base"])][0]["value"]
            value = dict(item["value"])
            for op in value.pop("peers", []):
                peers = entry.setdefault("peers", [])
                op = {k: v for k, v in op.items() if k != "action"}
                peers[:] = [p for p in peers if p.get("name") != op["name"]] + [op]
            entry.update(value)
        return FakeResponse({"status": 0, "rtver": self.firmware, "model": "UG65", "result": result})


class GatewayConfigTest(unittest.TestCase):
    def test_password_encryption_roundtrip(self):
        token = encrypt_login_password("geheim")
        decryptor = Cipher(algorithms.AES(b"1" * 16), modes.CBC(b"2" * 16)).decryptor()
        raw = decryptor.update(base64.b64decode(token)) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        self.assertEqual(unpadder.update(raw) + unpadder.finalize(), b"geheim")

    def test_configured_gateway_has_no_changes(self):
        client = UG65Client(session=FakeSession(_configured_state()))
        result = plan(client, load_profile("ug65-60.0.0.49"), VARS)
        self.assertTrue(result["firmware_ok"])
        self.assertEqual(result["changes"], [])

    def test_fresh_gateway_gets_device_values_and_verifies(self):
        state = _configured_state()
        state[("yruo_wifi", "yruo_wifi")][0]["value"]["ssid"] = "Gateway_F783E6"
        state[("yruo_cell", "yruo_cell")][0]["value"]["apn1"] = ""
        state[("yruo_wireguard", "yruo_wireguard")][0]["value"]["peers"] = []
        session = FakeSession(state)
        client = UG65Client(session=session)

        result = plan(client, load_profile("ug65-60.0.0.49"), VARS)
        labels = {c.label for c in result["changes"]}
        self.assertEqual(labels, {"WLAN", "Mobilfunk", "WireGuard wg0"})
        wg = next(c for c in result["changes"] if c.label == "WireGuard wg0")
        self.assertEqual(wg.peers[0]["action"], 1)

        text = format_plan(result)
        self.assertIn("'Gateway_F783E6' -> 'bbdbmon_0.116'", text)

        self.assertEqual(execute(client, result), 3)
        self.assertEqual(session.calls[-1]["core"], "yruo_apply")
        sets = [c for c in session.calls if c["function"] == "set"]
        wifi_set = next(c for c in sets if c["core"] == "yruo_wifi")
        self.assertEqual(wifi_set["values"][0]["value"], {"ssid": "bbdbmon_0.116"})
        self.assertEqual(plan(client, load_profile("ug65-60.0.0.49"), VARS)["changes"], [])
        self.assertEqual(state[("yruo_wifi", "yruo_wifi")][0]["value"]["extra_field"], "untouched")

    def test_secrets_are_masked_in_output(self):
        state = _configured_state()
        state[("yruo_wireguard", "yruo_wireguard")][0]["value"]["private_key"] = "OLDKEY"
        client = UG65Client(session=FakeSession(state))
        text = format_plan(plan(client, load_profile("ug65-60.0.0.49"), VARS))
        self.assertNotIn("PRIVKEY", text)
        self.assertNotIn("OLDKEY", text)
        self.assertIn("***(7)", text)

    def test_unknown_firmware_blocks_execute(self):
        state = _configured_state()
        state[("yruo_cell", "yruo_cell")][0]["value"]["apn1"] = ""
        client = UG65Client(session=FakeSession(state, firmware="60.0.0.50"))
        result = plan(client, load_profile("ug65-60.0.0.49"), VARS)
        self.assertFalse(result["firmware_ok"])
        with self.assertRaises(GatewayConfigError):
            execute(client, result)

    def test_readonly_status_fields_are_ignored(self):
        state = _configured_state()
        for serv in state[("yruo_loragw", "general_conf")][0]["value"]["servs"]:
            serv["connected"] = 1
        client = UG65Client(session=FakeSession(state))
        self.assertEqual(plan(client, load_profile("ug65-60.0.0.49"), VARS)["changes"], [])

    def test_missing_device_value_raises(self):
        client = UG65Client(session=FakeSession(_configured_state()))
        with self.assertRaises(GatewayConfigError):
            plan(client, load_profile("ug65-60.0.0.49"), dict(VARS, wifi_key=None))

    def test_dry_run_skips_missing_secrets_but_blocks_execute(self):
        client = UG65Client(session=FakeSession(_configured_state()))
        partial = dict(VARS, vpn_private_key=None, wifi_key=None, vpn_server_public_key=None)
        result = plan(client, load_profile("ug65-60.0.0.49"), partial, skip_missing=True)
        self.assertEqual(result["changes"], [])
        self.assertEqual(len(result["skipped"]), 3)
        self.assertIn("nicht geprueft", format_plan(result))
        with self.assertRaises(GatewayConfigError):
            execute(client, result)

    def test_session_expired(self):
        class Expired(FakeSession):
            def post(self, url, data, timeout):
                return FakeResponse({"status": -2, "result": [-32001, "Session not found"]})

        with self.assertRaises(GatewayConfigError):
            UG65Client(session=Expired({})).get("yruo_wifi", "yruo_wifi")

    def test_device_vars_from_inventory(self):
        v = device_vars_from_inventory("172.30.1.42", "K", "24:e1:24:ff:fe:00:00:01", "w")
        self.assertEqual(v["vpn_address"], "172.30.1.42/32")
        self.assertEqual(v["wifi_ssid"], "bbdbmon_1.42")
        self.assertEqual(v["gateway_id"], "24E124FFFE000001")




class ApplyTimeoutTest(unittest.TestCase):
    def test_apply_read_timeout_is_tolerated(self):
        import requests as rq

        class Slow:
            def post(self, url, data, timeout):
                self.timeout = timeout
                raise rq.ReadTimeout("slow")

        s = Slow()
        self.assertEqual(UG65Client(session=s, timeout=8).apply(), [])
        self.assertEqual(s.timeout, 60)

        class Down:
            def post(self, url, data, timeout):
                raise rq.ConnectionError("down")

        with self.assertRaises(GatewayConfigError):
            UG65Client(session=Down()).apply()


if __name__ == "__main__":
    unittest.main()


class Apply503Test(unittest.TestCase):
    def test_apply_tolerates_503_while_services_restart(self):
        class R:
            status_code = 503

            def json(self):
                raise ValueError("html")

        class S:
            def post(self, *a, **kw):
                return R()
        from services.gateway_config import GatewayConfigError, UG65Client
        c = UG65Client("gw", session=S())
        c.BUSY_RETRIES = 1
        self.assertEqual(c.apply(), [])
        with self.assertRaises(GatewayConfigError) as cm:
            c.set("yruo_wifi", "yruo_wifi", 0, {})
        self.assertIn("yruo_wifi/set", str(cm.exception))


class Busy503RetryTest(unittest.TestCase):
    def test_get_retries_after_503(self):
        from unittest import mock
        from services.gateway_config import UG65Client
        answers = [503, 503, 200]

        class R:
            def __init__(self, code):
                self.status_code = code

            def json(self):
                if self.status_code != 200:
                    raise ValueError("html")
                return {"status": 0, "result": [{"get": [{"x": 1}]}]}

        class S:
            def post(self, *a, **kw):
                return R(answers.pop(0))
        with mock.patch("services.gateway_config.time.sleep"):
            self.assertEqual(UG65Client("gw", session=S()).get("yruo_loragw", "x"), [{"x": 1}])
