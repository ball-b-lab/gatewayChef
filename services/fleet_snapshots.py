"""
Dated snapshots of the fleet state ("Flottenstand"), kept in the app database.

Saved automatically after a full fleet check (all gateways): always after a deep check, after a
quick check at most every SNAPSHOT_MIN_GAP seconds. Only compact, non-secret fields are stored.
"""
import json
import time

from db.connection import get_db_connection

SNAPSHOT_MIN_GAP = 30 * 60
_DDL = """
CREATE TABLE IF NOT EXISTS fleet_snapshots (
    id BIGSERIAL PRIMARY KEY,
    taken_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deep BOOLEAN NOT NULL DEFAULT false,
    summary JSONB NOT NULL,
    rows JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fleet_snapshots_taken_at ON fleet_snapshots(taken_at DESC);
"""
_state = {"ready": False, "last": 0.0}


def compact(row):
    """One gateway, the fields worth comparing over time."""
    d = row.get("driveby") or {}
    rad = d.get("radio") or {}
    flow = row.get("flow") or {}
    h = row.get("health") or {}
    cell = h.get("cellular") or {}
    sy = h.get("system") or {}
    return {
        "vpn_ip": row.get("vpn_ip"),
        "name": row.get("gateway_name"),
        "eui": row.get("eui"),
        "db_status": row.get("status_overall"),
        "online": row.get("online"),
        "latency_ms": row.get("latency_ms"),
        "firmware": row.get("firmware"),
        "flow": flow.get("version") or d.get("flow_version"),
        "flow_current": flow.get("up_to_date"),
        "wifi_country": row.get("wifi_country"),
        "receiving": d.get("receiving") if d else None,
        "driveby_poll_s": d.get("app_seconds_since_poll"),
        "net_type": cell.get("net_type"),
        "signal_dbm": cell.get("rsrp_dbm") if cell.get("rsrp_dbm") is not None else cell.get("signal_dbm"),
        "uptime_s": sy.get("uptime_s"),
        "crc_error_pct": rad.get("crc_error_pct"),
        "sensors": len(d.get("devices") or []) if d.get("devices") is not None else None,
    }


def summarize(rows):
    on = [r for r in rows if r.get("online") is True]
    fws = {}
    for r in rows:
        if r.get("firmware"):
            fws[r["firmware"]] = fws.get(r["firmware"], 0) + 1
    flows = {}
    for r in rows:
        if r.get("flow"):
            flows[r["flow"]] = flows.get(r["flow"], 0) + 1
    return {
        "total": len(rows),
        "online": len(on),
        "offline": sum(1 for r in rows if r.get("online") is False),
        "receiving": sum(1 for r in rows if r.get("receiving")),
        "firmware": fws,
        "flow": flows,
        "lte": sum(1 for r in rows if r.get("net_type") and "LTE" in r["net_type"].upper()),
    }


def _conn(connect=None):
    conn = (connect or get_db_connection)()
    if not _state["ready"]:
        with conn.cursor() as cur:
            cur.execute(_DDL)
        conn.commit()
        _state["ready"] = True
    return conn


def maybe_save(rows, deep, connect=None, now=None):
    """Save if due; returns the new id or None. Never raises (a snapshot must not break the status)."""
    now = now or time.time()
    if not rows or (not deep and now - _state["last"] < SNAPSHOT_MIN_GAP):
        return None
    try:
        comp = [compact(r) for r in rows]
        conn = _conn(connect)
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO fleet_snapshots (deep, summary, rows) VALUES (%s, %s, %s) RETURNING id",
                            (bool(deep), json.dumps(summarize(comp)), json.dumps(comp)))
                new_id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        _state["last"] = now
        return new_id
    except Exception:
        return None


def list_snapshots(limit=200, connect=None):
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, taken_at, deep, summary FROM fleet_snapshots ORDER BY taken_at DESC LIMIT %s", (limit,))
            return [{"id": i, "taken_at": t.isoformat(), "deep": d, "summary": s} for i, t, d, s in cur.fetchall()]
    finally:
        conn.close()


def get_snapshot(snap_id, connect=None):
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, taken_at, deep, summary, rows FROM fleet_snapshots WHERE id = %s", (snap_id,))
            r = cur.fetchone()
            return None if not r else {"id": r[0], "taken_at": r[1].isoformat(), "deep": r[2], "summary": r[3], "rows": r[4]}
    finally:
        conn.close()
