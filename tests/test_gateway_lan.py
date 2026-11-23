import os
import tempfile
import unittest
from unittest import mock

import requests

from utils import gateway_lan


class Resp:
    def __init__(self, code):
        self.status_code = code


class Http:
    def __init__(self, alive):
        self.alive, self.asked = set(alive), []

    def get(self, url, timeout=None):
        host = url.split("/")[2]
        self.asked.append(host)
        if host in self.alive:
            return Resp(200)
        raise requests.ConnectionError("down")


def _leases(text):
    fh = tempfile.NamedTemporaryFile("w", suffix=".leases", delete=False)
    fh.write(text)
    fh.close()
    return fh.name


class GatewayLanTest(unittest.TestCase):
    def setUp(self):
        gateway_lan._cache.update(host=None, at=0.0)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ("GATEWAY_DHCP_LEASES", "GATEWAYCHEF_PORT", "GATEWAY_LAN_CANDIDATES", "GATEWAY_IP"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()

    def test_newest_lease_first_then_factory(self):
        path = _leases("1000 aa:bb 192.168.1.101 * *\n2000 cc:dd 192.168.1.120 * *\n")
        self.assertEqual(gateway_lan.candidates(path),
                         ["192.168.1.120", "192.168.1.101", "192.168.1.1", "192.168.23.150"])

    def test_missing_lease_file_uses_factory(self):
        self.assertEqual(gateway_lan.candidates("/nope"), ["192.168.1.1", "192.168.23.150"])

    def test_dhcp_gateway_found(self):
        path = _leases("2000 cc:dd 192.168.1.120 ug65 *\n")
        http = Http({"192.168.1.120"})
        self.assertEqual(gateway_lan.find_host(http=http, lease_path=path), "192.168.1.120")
        self.assertEqual(http.asked, ["192.168.1.120"])

    def test_factory_gateway_found_when_lease_stale(self):
        path = _leases("2000 cc:dd 192.168.1.120 * *\n")
        http = Http({"192.168.23.150"})
        self.assertEqual(gateway_lan.find_host(http=http, lease_path=path), "192.168.23.150")

    def test_nothing_answers(self):
        self.assertIsNone(gateway_lan.find_host(http=Http(set()), lease_path="/nope"))

    def test_lease_file_per_station_port(self):
        os.environ["GATEWAYCHEF_PORT"] = "3"
        self.assertTrue(gateway_lan.lease_file().endswith("dhcp-gcp3.leases"))
        os.environ["GATEWAY_DHCP_LEASES"] = "/tmp/x.leases"
        self.assertEqual(gateway_lan.lease_file(), "/tmp/x.leases")

    def test_env_candidates_and_dedupe(self):
        os.environ["GATEWAY_LAN_CANDIDATES"] = "192.168.1.120, 192.168.23.150"
        path = _leases("2000 cc:dd 192.168.1.120 * *\n")
        self.assertEqual(gateway_lan.candidates(path), ["192.168.1.120", "192.168.23.150"])


if __name__ == "__main__":
    unittest.main()


class ZeroMacRetryTest(unittest.TestCase):
    def test_device_info_retries_zero_mac(self):
        from services.setup import checks
        answers = [{"device": {"mac": "00:00:00:00:00:00"}}, {"device": {"mac": "24:E1:24:F7:83:E6"}}]

        class R:
            def __init__(self, d):
                self.d = d

            def raise_for_status(self):
                pass

            def json(self):
                return self.d

        class H:
            def get(self, url, timeout=None):
                return R(answers.pop(0))

        info = checks.device_info("x", http=H(), sleep=lambda s: None)
        self.assertEqual(info["device"]["mac"], "24:E1:24:F7:83:E6")
        self.assertTrue(checks.zero_mac({"device": {"mac": "00:00:00:00:00:00"}}))
        self.assertFalse(checks.zero_mac({"device": {"mac": "24:E1:24:F7:83:E6"}}))
