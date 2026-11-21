"""
In-memory board of running and finished jobs (setup per station port, fleet
updates). Shown on /station so you can see which gateway is being worked on,
where it stands, and which are done, and pick up by hand when one fails.

Kept in the web process only: a restart of the service clears the board, the
logs of setup runs stay on disk (STATION_LOG_DIR).
"""
import itertools
import threading
import time

RUNNING, OK, DIFF, FAILED = "running", "ok", "diff", "failed"
_MAX_DONE = 200


class Job:
    def __init__(self, job_id, kind, target, label, port=None):
        self.id, self.kind, self.target, self.label, self.port = job_id, kind, target, label, port
        self.state = RUNNING
        self.started = time.time()
        self.finished = None
        self.step = None            # last finished step, e.g. "[OK  ] Identitaet"
        self.lines = []
        self.result = None          # dict from @@RESULT or the fleet call
        self.detail = ""
        self.gateway = {}           # eui / vpn_ip / name once known

    def log(self, line):
        line = line.rstrip("\n")
        self.lines.append(line)
        if len(self.lines) > 2000:
            del self.lines[:500]
        if line.startswith("["):
            self.step = line[:120]

    def finish(self, state, detail="", result=None):
        self.state, self.detail, self.finished = state, detail, time.time()
        if result is not None:
            self.result = result

    def as_dict(self, with_log=False):
        d = {"id": self.id, "kind": self.kind, "target": self.target, "label": self.label, "port": self.port,
             "state": self.state, "started": self.started, "finished": self.finished, "step": self.step,
             "detail": self.detail, "gateway": self.gateway,
             "seconds": int((self.finished or time.time()) - self.started)}
        if with_log:
            d["log"] = self.lines[-400:]
            d["result"] = self.result
        return d


class Board:
    def __init__(self):
        self._jobs = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def start(self, kind, target, label, port=None):
        with self._lock:
            job = Job(next(self._ids), kind, target, label, port)
            self._jobs[job.id] = job
            done = [j for j in self._jobs.values() if j.state != RUNNING]
            for old in sorted(done, key=lambda j: j.finished or 0)[:-_MAX_DONE]:
                self._jobs.pop(old.id, None)
            return job

    def get(self, job_id):
        return self._jobs.get(int(job_id))

    def running_on_port(self, port):
        return next((j for j in self._jobs.values() if j.port == port and j.state == RUNNING), None)

    def running_for(self, target):
        return next((j for j in self._jobs.values() if j.target == target and j.state == RUNNING), None)

    def all(self):
        return sorted(self._jobs.values(), key=lambda j: (j.state != RUNNING, -(j.finished or j.started)))


BOARD = Board()


def tracked(kind, target, label, fn):
    """Run a synchronous fleet action as a job on the board; returns fn()'s result."""
    job = BOARD.start(kind, target, label)
    try:
        res = fn()
    except Exception as exc:  # noqa: BLE001 - shown on the board, then re-raised
        job.log(f"Fehler: {exc}")
        job.finish(FAILED, str(exc))
        raise
    result = (res or {}).get("result") if isinstance(res, dict) else None
    state = FAILED if result in ("failed", "offline", "error") else (DIFF if result == "would_change" else OK)
    job.log(str(res))
    job.finish(state, (res or {}).get("detail", "") if isinstance(res, dict) else "", res)
    return res
