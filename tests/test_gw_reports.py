import unittest
from datetime import datetime, timedelta, timezone

from services import gw_reports as gr


class Cur:
    def __init__(self, prev): self.prev, self.sql = prev, []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.sql.append((sql, params))
    def fetchone(self): return self.prev


class Conn:
    def __init__(self, prev): self.cur = Cur(prev)
    def cursor(self): return self.cur
    def commit(self): pass
    def close(self): pass


class GwReportsTest(unittest.TestCase):
    def setUp(self):
        gr._state.update(ready=True, pruned=1e18)

    def test_clean_drops_unknown_and_validates(self):
        kind, d = gr.clean({"kind": "beat", "ts": 1, "eui": "24e124fffef783e6", "vpn_ip": "172.30.0.116",
                            "uptime_s": "123.4", "password": "x", "sf": {"SF7": 1}})
        self.assertEqual((kind, d["eui"], d["uptime_s"]), ("beat", "24E124FFFEF783E6", 123))
        self.assertNotIn("password", d)
        for bad in ({"kind": "x", "eui": "24E124FFFEF783E6"}, {"kind": "beat"},
                    {"kind": "beat", "vpn_ip": "10.0.0.1"}, {"kind": "beat", "eui": "nothex"}, []):
            with self.assertRaises(gr.ReportError):
                gr.clean(bad)

    def test_boot_detection(self):
        self.assertTrue(gr.is_boot("beat", 100, 5000))       # uptime went down
        self.assertTrue(gr.is_boot("start", 120, None))      # start shortly after boot
        self.assertFalse(gr.is_boot("start", 9000, 8700))    # Node-RED restart only
        self.assertFalse(gr.is_boot("beat", 9000, 8700))

    def test_store_marks_reboot(self):
        conn = Conn((50000,))
        out = gr.store({"kind": "start", "eui": "24E124FFFEF783E6", "uptime_s": 95}, connect=lambda: conn)
        self.assertEqual(out, {"stored": 1, "boots": 1})
        insert = [p for s, p in conn.cur.sql if s.startswith("INSERT")][0]
        self.assertTrue(insert[3])

    def test_buffered_samples_in_order_with_own_time(self):
        conn = Conn((9000,))
        now = 1_800_000_000
        samples = [{"kind": "beat", "eui": "24E124FFFEF783E6", "uptime_s": u, "ts": (now - 60 * i) * 1000}
                   for i, u in ((3, 9100), (2, 9160), (1, 40))]   # rebooted between 2nd and 3rd
        out = gr.store({"samples": list(reversed(samples))}, connect=lambda: conn, now=now)
        self.assertEqual(out, {"stored": 3, "boots": 1})
        ins = [p for s, p in conn.cur.sql if s.startswith("INSERT")]
        self.assertEqual([p[0] for p in ins], [now - 180, now - 120, now - 60])
        self.assertEqual([p[4] for p in ins], [False, False, True])

    def test_timeline_gaps_become_offline(self):
        now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
        pts = [{"t": (now - timedelta(minutes=m)).isoformat(), "boot": m == 60} for m in (120, 119, 118, 60, 59, 58)]
        out = gr.summarize_timeline(pts, days=1, now=now)
        self.assertEqual(len(out["online"]), 2)
        self.assertEqual(len(out["boots"]), 1)
        self.assertEqual(out["no_connection"], [])


if __name__ == "__main__":
    unittest.main()
