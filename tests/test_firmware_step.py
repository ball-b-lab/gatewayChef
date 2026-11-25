import os
import unittest

from services.setup import firmware_step as fs
from services.setup.model import CHANGED, FAIL, OK, WOULD_CHANGE

IMAGES = {"60.0.0.49": {"label": "60.0.0.49-r4", "path": "x", "size": 1},
          "60.0.0.50": {"label": "60.0.0.50", "path": "y", "size": 2}}


class Client:
    def __init__(self, firmware):
        self.firmware = firmware

    def login(self, u, p):
        pass

    def get(self, core, base):
        return []


class Pipe:
    def __init__(self, firmware):
        self.client, self.user, self.password, self.host, self.http = Client(firmware), "a", "b", "192.168.23.150", None


class FakeFleet:
    def __init__(self, result):
        self.result, self.inventory = result, None


class FirmwareStepTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FIRMWARE_AUTO_UPGRADE", None)

    def tearDown(self):
        os.environ["FIRMWARE_AUTO_UPGRADE"] = "0"

    def test_newest_and_compare(self):
        self.assertEqual(fs.newest_image({"60.0.0.9": 1, "60.0.0.50": 1, "60.0.0.49": 1}), "60.0.0.50")
        self.assertTrue(fs.is_older("60.0.0.49", "60.0.0.50"))
        self.assertFalse(fs.is_older("60.0.0.50", "60.0.0.50"))

    def test_dry_run_and_current(self):
        r = fs.step_firmware(Pipe("60.0.0.49"), apply=False, images=IMAGES)
        self.assertEqual((r.status, r.detail), (WOULD_CHANGE, "60.0.0.49 -> 60.0.0.50"))
        self.assertEqual(fs.step_firmware(Pipe("60.0.0.50"), apply=True, images=IMAGES).status, OK)
        self.assertEqual(fs.step_firmware(Pipe("60.0.0.49"), apply=True, images={}).status, OK)
        os.environ["FIRMWARE_AUTO_UPGRADE"] = "0"
        self.assertIsNone(fs.step_firmware(Pipe("60.0.0.49"), apply=True, images=IMAGES))

    def test_apply_uses_fleet_upgrade(self):
        from services import fleet as fl
        orig = fl.firmware_upgrade
        try:
            fl.firmware_upgrade = lambda f, gw, v, apply, images, force, progress=None: force and {
                "result": "updated", "checks": [{"label": "Firmware", "ok": True, "info": "49 -> 50"}]}
            p = Pipe("60.0.0.49")
            r = fs.step_firmware(p, apply=True, images=IMAGES, fleet_factory=lambda inv: FakeFleet(None))
            self.assertEqual(r.status, CHANGED)
            self.assertEqual(p.client.firmware, "60.0.0.50")
            fl.firmware_upgrade = lambda f, gw, v, apply, images, force, progress=None: {"result": "failed", "detail": "Neustart"}
            r = fs.step_firmware(Pipe("60.0.0.49"), apply=True, images=IMAGES, fleet_factory=lambda inv: FakeFleet(None))
            self.assertEqual(r.status, FAIL)
        finally:
            fl.firmware_upgrade = orig


if __name__ == "__main__":
    unittest.main()
