"""
Gateways push their state to the cloud (flow >= 1.4.0) instead of only being polled over the VPN.

The flow sends a report when Node-RED starts ("start") and then every few minutes ("beat") to
POST /api/gw/report (header X-GW-Report-Token = GW_REPORT_TOKEN). A gateway reboot is recognised by
its uptime: smaller than in the previous report, or a start report with uptime < BOOT_UPTIME_MAX.
Stored in gw_reports (app database, cloud only). No secrets are accepted or stored.
"""
import json
import time
from datetime import datetime, timedelta, timezone

from db.connection import get_db_connection

BOOT_UPTIME_MAX = 600          # s: a "start" this soon after boot is a reboot, later a Node-RED restart
ONLINE_GAP = 3 * 60            # s without report = offline (flow reports every minute)
KEEP_DAYS = 90
_FIELDS = ("eui", "vpn_ip", "flow_version", "uptime_s", "rx_total", "rx_ok", "crc_error_pct", "rxpk",
           "seconds_since_rxpk", "sensors", "tx_failed", "sf")
_DDL = """
CREATE TABLE IF NOT EXISTS gw_reports (
    id BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    eui TEXT,
    vpn_ip TEXT,
    kind TEXT NOT NULL,
    boot BOOLEAN NOT NULL DEFAULT false,
    uptime_s BIGINT,
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gw_reports_ip_time ON gw_reports(vpn_ip, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_gw_reports_eui_time ON gw_reports(eui, received_at DESC);
"""
_state = {"ready": False, "pruned": 0.0}


class ReportError(ValueError):
    pass


def clean(payload):
    """Validate and reduce a pushed report to known, harmless fields."""
    if not isinstance(payload, dict):
        raise ReportError("JSON-Objekt erwartet")
    kind = payload.get("kind")
    if kind not in ("start", "beat"):
        raise ReportError("kind muss start oder beat sein")
    data = {k: payload.get(k) for k in _FIELDS if payload.get(k) is not None}
    eui = str(data.get("eui") or "").upper()
    if eui and not (len(eui) == 16 and all(c in "0123456789ABCDEF" for c in eui)):
        raise ReportError("eui ungueltig")
    ip = str(data.get("vpn_ip") or "")
    if ip and not (ip.startswith("172.30.") and all(p.isdigit() for p in ip.split("."))):
        raise ReportError("vpn_ip ungueltig")
    if not (eui or ip):
        raise ReportError("eui oder vpn_ip fehlt")
    for k in ("uptime_s", "rx_total", "rx_ok", "rxpk", "seconds_since_rxpk", "sensors", "tx_failed"):
        if k in data:
            try:
                data[k] = int(float(data[k]))
            except (TypeError, ValueError):
                data.pop(k)
    if "sf" in data and not isinstance(data["sf"], dict):
        data.pop("sf")
    data["eui"], data["vpn_ip"] = eui or None, ip or None
    return kind, data


def _conn(connect=None):
    conn = (connect or get_db_connection)()
    if not _state["ready"]:
        with conn.cursor() as cur:
            cur.execute(_DDL)
        conn.commit()
        _state["ready"] = True
    return conn


def is_boot(kind, uptime, prev_uptime):
    if uptime is None:
        return False
    if prev_uptime is not None and uptime < prev_uptime:
        return True
    return kind == "start" and uptime < BOOT_UPTIME_MAX


def store(payload, connect=None, now=None):
    kind, data = clean(payload)
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            key, val = ("eui", data["eui"]) if data["eui"] else ("vpn_ip", data["vpn_ip"])
            cur.execute(f"SELECT uptime_s FROM gw_reports WHERE {key} = %s ORDER BY received_at DESC LIMIT 1", (val,))
            prev = cur.fetchone()
            boot = is_boot(kind, data.get("uptime_s"), prev[0] if prev else None)
            cur.execute("INSERT INTO gw_reports (eui, vpn_ip, kind, boot, uptime_s, data) VALUES (%s,%s,%s,%s,%s,%s)",
                        (data["eui"], data["vpn_ip"], kind, boot, data.get("uptime_s"), json.dumps(data)))
            now = now or time.time()
            if now - _state["pruned"] > 6 * 3600:
                cur.execute("DELETE FROM gw_reports WHERE received_at < now() - %s::interval", (f"{KEEP_DAYS} days",))
                _state["pruned"] = now
        conn.commit()
        return {"kind": kind, "boot": boot}
    finally:
        conn.close()


def timeline(vpn_ip, days=7, connect=None):
    """Reports of one gateway for the chart: [{t, kind, boot, uptime_s, rxpk, crc_error_pct, sensors}]."""
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT received_at, kind, boot, uptime_s, data FROM gw_reports "
                        "WHERE vpn_ip = %s AND received_at > now() - %s::interval ORDER BY received_at",
                        (vpn_ip, f"{int(days)} days"))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"t": t.isoformat(), "kind": k, "boot": b, "uptime_s": u,
             "rx": (d or {}).get("rx_total"), "crc_error_pct": (d or {}).get("crc_error_pct"),
             "sensors": (d or {}).get("sensors"), "flow_version": (d or {}).get("flow_version")}
            for t, k, b, u, d in rows]


def summarize_timeline(points, days=7, now=None):
    """Online intervals (gap > ONLINE_GAP = offline) and boots, for the page."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    times = [datetime.fromisoformat(p["t"]) for p in points]
    online, cur = [], None
    for t in times:
        if cur and (t - cur[1]).total_seconds() <= ONLINE_GAP:
            cur[1] = t
        else:
            if cur:
                online.append(cur)
            cur = [t, t]
    if cur:
        online.append(cur)
    up = sum((min(b + timedelta(seconds=ONLINE_GAP / 2), now) - a).total_seconds() for a, b in online)
    return {
        "online": [[a.isoformat(), min(b + timedelta(seconds=ONLINE_GAP / 2), now).isoformat()] for a, b in online],
        "boots": [p["t"] for p in points if p["boot"]],
        "last_report": points[-1]["t"] if points else None,
        "online_pct": round(min(100.0, up / (now - start).total_seconds() * 100), 1) if points else None,
    }


def last_reports(connect=None):
    """{vpn_ip: {"t", "uptime_s", "flow_version"}} newest report per gateway (for the fleet list)."""
    conn = _conn(connect)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ON (vpn_ip) vpn_ip, received_at, uptime_s, data FROM gw_reports "
                        "WHERE vpn_ip IS NOT NULL ORDER BY vpn_ip, received_at DESC")
            return {ip: {"t": t.isoformat(), "uptime_s": u, "flow_version": (d or {}).get("flow_version")}
                    for ip, t, u, d in cur.fetchall()}
    finally:
        conn.close()
