import unittest

from services import fleet_snapshots as fs


class FakeCur:
    def __init__(self, log): self.log = log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.log.append((sql, params))
    def fetchone(self): return (7,)


class FakeConn:
    def __init__(self): self.log = []; self.closed = False
    def cursor(self): return FakeCur(self.log)
    def commit(self): pass
    def close(self): self.closed = True


ROW = {"vpn_ip": "172.30.0.116", "gateway_name": "JK_Test", "online": True, "firmware": "60.0.0.50",
       "flow": {"version": "1.3.0", "up_to_date": True},
       "driveby": {"receiving": True, "radio": {"crc_error_pct": 4.2}, "devices": [{"id": "A"}, {"id": "B"}]},
       "health": {"cellular": {"net_type": "FDD LTE", "rsrp_dbm": -100, "signal_dbm": -70}, "system": {"uptime_s": 99}},
       "private_key": "SECRET"}


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        fs._state.update(ready=False, last=0.0)

    def test_compact_has_no_secrets(self):
        c = fs.compact(ROW)
        self.assertNotIn("SECRET", str(c))
        self.assertEqual((c["flow"], c["sensors"], c["signal_dbm"], c["crc_error_pct"]), ("1.3.0", 2, -100, 4.2))

    def test_summary(self):
        m = fs.summarize([fs.compact(ROW), fs.compact({"vpn_ip": "x", "online": False})])
        self.assertEqual((m["total"], m["online"], m["offline"], m["lte"], m["flow"]), (2, 1, 1, 1, {"1.3.0": 1}))

    def test_quick_check_throttled_deep_always(self):
        conns = []
        mk = lambda: conns.append(FakeConn()) or conns[-1]
        self.assertEqual(fs.maybe_save([ROW], False, connect=mk, now=10_000), 7)
        self.assertIsNone(fs.maybe_save([ROW], False, connect=mk, now=10_060))
        self.assertEqual(fs.maybe_save([ROW], True, connect=mk, now=10_120), 7)
        self.assertTrue(all(c.closed for c in conns))

    def test_db_error_never_raises(self):
        def boom(): raise RuntimeError("db down")
        self.assertIsNone(fs.maybe_save([ROW], True, connect=boom))


if __name__ == "__main__":
    unittest.main()
