import csv
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import pool_refill  # noqa: E402


class FakeInventory:
    def __init__(self, free, used):
        self.status = {"free": free, "total": len(used), "vpn_ips": used}
        self.imported = None

    def pool_status(self):
        return self.status

    def import_csv(self, text):
        self.imported = text
        return {"inserted": text.count("\n") - 1}


class PoolRefillTest(unittest.TestCase):
    def test_pick_skips_used_and_network_addresses(self):
        ips = pool_refill.pick_free_ips("172.30.1.0-172.30.1.5,172.30.2.254-172.30.3.1", ["172.30.1.1", "172.30.1.3"], 6)
        self.assertEqual(ips, ["172.30.1.2", "172.30.1.4", "172.30.1.5", "172.30.2.254", "172.30.3.1"])

    def test_keys_are_valid_wireguard_keys(self):
        import base64
        priv, pub = pool_refill.generate_keypair()
        self.assertEqual((len(base64.b64decode(priv)), len(base64.b64decode(pub))), (32, 32))
        self.assertNotEqual(priv, pub)

    def test_generate_then_import(self):
        inv = FakeInventory(3, ["172.30.1.1"])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pool_refill, "build_inventory", return_value=inv):
            self.assertEqual(pool_refill.main(["--ranges", "172.30.1.1-172.30.1.10", "--min-free", "5"]), 1)
            out = os.path.join(tmp, "p")
            self.assertEqual(pool_refill.main(["--ranges", "172.30.1.1-172.30.1.10", "--min-free", "5",
                                               "--batch", "2", "--generate", "--out", out]), 0)
            self.assertEqual(oct(os.stat(os.path.join(out, "peer_inventory.csv")).st_mode & 0o777), "0o600")
            rows = list(csv.DictReader(open(os.path.join(out, "peer_inventory.csv"))))
            self.assertEqual([r["vpn_ip"] for r in rows], ["172.30.1.2", "172.30.1.3"])
            self.assertEqual(rows[0]["wifi_ssid"], "bbdbmon_1.2")
            peers = open(os.path.join(out, "wg0_peers.conf")).read()
            self.assertIn(f"PublicKey = {rows[0]['public_key']}", peers)
            self.assertNotIn("192.168.1.0/24", peers)
            self.assertNotIn(rows[0]["private_key"], peers)
            self.assertEqual(pool_refill.main(["--import", out]), 0)
            self.assertIn("172.30.1.3", inv.imported)

    def test_enough_free_generates_nothing(self):
        inv = FakeInventory(50, [])
        with mock.patch.object(pool_refill, "build_inventory", return_value=inv), \
                mock.patch.object(pool_refill, "build_rows") as build:
            self.assertEqual(pool_refill.main(["--generate", "--min-free", "20"]), 0)
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
