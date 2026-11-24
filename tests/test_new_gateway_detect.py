import unittest
from unittest import mock

import requests

from utils import gateway_lan


class Resp:
    def __init__(self, code, text=""): self.status_code, self.text = code, text


class FactoryHttp:
    """192.168.1.1 is a factory UG65: web UI yes, Node-RED device-info no."""
    def get(self, url, timeout=None):
        if url.startswith("http://192.168.1.1/node-red"):
            return Resp(404)
        if url == "http://192.168.1.1/":
            return Resp(200, "<title>Milesight LoRaWAN Gateway</title>")
        raise requests.ConnectionError()


class NewGatewayDetectTest(unittest.TestCase):
    def setUp(self):
        gateway_lan._cache.update(host=None, at=0.0)

    def test_factory_gateway_found_by_web_ui(self):
        with mock.patch.dict("os.environ", {"GATEWAY_LAN_CANDIDATES": "192.168.23.150,192.168.1.1"}):
            self.assertEqual(gateway_lan.find_host(http=FactoryHttp(), lease_path="/nonexistent"), "192.168.1.1")

    def test_other_web_server_is_not_a_gateway(self):
        http = mock.Mock(get=mock.Mock(return_value=Resp(200, "<title>Router</title>")))
        self.assertFalse(gateway_lan.web_answers("10.0.0.1", http=http))

    def test_passwords_ours_then_factory(self):
        with mock.patch.dict("os.environ", {"GATEWAY_PASSWORD": "ours", "GATEWAY_FACTORY_PASSWORD": "password"}):
            self.assertEqual(gateway_lan.gateway_passwords(), ["ours", "password"])

    def test_cgi_identity_reads_eui(self):
        from services import gateway_config as gc

        class C:
            firmware = "60.0.0.50"
            def __init__(self, ok): self.ok = ok
            def login(self, u, p):
                if p != "password": raise gc.GatewayConfigError("bad login")
            def get(self, core, base): return [{"value": {"gateway_id": "24e124fffef00001"}}]
        with mock.patch.dict("os.environ", {"GATEWAY_PASSWORD": "ours", "GATEWAY_FACTORY_PASSWORD": "password"}):
            ident = gateway_lan.cgi_identity("192.168.1.1", client_factory=lambda h: C(True))
        self.assertEqual(ident, {"eui": "24E124FFFEF00001", "firmware": "60.0.0.50"})


if __name__ == "__main__":
    unittest.main()
