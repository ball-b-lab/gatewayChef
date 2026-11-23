import unittest
from unittest import mock

from services import gateway_stats as gs


def resp(code=200, data=None):
    r = mock.Mock(status_code=code)
    r.json.return_value = data or {}
    r.raise_for_status = lambda: None
    return r


class StatsTest(unittest.TestCase):
    def test_chirpstack_sums_datasets(self):
        http = mock.Mock()
        http.get.side_effect = [
            resp(data={"lastSeenAt": "2026-11-23T07:00:00Z", "gateway": {"metadata": {"fw": "x"}}}),
            resp(data={"rxPackets": {"timestamps": ["a", "b"], "datasets": [{"label": "rx", "data": [1, 2]}]},
                       "txPackets": {"timestamps": ["a", "b"], "datasets": [{"data": [0, 1]}, {"data": [1, 1]}]},
                       "rxPacketsPerFreq": {"datasets": [{"label": "868100000", "data": [3, 4]}]}})]
        with mock.patch.object(gs, "CHIRPSTACK_API_TOKEN", "t"):
            out = gs.chirpstack("EUI", 1, http=http)
        self.assertEqual(out["rx"]["values"], [1, 2])
        self.assertEqual(out["tx"]["values"], [1, 2])
        self.assertEqual(out["rx_per_freq"], {"868100000": 7})
        self.assertEqual(http.get.call_args.kwargs["params"]["aggregation"], "HOUR")

    def test_unknown_gateway(self):
        http = mock.Mock()
        http.get.return_value = resp(404)
        with mock.patch.object(gs, "CHIRPSTACK_API_TOKEN", "t"):
            self.assertIn("nicht in ChirpStack", gs.chirpstack("EUI", 7, http=http)["error"])

    def test_vpn_peer(self):
        http = mock.Mock()
        http.get.return_value = resp(data={"generated": 5, "peers": [{"ip": "172.30.1.2", "name": "x"}]})
        self.assertEqual(gs.vpn_peer("172.30.1.2", http=http)["name"], "x")
        self.assertIn("error", gs.vpn_peer("172.30.1.3", http=http))


if __name__ == "__main__":
    unittest.main()
