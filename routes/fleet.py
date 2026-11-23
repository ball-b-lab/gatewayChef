import time
"""
Fleet management page and API (station / any instance inside the VPN).
Writes require apply=true in the body; without it everything is a dry run.
"""
import os

from flask import Blueprint, render_template, request

from services import firmware as fw
from services import fleet as fl
from services import gateway_config as gc
from services import jobs
from services import nodered as nr
from utils.response import error, ok

bp = Blueprint("fleet", __name__)
_LAST_DEEP = {}  # vpn_ip -> (fields, time) of the last successful deep check (this process)
_DEEP_KEYS = ("firmware", "profile_ok", "profile", "firmware_compat", "firmware_deltas", "wifi_country", "flow", "health")
_ERRORS = (fl.FleetError, gc.GatewayConfigError, nr.NodeRedError, fw.FirmwareError)


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
    return ok(rows)


@bp.route("/api/fleet/catalog", methods=["GET"])
def fleet_catalog():
    patches = [{"name": n, "description": p.get("description", ""), "risky": fl.patch_is_risky(p),
                "firmware": p.get("firmware")} for n, p in fl.list_patches().items()]
    bundles = nr.load_bundles()
    return ok({"patches": patches, "flows": sorted(bundles), "latest_flow": nr.latest_version(bundles),
               "profiles": fl.known_firmwares(),
               "firmware_images": [{"version": v, "label": i["label"], "mb": i["size"] // 1_000_000}
                                   for v, i in sorted(fw.find_images().items())],
               "firmware_upload_configured": bool(os.getenv("FIRMWARE_UPLOAD_TYPE") and os.getenv("FIRMWARE_UPLOAD_FILE"))})


@bp.route("/api/fleet/patch", methods=["POST"])
def fleet_patch():
    data = request.json or {}
    try:
        patch = fl.load_patch(str(data.get("name") or ""))
    except (OSError, ValueError):
        return error("Patch nicht gefunden.", 404)
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
        run = lambda: fa.align(_fleet(), ip, apply=apply, force=bool(data.get("force")))  # noqa: E731
        return ok(jobs.tracked("align", ip, "An Standard angleichen", run) if apply else run())
    except _ERRORS as exc:
        return error(str(exc), 400)
