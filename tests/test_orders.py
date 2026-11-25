import unittest
from unittest import mock

from services import orders


class OrderActionTest(unittest.TestCase):
    def test_only_non_standard_lns_needs_admin(self):
        self.assertEqual(orders.check_action("patch:lns-nodered-first", admin=False), "patch:lns-nodered-first")
        with self.assertRaises(orders.OrderError):
            orders.check_action("patch:driveby-udp-forward", admin=False)
        self.assertEqual(orders.check_action("patch:driveby-udp-forward", admin=True), "patch:driveby-udp-forward")
        self.assertEqual(orders.check_action("patch:wifi-country-de", admin=False), "patch:wifi-country-de")
        with self.assertRaises(orders.OrderError):
            orders.check_action("firmware", admin=True)

    def test_results_map_to_states(self):
        from services import fleet_align as fa
        f = mock.Mock()
        for res, state in (({"result": "changed"}, orders.DONE), ({"result": "skipped"}, orders.OPEN),
                           ({"result": "skipped", "needs_admin": True}, orders.DONE), ({"result": "failed"}, orders.FAILED)):
            with mock.patch.object(fa, "align", return_value=res) as al:
                self.assertEqual(orders.run_action(f, "1.2.3.4", "align", False)[0], state)
        f.nodered_update.return_value = {"result": "offline"}
        self.assertEqual(orders.run_action(f, "x", "flow", False)[0], orders.OPEN)
        f.patch.return_value = {"result": "changed"}
        self.assertEqual(orders.run_action(f, "x", "patch:wifi-country-de", False)[0], orders.DONE)


if __name__ == "__main__":
    unittest.main()


class ProfileRevisionTest(unittest.TestCase):
    def test_revision_uses_base_profile(self):
        from services import gateway_config as gc
        self.assertEqual(gc.profile_for_firmware("60.0.0.49-r4"), "ug65-60.0.0.49")
        self.assertEqual(gc.profile_for_firmware("60.0.0.50"), "ug65-60.0.0.50")


class DirectLogTest(unittest.TestCase):
    def test_direct_run_is_logged_as_done(self):
        cur = mock.MagicMock()
        conn = mock.MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        orders._state["ready"] = True
        orders.log_direct("172.30.0.5", "patch:wifi-country-de", {"result": "changed", "detail": "WLAN: country_code CN->DE"},
                          "nina", connect=lambda: conn)
        args = cur.execute.call_args[0][1]
        self.assertEqual(args[:4], ("nina", "172.30.0.5", "patch:wifi-country-de", orders.DONE))
        cur.reset_mock()
        orders.log_direct("x", "flow", {"result": "would_change"}, connect=lambda: conn)
        cur.execute.assert_not_called()

    def test_already_done_gets_no_order(self):
        r = orders.create(["a"], "patch:wifi-country-de", already={"a": "schon DE"}, connect=lambda: 1 / 0)
        self.assertEqual((r["created"], r["already_done"]), (0, 1))

    def test_patch_already(self):
        from services import fleet as fl
        p = fl.load_patch("wifi-country-de")
        self.assertTrue(fl.patch_already(p, {"wifi_country": "DE"}))
        self.assertFalse(fl.patch_already(p, {"wifi_country": "CN"}))
        self.assertFalse(fl.patch_already(p, {}))
