import time
"""
Fleet management page and API (station / any instance inside the VPN).
Writes require apply=true in the body; without it everything is a dry run.
"""
import os

from flask import Blueprint, render_template, request, send_from_directory

from services import firmware as fw
from services import fleet as fl
from services import fleet_snapshots as snaps
from services import gw_reports
from services import gateway_config as gc
from services import jobs
from services import nodered as nr
from services import orders
from services import roles
from utils.response import error, ok

bp = Blueprint("fleet", __name__)
_LAST_STATUS = {"rows": None, "at": 0.0}  # last full status (any check), served instantly with ?cached=1
_LAST_DEEP = {}  # vpn_ip -> (fields, time) of the last successful deep check
# kept on disk too: the station restarts on every auto-update and would otherwise start empty (slow first load)
_CACHE_FILE = os.getenv("FLEET_CACHE_FILE") or os.path.join(os.path.expanduser("~"), ".cache", "gatewaychef", "fleet-status.json")


def _load_cache():
    import json
    try:
        with open(_CACHE_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        _LAST_STATUS.update(rows=d.get("rows"), at=float(d.get("at") or 0))
        _LAST_DEEP.update({k: tuple(v) for k, v in (d.get("deep") or {}).items()})
    except (OSError, ValueError, TypeError):
        pass


def _save_cache():
    import json
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"rows": _LAST_STATUS["rows"], "at": _LAST_STATUS["at"], "deep": _LAST_DEEP}, fh, default=str)
        os.replace(tmp, _CACHE_FILE)
    except OSError:
        pass


_load_cache()
_DEEP_KEYS = ("firmware", "profile_ok", "profile", "firmware_compat", "firmware_deltas", "wifi_country", "flow", "health")
_ERRORS = (fl.FleetError, gc.GatewayConfigError, nr.NodeRedError, fw.FirmwareError)


def _cloud_read():
    """Station/Mac without own database: read snapshots and gateway reports from the cloud app
    (DB_API_PROVIDER_URL + X-API-Token). Returns a Flask response or None (= answer locally)."""
    from config import APP_MODE, API_SERVICE_TOKEN, DATABASE_URL, DB_API_PROVIDER_URL, DB_HOST
    if APP_MODE != "local" or not DB_API_PROVIDER_URL or DB_HOST or DATABASE_URL:
        return None
    import requests
    from flask import Response
    try:
        up = requests.get(DB_API_PROVIDER_URL + request.path, params=request.args,
                          headers={"X-API-Token": API_SERVICE_TOKEN} if API_SERVICE_TOKEN else {}, timeout=20)
    except requests.RequestException as exc:
        return error(f"Cloud nicht erreichbar: {type(exc).__name__}", 502)
    return Response(up.content, status=up.status_code, content_type=up.headers.get("Content-Type", "application/json"))


def _fleet():
    return fl.from_env()


def _cloud():
    from config import APP_MODE
    return APP_MODE == "cloud"


@bp.route("/fleet")
def fleet_page():
    return render_template("fleet.html", cloud=_cloud())


@bp.route("/fleet/gw/<ip>")
def gateway_page(ip):
    return render_template("gateway.html", ip=ip, cloud=_cloud())


@bp.route("/api/fleet/jobs", methods=["GET"])
def fleet_jobs():
    """Recent remote actions (this process only), optionally for one VPN IP."""
    ip = request.args.get("ip")
    return ok([j.as_dict() for j in jobs.BOARD.all() if not ip or j.target == ip][:50])


@bp.route("/api/fleet/gateway/<ip>/stats", methods=["GET"])
def gateway_stats(ip):
    """ChirpStack last seen + packet counts (per hour or day) and the VPN peer of one gateway."""
    from services import gateway_stats as gs
    try:
        gw = _fleet()._gateway(ip)
    except _ERRORS as exc:
        return error(str(exc), 404)
    days = 7 if request.args.get("days") == "7" else 1
    return ok({"gateway": gw, "chirpstack": gs.chirpstack(gw.get("eui"), days), "vpn": gs.vpn_peer(ip)})


@bp.route("/api/fleet/status", methods=["GET"])
def fleet_status():
    deep = request.args.get("deep") in ("1", "true")
    only = [ip for ip in (request.args.get("ip") or "").split(",") if ip] or None
    if request.args.get("cached") in ("1", "true"):
        # instant answer from memory (the page then refreshes live); empty after an app restart
        return ok({"rows": _LAST_STATUS["rows"] or [], "age_s": int(time.time() - _LAST_STATUS["at"]) if _LAST_STATUS["rows"] else None})
    try:
        rows = _fleet().status(deep=deep, only=only)
    except Exception as exc:  # inventory unreachable etc.
        return error(f"Status fehlgeschlagen: {exc}", 502)
    # remember the last deep check (firmware, WLAN region, drive-by interface) and show it on quick checks
    now = time.time()
    for r in rows:
        if deep and r.get("online"):
            _LAST_DEEP[r["vpn_ip"]] = ({k: r[k] for k in _DEEP_KEYS if k in r}, now)
        elif not deep and r["vpn_ip"] in _LAST_DEEP:
            cached, at = _LAST_DEEP[r["vpn_ip"]]
            for k, v in cached.items():
                r.setdefault(k, v)
            r["deep_age"] = int(now - at)
    if not only:
        _LAST_STATUS.update(rows=rows, at=now)
        snaps.maybe_save(rows, deep)
    _save_cache()
    return ok(rows)


@bp.route("/fleet/history")
def fleet_history_page():
    return render_template("fleet_history.html", cloud=_cloud())


@bp.route("/api/fleet/snapshots", methods=["GET"])
def fleet_snapshots():
    proxied = _cloud_read()
    if proxied is not None:
        return proxied
    try:
        return ok(snaps.list_snapshots())
    except Exception as exc:
        return error(f"Flottenstände nicht lesbar: {exc}", 502)


@bp.route("/api/fleet/snapshots/<int:snap_id>", methods=["GET"])
def fleet_snapshot(snap_id):
    proxied = _cloud_read()
    if proxied is not None:
        return proxied
    try:
        snap = snaps.get_snapshot(snap_id)
    except Exception as exc:
        return error(f"Flottenstand nicht lesbar: {exc}", 502)
    return ok(snap) if snap else error("Flottenstand nicht gefunden", 404)


@bp.route("/api/fleet/catalog", methods=["GET"])
def fleet_catalog():
    patches = [{"name": n, "description": p.get("description", ""), "risky": fl.patch_is_risky(p),
                "admin_only": bool(fl.patch_is_risky(p) or fl.patch_touches_lns(p)),
                "firmware": p.get("firmware")} for n, p in fl.list_patches().items()]
    bundles = nr.load_bundles()
    return ok({"patches": patches, "flows": sorted(bundles), "latest_flow": nr.latest_version(bundles),
               "profiles": fl.known_firmwares(),
               "firmware_images": [{"version": v, "label": i["label"], "mb": i["size"] // 1_000_000}
                                   for v, i in sorted(fw.find_images().items())],
               "admin": roles.is_admin(), "orders": _cloud(),
               "firmware_upload_configured": bool(os.getenv("FIRMWARE_UPLOAD_TYPE") and os.getenv("FIRMWARE_UPLOAD_FILE"))})


@bp.route("/api/fleet/patch", methods=["POST"])
def fleet_patch():
    data = request.json or {}
    try:
        patch = fl.load_patch(str(data.get("name") or ""))
    except (OSError, ValueError):
        return error("Patch nicht gefunden.", 404)
    if bool(data.get("apply")) and (fl.patch_touches_lns(patch) or fl.patch_is_risky(patch)) and not roles.is_admin():
        return error("LNS- und Netzeinstellungen dürfen nur Admins ändern (Standard: driveby-udp-forward).", 403)
    try:
        ip, apply = data.get("vpn_ip"), bool(data.get("apply"))
        run = lambda: _fleet().patch(ip, patch, apply=apply, allow_risky=bool(data.get("allow_risky")))  # noqa: E731
        return ok(jobs.tracked("patch", ip, f"Patch {patch.get('name')}", run) if apply else run())
    except _ERRORS as exc:
        return error(str(exc), 400)


@bp.route("/api/fleet/nodered", methods=["POST"])
def fleet_nodered():
    data = request.json or {}
    try:
        ip, apply = data.get("vpn_ip"), bool(data.get("apply"))
        run = lambda: _fleet().nodered_update(ip, data.get("version"), apply=apply)  # noqa: E731
        return ok(jobs.tracked("nodered", ip, f"Node-RED {data.get('version') or 'neueste'}", run) if apply else run())
    except _ERRORS as exc:
        return error(str(exc), 400)


@bp.route("/api/fleet/firmware", methods=["POST"])
def fleet_firmware():
    data = request.json or {}
    try:
        ip, version, apply = data.get("vpn_ip"), str(data.get("version") or ""), bool(data.get("apply"))
        run = lambda: _fleet().firmware_upgrade(ip, version, apply=apply, force=bool(data.get("force")))  # noqa: E731
        return ok(jobs.tracked("firmware", ip, f"Firmware {version}", run) if apply else run())
    except _ERRORS as exc:
        return error(str(exc), 400)


@bp.route("/api/fleet/firmware/images", methods=["POST"])
def firmware_image_upload():
    """Store a firmware image (.bin, name with version) in FIRMWARE_DIR for remote upgrades."""
    f = request.files.get("file")
    if not f:
        return error("Datei fehlt.", 400)
    try:
        return ok(fw.store_image(f.stream, f.filename))
    except (fw.FirmwareError, OSError) as exc:
        return error(str(exc), 400)


@bp.route("/api/fleet/firmware/images/<version>", methods=["DELETE"])
def firmware_image_delete(version):
    try:
        fw.delete_image(version)
        return ok({"deleted": version})
    except (fw.FirmwareError, OSError) as exc:
        return error(str(exc), 404)


@bp.route("/api/fleet/compare", methods=["GET"])
def fleet_compare():
    """Soll-Ist against our standard for the given VPN IPs (comma separated)."""
    from concurrent.futures import ThreadPoolExecutor
    from services import fleet_align as fa
    ips = [ip for ip in (request.args.get("ip") or "").split(",") if ip]
    if not ips:
        return error("ip fehlt", 400)
    f = _fleet()

    def one(ip):
        try:
            return fa.public(fa.compare(f, f._gateway(ip)))
        except _ERRORS as exc:
            return {"vpn_ip": ip, "result": "error", "detail": str(exc)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return ok(list(pool.map(one, ips)))


@bp.route("/api/fleet/align", methods=["POST"])
def fleet_align():
    """Bring one gateway to the standard (dry run unless apply). Stability gate before any write."""
    from services import fleet_align as fa
    data = request.json or {}
    try:
        ip, apply = data.get("vpn_ip"), bool(data.get("apply"))
        admin = roles.is_admin()
        run = lambda: fa.align(_fleet(), ip, apply=apply, force=bool(data.get("force")) and admin, lns=admin)  # noqa: E731
        return ok(jobs.tracked("align", ip, "An Standard angleichen", run) if apply else run())
    except _ERRORS as exc:
        return error(str(exc), 400)


@bp.route("/api/gw/report", methods=["POST"])
def gw_report():
    """Push from the gateway flow (>= 1.4.0). Public path, checked with X-GW-Report-Token."""
    import hmac
    expected = os.getenv("GW_REPORT_TOKEN", "")
    got = request.headers.get("X-GW-Report-Token", "")
    if not expected or not got or not hmac.compare_digest(got, expected):
        return error("Token fehlt oder falsch", 401)
    body = request.get_json(silent=True)
    try:
        res = gw_reports.store(body)
    except gw_reports.ReportError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # DB down etc.
        return error(f"nicht gespeichert: {type(exc).__name__}", 503)
    samples = body.get("samples") if isinstance(body, dict) and isinstance(body.get("samples"), list) else [body]
    ip = next((x.get("vpn_ip") for x in samples if isinstance(x, dict) and x.get("vpn_ip")), None)
    orders.wake(ip)   # gateway is online right now: run its open orders
    return ok(res)


@bp.route("/api/fleet/orders", methods=["GET"])
def orders_list():
    if not _cloud():
        return ok([])
    try:
        return ok(orders.listing())
    except Exception as exc:
        return error(f"Aufträge nicht lesbar: {exc}", 502)


@bp.route("/api/fleet/orders", methods=["POST"])
def orders_create():
    """Body {ips: [...], action: align | flow | patch:<name>}: done as soon as each gateway is online."""
    if not _cloud():
        return error("Aufträge gibt es nur in der Cloud (dort läuft der Auftragsdienst).", 400)
    data = request.get_json(silent=True) or {}
    try:
        return ok(orders.create(data.get("ips") or [], str(data.get("action") or ""), roles.user_name(), roles.is_admin()))
    except orders.OrderError as exc:
        return error(str(exc), 400)


@bp.route("/api/fleet/orders/<int:order_id>", methods=["DELETE"])
def orders_cancel(order_id):
    try:
        return ok(orders.cancel(order_id))
    except orders.OrderError as exc:
        return error(str(exc), 409)


@bp.route("/api/fleet/gateway/<ip>/reports", methods=["GET"])
def gw_report_timeline(ip):
    proxied = _cloud_read()
    if proxied is not None:
        return proxied
    days = {"7": 7, "0.5h": 0.5 / 24, "2h": 2 / 24}.get(request.args.get("days"), 1)
    try:
        points = gw_reports.timeline(ip, days)
    except Exception as exc:
        return error(f"Meldungen nicht lesbar: {exc}", 502)
    return ok(dict(gw_reports.summarize_timeline(points, days), points=points, days=days))


@bp.route("/api/fleet/reports/last", methods=["GET"])
def gw_reports_last():
    proxied = _cloud_read()
    if proxied is not None:
        return proxied
    try:
        return ok(gw_reports.last_reports())
    except Exception as exc:
        return error(f"Meldungen nicht lesbar: {exc}", 502)


@bp.route("/api/fleet/rename", methods=["POST"])
def gw_rename():
    """Body {vpn_ip, name, apply}: plan (default) or write DB + ChirpStack; webservice is reported."""
    from services import rename
    body = request.get_json(silent=True) or {}
    try:
        r = rename.Renamer()
        out = r.apply(body.get("vpn_ip"), body.get("name")) if body.get("apply") is True else \
            r.plan(body.get("vpn_ip"), body.get("name"))
    except rename.RenameError as exc:
        return error(str(exc), 400)
    except Exception as exc:
        return error(f"Umbenennen fehlgeschlagen: {exc}", 502)
    return ok(out)


_IFACE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "interface")
_IFACE_FILES = {"driveby-health.schema.json": "application/schema+json", "DRIVEBY_INTERFACE.md": "text/markdown; charset=utf-8"}


@bp.route("/api/interface/", methods=["GET"])
@bp.route("/api/interface/<name>", methods=["GET"])
def interface_file(name=None):
    """Public, read-only: the gateway-flow interface contract (schema + description) for readers like the drive-by app."""
    if name is None:
        return ok({"files": sorted(_IFACE_FILES)})
    if name not in _IFACE_FILES:
        return error("unbekannt", 404)
    resp = send_from_directory(_IFACE_DIR, name, mimetype=_IFACE_FILES[name], max_age=300)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
