import unittest
from unittest import mock

from services import orders


class OrderActionTest(unittest.TestCase):
    def test_lns_patch_needs_admin(self):
        with self.assertRaises(orders.OrderError):
            orders.check_action("patch:lns-nodered-first", admin=False)
        self.assertEqual(orders.check_action("patch:lns-nodered-first", admin=True), "patch:lns-nodered-first")
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
            self.assertFalse(al.call_args.kwargs["lns"])
        f.nodered_update.return_value = {"result": "offline"}
        self.assertEqual(orders.run_action(f, "x", "flow", False)[0], orders.OPEN)
        f.patch.return_value = {"result": "changed"}
        self.assertEqual(orders.run_action(f, "x", "patch:wifi-country-de", False)[0], orders.DONE)


if __name__ == "__main__":
    unittest.main()
