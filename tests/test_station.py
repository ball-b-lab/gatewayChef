import io
import json
import os
import tempfile
import time
import unittest

from services import jobs
from services import station as st

PORTS = [{"port": 1, "iface": "enx1", "vlan": None}, {"port": 2, "iface": "enp2s0", "vlan": 12}]
FOUND = {"host": "192.168.23.150", "eui": "24E124FFFEF783E6"}


class Done:
    def __init__(self, stdout, code=0):
        self.stdout, self.returncode, self.stderr = stdout, code, ""


class Proc:
    def __init__(self, lines, code):
        self.stdout, self.code = io.StringIO("".join(lines)), code

    def wait(self):
        return self.code


def _station(lines, code=0, probe=FOUND, log_dir=""):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return Done(json.dumps(probe) + "\n", 0 if probe.get("host") else 3)

    def popen(cmd, **kw):
        calls.append(cmd)
        return Proc(lines, code)

    s = st.Station(board=jobs.Board(), ports=PORTS, runner=["runner"], popen=popen, run=run, log_dir=log_dir)
    return s, calls


def _wait(job):
    for _ in range(200):
        if job.state != jobs.RUNNING:
            return
        time.sleep(0.01)


class StationTest(unittest.TestCase):
    def test_load_ports(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write("# Kommentar\n1 enx1\n\n3 enp2s0 13  # vlan\nkaputt\n")
        try:
            self.assertEqual(st.load_ports(fh.name), [{"port": 1, "iface": "enx1", "vlan": None},
                                                      {"port": 3, "iface": "enp2s0", "vlan": 13}])
        finally:
            os.unlink(fh.name)
        self.assertEqual(st.load_ports("/nicht/da"), [])

    def test_build_args_rejects_injection(self):
        self.assertEqual(st.build_args("apply", {"new": True, "client_id": "10999", "iccid": "8949 1"}),
                         ["setup", "--live", "--apply", "--new", "--client-id", "10999", "--iccid", "8949 1"])
        for bad in ("--apply", "a;rm -rf /", "x" * 90, "$(id)"):
            with self.assertRaises(st.StationError):
                st.build_args("dry", {"name": bad})
        with self.assertRaises(st.StationError):
            st.build_args("sudo", {})

    def test_setup_job_streams_steps_and_result(self):
        result = {"code": 0, "eui": "24E124FFFEF783E6", "vpn_ip": "172.30.0.120", "name": "0.120 Test",
                  "serial": "SN", "steps": [{"step": "Identitaet", "status": "ok", "detail": ""}]}
        with tempfile.TemporaryDirectory() as d:
            s, calls = _station(["[OK  ] Vorpruefung\n", "     + x: y\n", "[NEU ] Identitaet: 172.30.0.120\n",
                                 "@@RESULT " + json.dumps(result) + "\n"], log_dir=d)
            job = s.start_setup(1, "apply", {"new": True, "client_id": "10999"})
            _wait(job)
            self.assertEqual(calls[-1][:5], ["runner", "1", "setup", "--live", "--apply"])
            self.assertEqual(calls[-1][-2:], ["--host", "192.168.23.150"])
            self.assertEqual(job.state, jobs.OK)
            self.assertEqual(job.step, "[NEU ] Identitaet: 172.30.0.120")
            self.assertEqual(job.gateway["vpn_ip"], "172.30.0.120")
            self.assertFalse(any(l.startswith("@@RESULT") for l in job.lines))
            self.assertEqual(len(os.listdir(d)), 1)

    def test_failed_run_names_open_steps(self):
        res = {"code": 2, "steps": [{"step": "Netz & VPN", "status": "fail", "detail": "x"}]}
        s, _ = _station(["[FEHL] Netz & VPN\n", "@@RESULT " + json.dumps(res) + "\n"], code=2)
        job = s.start_setup(2, "dry")
        _wait(job)
        self.assertEqual((job.state, job.detail), (jobs.FAILED, "offen: Netz & VPN"))

    def test_guards(self):
        s, _ = _station([], probe={"host": None})
        with self.assertRaises(st.StationError):
            s.start_setup(9, "dry")          # unknown port
        with self.assertRaises(st.StationError):
            s.start_setup(1, "dry")          # nothing plugged in
        s, _ = _station([])
        s.board.start("setup", "x", "laeuft", port=1)
        with self.assertRaises(st.StationError):
            s.start_setup(1, "dry")          # port busy

    def test_overview_shows_last_job(self):
        s, _ = _station([])
        job = s.board.start("setup", "EUI", "Einrichten Port 2", port=2)
        job.finish(jobs.OK, "fertig")
        rows = s.overview()
        self.assertEqual(rows[0]["gateway"]["eui"], FOUND["eui"])
        self.assertIsNone(rows[0]["job"])
        self.assertEqual(rows[1]["job"]["state"], jobs.OK)


class BoardTest(unittest.TestCase):
    def test_tracked_states(self):
        orig = jobs.BOARD
        jobs.BOARD = jobs.Board()
        try:
            jobs.tracked("nodered", "172.30.0.1", "Node-RED", lambda: {"result": "updated", "detail": "ok"})
            jobs.tracked("nodered", "172.30.0.2", "Node-RED", lambda: {"result": "failed", "detail": "rollback"})
            with self.assertRaises(RuntimeError):
                jobs.tracked("firmware", "172.30.0.3", "FW", lambda: (_ for _ in ()).throw(RuntimeError("weg")))
            states = {j.target: j.state for j in jobs.BOARD.all()}
            self.assertEqual(states, {"172.30.0.1": jobs.OK, "172.30.0.2": jobs.FAILED, "172.30.0.3": jobs.FAILED})
        finally:
            jobs.BOARD = orig


class RouteTest(unittest.TestCase):
    def test_station_routes(self):
        os.environ.setdefault("OPEN_BROWSER", "false")
        import app as A
        from routes import station as rs
        s, _ = _station(["[OK  ] Vorpruefung\n"])
        rs._station = s
        try:
            c = A.app.test_client()
            self.assertEqual(c.get("/station").status_code, 200)
            ov = c.get("/api/station/overview").get_json()["data"]
            self.assertEqual(len(ov["ports"]), 2)
            r = c.post("/api/station/run", json={"port": 1, "mode": "dry"})
            self.assertEqual(r.status_code, 200)
            job_id = r.get_json()["data"]["id"]
            _wait(s.board.get(job_id))
            self.assertIn("[OK  ] Vorpruefung", c.get(f"/api/station/job/{job_id}").get_json()["data"]["log"])
            self.assertEqual(c.post("/api/station/run", json={"port": 1, "mode": "x"}).status_code, 400)
        finally:
            rs._station = None


if __name__ == "__main__":
    unittest.main()
