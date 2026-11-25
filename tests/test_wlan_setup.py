import os
import unittest
from unittest import mock

import requests

from services import station as st
from utils import wlan_follow


class Run:
    def __init__(self, code=0):
        self.calls, self.code, self.profiles = [], code, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if "profile" in cmd:
            path = cmd[4].split("=", 1)[1]
            with open(path, encoding="utf-8") as fh:
                self.profiles.append(fh.read())
        return mock.Mock(returncode=self.code, stdout="ok", stderr="")


class WlanFollowTest(unittest.TestCase):
    def test_connect_writes_profile_and_removes_it(self):
        run = Run()
        ok, _ = wlan_follow.connect_windows("bbdbmon_0.116", "k<&ey", run=run)
        self.assertTrue(ok)
        self.assertIn("<keyMaterial>k&lt;&amp;ey</keyMaterial>", run.profiles[0])
        self.assertFalse(os.path.exists(run.calls[0][4].split("=", 1)[1]))
        self.assertEqual(run.calls[1][:3], ["netsh", "wlan", "connect"])

    def test_follow_waits_until_gateway_answers(self):
        http = mock.Mock(get=mock.Mock(side_effect=[requests.ConnectionError()] * 2 + [mock.Mock()]))
        ok, info = wlan_follow.follow("bbdbmon_0.116", "k", "192.168.1.1", say=lambda m: None,
                                      sleep=lambda s: None, run=Run(), is_windows=True, http=http)
        self.assertTrue(ok)
        self.assertIn("bbdbmon_0.116", info)

    def test_follow_gives_up(self):
        http = mock.Mock(get=mock.Mock(side_effect=requests.ConnectionError()))
        ok, info = wlan_follow.follow("x", "k", "h", say=lambda m: None, sleep=lambda s: None,
                                      is_windows=False, http=http, wait_secs=0)
        self.assertFalse(ok)
        self.assertIn("neu starten", info)


class StationWlanModeTest(unittest.TestCase):
    def test_no_ports_file_means_wlan_port(self):
        with mock.patch.object(st, "load_ports", return_value=[]), mock.patch.dict(os.environ, {"STATION_WLAN": "1"}):
            s = st.Station()
            self.assertEqual(s.ports(), [st.WLAN_PORT])
            self.assertTrue(s._is_wlan(1))

    def test_wlan_can_be_switched_off(self):
        with mock.patch.object(st, "load_ports", return_value=[]), mock.patch.dict(os.environ, {"STATION_WLAN": "0"}):
            self.assertEqual(st.Station().ports(), [])

    def test_line_writer_splits_lines(self):
        got = []
        w = st._LineWriter(got.append)
        w.write("a\nb")
        w.write("c\n")
        w.write("rest")
        w.flush()
        self.assertEqual(got, ["a\n", "bc\n", "rest"])


if __name__ == "__main__":
    unittest.main()
