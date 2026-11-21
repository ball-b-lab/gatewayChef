"""
Setup station with several ports at once (Linux, one network namespace per
port, see scripts/linux/ports.sh). The web UI starts the setup pipeline per
port as a subprocess via the root helper `gatewaychef-port` and streams its
output onto the job board (services/jobs.py).

Every UG65 comes with the same fixed factory IP and no DHCP. The namespaces
keep them apart, so the pipeline runs unchanged with `--host <factory ip>`.
"""
import json
import os
import re
import shlex
import subprocess
import threading
import time

from services import jobs

PORTS_FILE = os.getenv("STATION_PORTS_FILE", "/etc/gatewaychef/ports")
_SAFE = re.compile(r"^[\w .:+\-/äöüÄÖÜß]{1,80}$")
MODES = {"check": ["--check"], "dry": [], "apply": ["--apply"]}
OPTION_FLAGS = {"client_id": "--client-id", "client_name": "--client-name", "iccid": "--iccid",
                "sim_vendor_id": "--sim-vendor-id", "serial": "--serial", "name": "--name", "vpn_ip": "--vpn-ip"}


class StationError(Exception):
    pass


def runner_prefix():
    return shlex.split(os.getenv("STATION_RUNNER", "sudo -n /usr/local/sbin/gatewaychef-port"))


def load_ports(path=None):
    """[{"port": 1, "iface": "enx...", "vlan": None}, ...] from the ports file (missing file -> [])."""
    path = path or PORTS_FILE
    ports = []
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                parts = raw.split("#", 1)[0].split()
                if len(parts) >= 2 and parts[0].isdigit():
                    ports.append({"port": int(parts[0]), "iface": parts[1],
                                  "vlan": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None})
    except OSError:
        return []
    return sorted(ports, key=lambda p: p["port"])


def build_args(mode, opts):
    if mode not in MODES:
        raise StationError(f"Modus {mode!r} unbekannt (check|dry|apply)")
    args = ["setup", "--live"] + MODES[mode]
    opts = opts or {}
    if opts.get("new"):
        args.append("--new")
    for key, flag in OPTION_FLAGS.items():
        val = str(opts.get(key) or "").strip()
        if not val:
            continue
        if not _SAFE.match(val) or val.startswith("-"):
            raise StationError(f"Wert fuer {key} ungueltig")
        args += [flag, val]
    if opts.get("force_firmware"):
        args.append("--force-firmware")
    return args


class Station:
    def __init__(self, board=None, ports=None, runner=None, popen=subprocess.Popen, run=subprocess.run,
                 log_dir=None):
        self.board = board or jobs.BOARD
        self._ports = ports
        self.runner = runner
        self.popen, self.run = popen, run
        self.log_dir = log_dir if log_dir is not None else os.getenv("STATION_LOG_DIR", "")
        self._probe_cache = {}

    def ports(self):
        return self._ports if self._ports is not None else load_ports()

    def _prefix(self, port):
        return (self.runner or runner_prefix()) + [str(int(port))]

    def _check_port(self, port):
        if int(port) not in {p["port"] for p in self.ports()}:
            raise StationError(f"Port {port} ist nicht eingerichtet")
        return int(port)

    # ------------------------------------------------------------ probe
    def probe(self, port, max_age=4):
        port = self._check_port(port)
        cached = self._probe_cache.get(port)
        if cached and time.time() - cached[0] < max_age:
            return cached[1]
        try:
            out = self.run(self._prefix(port) + ["probe"], capture_output=True, text=True, timeout=20)
            line = (out.stdout or "").strip().splitlines()[-1:] or ["{}"]
            info = json.loads(line[0])
            if not isinstance(info, dict):
                info = {"host": None}
            if out.returncode not in (0, 3):
                info = {"host": None, "error": (out.stderr or "").strip()[-200:]}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            info = {"host": None, "error": type(exc).__name__}
        self._probe_cache[port] = (time.time(), info)
        return info

    def overview(self):
        rows = []
        for p in self.ports():
            job = self.board.running_on_port(p["port"])
            last = next((j for j in self.board.all() if j.port == p["port"]), None)
            rows.append(dict(p, gateway=self.probe(p["port"]),
                             job=(job or last).as_dict() if (job or last) else None))
        return rows

    # ------------------------------------------------------------ setup
    def start_setup(self, port, mode="dry", opts=None):
        port = self._check_port(port)
        if self.board.running_on_port(port):
            raise StationError(f"Port {port}: es laeuft schon ein Vorgang")
        args = build_args(mode, opts)
        gw = self.probe(port, max_age=0)
        if not gw.get("host"):
            raise StationError(f"Port {port}: kein Gateway erkannt")
        args += ["--host", gw["host"]]
        label = {"check": "Pruefen", "dry": "Dry-Run", "apply": "Einrichten"}[mode]
        job = self.board.start("setup", gw.get("eui") or f"port {port}", f"{label} Port {port}", port=port)
        job.gateway = {"eui": gw.get("eui"), "host": gw["host"]}
        job.log("$ gatewaychef " + " ".join(shlex.quote(a) for a in args))
        thread = threading.Thread(target=self._run_job, args=(job, self._prefix(port) + args), daemon=True)
        thread.start()
        return job

    def _run_job(self, job, cmd):
        logfile = None
        try:
            if self.log_dir:
                os.makedirs(self.log_dir, exist_ok=True)
                name = f"{time.strftime('%Y%m%d-%H%M%S')}-p{job.port}-{job.gateway.get('eui') or 'unbekannt'}.log"
                logfile = open(os.path.join(self.log_dir, name), "w", encoding="utf-8")
            proc = self.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc.stdout:
                if logfile:
                    logfile.write(line)
                    logfile.flush()
                if line.startswith("@@RESULT "):
                    try:
                        job.result = json.loads(line[len("@@RESULT "):])
                        job.gateway.update({k: job.result.get(k) for k in ("eui", "vpn_ip", "name", "serial")})
                    except ValueError:
                        pass
                    continue
                job.log(line)
            code = proc.wait()
        except OSError as exc:
            job.log(f"Start fehlgeschlagen: {exc}")
            job.finish(jobs.FAILED, str(exc))
            return
        finally:
            if logfile:
                logfile.close()
        state = {0: jobs.OK, 1: jobs.DIFF}.get(code, jobs.FAILED)
        failed = [s["step"] for s in (job.result or {}).get("steps", []) if s["status"] == "fail"]
        job.finish(state, ("offen: " + ", ".join(failed)) if failed else f"Exit {code}")
