"""
Orders for gateways: "do X as soon as the gateway is online" (cloud only, app database).

An order is one action for one gateway:
  align          bring to our standard (stability gate, flow -> parameters -> LNS, rollback)
  flow           newest Node-RED flow (drive-by interface)
  patch:<name>   one prepared setting, e.g. patch:wifi-country-de (only patches without risk)

A background worker (one thread per web process, claims rows with SKIP LOCKED) looks at
open orders every ORDER_INTERVAL seconds and right away when a gateway reports itself
(POST /api/gw/report). Offline or not stable yet -> stays open and is tried again later.
LNS changes only run if the order was created by an admin (allow_lns).
"""
import json
import os
import threading
import time

from db.connection import get_db_connection

INTERVAL = int(os.getenv("ORDER_INTERVAL", "120"))
OPEN, RUNNING, DONE, FAILED, CANCELLED = "open", "running", "done", "failed", "cancelled"
_DDL = """
CREATE TABLE IF NOT EXISTS fleet_orders (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    vpn_ip TEXT NOT NULL,
    action TEXT NOT NULL,
    allow_lns BOOLEAN NOT NULL DEFAULT false,
    state TEXT NOT NULL DEFAULT 'open',
    attempts INT NOT NULL DEFAULT 0,
    last_try TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    detail TEXT,
    result JSONB
);
CREATE INDEX IF NOT EXISTS idx_fleet_orders_state ON fleet_orders(state, vpn_ip);
"""
_state = {"ready": False, "started": False}
_wake = threading.Event()
_woken = set()
LABELS = {"align": "Auf Standard bringen", "flow": "Drive-by-Schnittstelle aktualisieren"}


class OrderError(ValueError):
    pass


def label(action):
    if action.startswith("patch:"):
        return "Einstellung " + action[6:]
    return LABELS.get(action, action)


def _conn(connect=None):
    conn = (connect or get_db_connection)()
    if not _state["ready"]:
        with conn.cursor() as cur:
            cur.execute(_DDL)
        conn.commit()
        _state["ready"] = True
    return conn


def check_action(action, admin=False):
    from services import fleet as fl
    if action in LABELS:
        return action
    if action.startswith("patch:"):
        try:
            patch = fl.load_patch(action[6:])
        except (OSError, ValueError):
            raise OrderError("Einstellung nicht gefunden")
        if (fl.patch_is_risky(patch) or fl.patch_touches_lns(patch)) and not admin:
            raise OrderError("Diese Einstellung dürfen nur Admins ändern")
        return action
    raise OrderError("unbekannte Aktion")


def create(ips, action, user=None, admin=False, connect=None):
    action = check_action(action, admin)
    ips = [ip for ip in dict.fromkeys(ips) if ip]
    if not ips:
        raise OrderError("keine Gateways markiert")
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            # same open action for the same gateway: keep the existing order
            cur.execute("SELECT vpn_ip FROM fleet_orders WHERE action = %s AND state IN ('open','running') AND vpn_ip = ANY(%s)",
                        (action, ips))
            have = {r[0] for r in cur.fetchall()}
            new = [ip for ip in ips if ip not in have]
            for ip in new:
                cur.execute("INSERT INTO fleet_orders (created_by, vpn_ip, action, allow_lns) VALUES (%s,%s,%s,%s)",
                            (user, ip, action, bool(admin)))
        conn.commit()
    finally:
        conn.close()
    _wake.set()
    return {"created": len(new), "already_open": len(have), "label": label(action)}


def listing(limit=300, connect=None):
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, created_at, created_by, vpn_ip, action, state, attempts, last_try, finished_at, detail "
                        "FROM fleet_orders WHERE state IN ('open','running') OR finished_at > now() - interval '14 days' "
                        "ORDER BY (state IN ('open','running')) DESC, COALESCE(finished_at, created_at) DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()
    iso = lambda t: t.isoformat() if t else None  # noqa: E731
    return [{"id": i, "created_at": iso(c), "created_by": b, "vpn_ip": ip, "action": a, "label": label(a), "state": s,
             "attempts": n, "last_try": iso(lt), "finished_at": iso(f), "detail": d}
            for i, c, b, ip, a, s, n, lt, f, d in rows]


def cancel(order_id, connect=None):
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE fleet_orders SET state='cancelled', finished_at=now(), detail='abgebrochen' "
                        "WHERE id=%s AND state='open'", (order_id,))
            n = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise OrderError("Auftrag läuft schon oder ist erledigt")
    return {"cancelled": order_id}


def wake(vpn_ip):
    """A gateway reported itself: try its open orders now."""
    if vpn_ip:
        _woken.add(vpn_ip)
        _wake.set()


# ------------------------------------------------------------ worker
def run_action(fleet, ip, action, allow_lns):
    """-> (state, detail, result). OPEN = try again later (offline, not stable)."""
    from services import fleet as fl
    from services import fleet_align as fa
    if action == "align":
        res = fa.align(fleet, ip, apply=True, lns=allow_lns)
        r = res.get("result")
        state = DONE if r in ("changed", "ok") or res.get("needs_admin") else OPEN if r in ("offline", "skipped") else FAILED
    elif action == "flow":
        res = fleet.nodered_update(ip, None, apply=True)
        r = res.get("result")
        state = DONE if r in ("updated", "ok") else OPEN if r == "offline" else FAILED
    else:
        res = fleet.patch(ip, fl.load_patch(action[6:]), apply=True, allow_risky=False)
        r = res.get("result")
        state = DONE if r in ("changed", "ok") else OPEN if r == "offline" else FAILED
    return state, str(res.get("detail") or r)[:500], res


def _due(conn, only=None):
    with conn.cursor() as cur:
        cur.execute("UPDATE fleet_orders SET state='open' WHERE state='running' AND last_try < now() - interval '1 hour'")
        if only:
            cur.execute("SELECT DISTINCT vpn_ip FROM fleet_orders WHERE state='open' AND vpn_ip = ANY(%s)", (list(only),))
        else:
            cur.execute("SELECT DISTINCT vpn_ip FROM fleet_orders WHERE state='open' AND "
                        "(last_try IS NULL OR last_try < now() - %s::interval)", (f"{INTERVAL - 5} seconds",))
        ips = [r[0] for r in cur.fetchall()]
    conn.commit()
    return ips


def _claim(conn, ip):
    with conn.cursor() as cur:
        cur.execute("UPDATE fleet_orders SET state='running', attempts=attempts+1, last_try=now() WHERE id = ("
                    "SELECT id FROM fleet_orders WHERE vpn_ip=%s AND state='open' ORDER BY id LIMIT 1 "
                    "FOR UPDATE SKIP LOCKED) RETURNING id, action, allow_lns", (ip,))
        row = cur.fetchone()
    conn.commit()
    return row


def _finish(conn, oid, state, detail, result=None):
    with conn.cursor() as cur:
        cur.execute("UPDATE fleet_orders SET state=%s, detail=%s, result=%s, finished_at=CASE WHEN %s IN ('done','failed') "
                    "THEN now() END WHERE id=%s",
                    (state, detail, json.dumps(result, default=str) if result is not None else None, state, oid))
    conn.commit()


def work_once(fleet, only=None, connect=None):
    """One pass over gateways with open orders. Returns how many orders were finished."""
    conn = _conn(connect)
    finished = 0
    try:
        for ip in _due(conn, only):
            try:
                gw = fleet._gateway(ip)
                online, why, _ = fleet.identity(gw)
            except Exception as exc:  # noqa: BLE001 - inventory problem: try later
                online, why = False, str(exc)
            if not online:
                with conn.cursor() as cur:
                    cur.execute("UPDATE fleet_orders SET last_try=now(), detail=%s WHERE vpn_ip=%s AND state='open'",
                                (f"wartet: nicht erreichbar ({why})"[:300], ip))
                conn.commit()
                continue
            while True:   # all open orders of this gateway, one after the other
                row = _claim(conn, ip)
                if not row:
                    break
                oid, action, allow_lns = row
                try:
                    state, detail, res = run_action(fleet, ip, action, allow_lns)
                except Exception as exc:  # noqa: BLE001 - one failing order must not stop the worker
                    state, detail, res = FAILED, f"{type(exc).__name__}: {exc}"[:500], None
                _finish(conn, oid, state, ("wartet: " + detail) if state == OPEN else detail,
                        {k: v for k, v in (res or {}).items() if k not in ("plan", "client")})
                finished += state in (DONE, FAILED)
                if state == OPEN:
                    break   # not stable now: rest of this gateway later
    finally:
        conn.close()
    return finished


def start_worker(fleet_factory):
    if _state["started"]:
        return
    _state["started"] = True

    def loop():
        time.sleep(20)
        while True:
            only = set(_woken) if _woken else None
            _woken.clear()
            _wake.clear()
            try:
                work_once(fleet_factory(), only)
            except Exception as exc:  # noqa: BLE001 - database down etc.: keep the thread alive
                print(f"orders: {type(exc).__name__}: {exc}", flush=True)
            _wake.wait(INTERVAL if not only else 1)
    threading.Thread(target=loop, name="fleet-orders", daemon=True).start()
