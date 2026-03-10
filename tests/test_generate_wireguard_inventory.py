import importlib.util
import unittest
from pathlib import Path

from utils.helpers import derive_wifi_ssid as app_derive_wifi_ssid


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_wireguard_inventory.py"
SPEC = importlib.util.spec_from_file_location("generate_wireguard_inventory", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WireguardInventoryScriptTest(unittest.TestCase):
    def test_derive_wifi_ssid_matches_app_logic(self):
        self.assertEqual(MODULE.derive_wifi_ssid("172.30.1.42"), app_derive_wifi_ssid("172.30.1.42"))

    def test_build_sql_supports_skip_existing_conflict_clause(self):
        sql = MODULE.build_sql(
            [
                {
                    "vpn_ip": "172.30.1.42",
                    "private_key": "secret",
                    "wifi_ssid": "bbdbmon_1.42",
                }
            ],
            status="FREE",
            skip_existing=True,
        )

        self.assertIn("INSERT INTO gateway_inventory", sql)
        self.assertIn("ON CONFLICT (vpn_ip) DO NOTHING", sql)
        self.assertIn("'172.30.1.42'", sql)

    def test_iter_ip_range_rejects_reverse_range(self):
        with self.assertRaises(SystemExit) as ctx:
            list(MODULE.iter_ip_range("172.30.1.10", "172.30.1.1"))

        self.assertIn("--start-ip must be <=", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
