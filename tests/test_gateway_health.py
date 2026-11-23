import unittest

from services import fleet


class FakeClient:
    def get(self, core, base):
        return [{"type": "system", "index": 1, "value": {
            "uptime": 3600, "cpu_load": "4%", "memory_avail_percent": "26%", "emmc_avail_percent": "80%",
            "packet_forwarder": {"destinations": [
                {"serv_enabled": True, "serv_addr": "127.0.0.1", "connected": 1},
                {"serv_enabled": True, "serv_addr": "lns.example", "connected": 0},
                {"serv_enabled": False, "serv_addr": "localhost", "connected": 0}]}}}]

    def _call(self, core, function, values):
        return [{"get": [
            {"type": "cellular_modem", "value": {"net_type": "FDD LTE", "signal": "20asu (-73dBm)", "rsrp": "-105dBm",
                                                 "rsrq": "-10dB", "sinr": "12dB", "imsi": "SECRET", "iccid": "SECRET",
                                                 "imei": "SECRET", "cellid": "SECRET", "cur_sim": "SIM1",
                                                 "sim1_flow": "RX: 1 MiB   TX: 1 MiB   ALL: 2 MiB"}},
            {"type": "cellular_network", "value": {"status": "Connected", "ip": "SECRET", "time": "1 days"}}]}]


class GatewayHealthTest(unittest.TestCase):
    def test_reads_cellular_and_system_without_identifiers(self):
        h = fleet.gateway_health(FakeClient())
        self.assertEqual(h["cellular"]["rsrp_dbm"], -105.0)
        self.assertEqual(h["cellular"]["signal_dbm"], -73.0)
        self.assertEqual(h["cellular"]["data_usage"], "RX: 1 MiB   TX: 1 MiB   ALL: 2 MiB")
        self.assertEqual(h["system"]["lns"], [{"addr": "127.0.0.1", "connected": 1}, {"addr": "lns.example", "connected": 0}])
        self.assertNotIn("SECRET", repr(h))

    def test_radio_passes_through(self):
        s = fleet.drive_by_summary({"seconds_since_stat": 10, "radio": {"crc_error_pct": 5}})
        self.assertEqual(s["radio"]["crc_error_pct"], 5)


if __name__ == "__main__":
    unittest.main()
