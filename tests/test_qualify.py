import os
import tempfile
import unittest

from services import profile_check as pc

PROFILE = {"name": "ug65-1.0", "firmware": "1.0", "source": "x",
           "sections": [{"label": "A", "core": "c", "base": "b", "index": 0, "value": {"k": 1}}]}


class FakeClient:
    firmware = "2.0"

    def __init__(self, value):
        self.value = value

    def get(self, core, base):
        return [{"index": 0, "value": self.value}]


DEV = {"device": {"vpn_ip": None, "interfaces": {"eth0": {"up": True, "ip": "192.168.23.150", "primary": True},
                                                 "cellular0": {"up": False}, "wlan0": {"up": True}}}}


class QualifyTest(unittest.TestCase):
    def test_factory_gateway_is_qualifiable(self):
        r = pc.qualify(FakeClient({"k": 2, "new": 1}), PROFILE, DEV)
        self.assertTrue(r["qualifiable"])
        with tempfile.TemporaryDirectory() as d:
            path = pc.approve(r, d, "test")
            self.assertTrue(os.path.basename(path) == "ug65-2.0.json")
            with self.assertRaises(ValueError):
                pc.approve(r, d)

    def test_missing_field_blocks(self):
        r = pc.qualify(FakeClient({"other": 1}), PROFILE, DEV)
        self.assertFalse(r["qualifiable"])
        with self.assertRaises(ValueError):
            pc.approve(r, "/nonexistent")

    def test_missing_interface_blocks(self):
        dev = {"device": {"interfaces": {"eth0": {"up": True}}}}
        self.assertFalse(pc.qualify(FakeClient({"k": 1}), PROFILE, dev)["qualifiable"])


if __name__ == "__main__":
    unittest.main()
