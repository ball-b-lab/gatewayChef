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
_ERRORS = (fl.FleetError, gc.GatewayConfigError, nr.NodeRedError, fw.FirmwareError)


def _fleet():
    return fl.from_env()


@bp.route("/fleet")
def fleet_page():
    return render_template("fleet.html")


@bp.route("/api/fleet/status", methods=["GET"])
def fleet_status():
    deep = request.args.get("deep") in ("1", "true")
    only = [ip for ip in (request.args.get("ip") or "").split(",") if ip] or None
    try:
        return ok(_fleet().status(deep=deep, only=only))
    except Exception as exc:  # inventory unreachable etc.
        return error(f"Status fehlgeschlagen: {exc}", 502)


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
        run = lambda: _fleet().firmware_upgrade(ip, version, apply=apply)  # noqa: E731
        return ok(jobs.tracked("firmware", ip, f"Firmware {version}", run) if apply else run())
    except _ERRORS as exc:
        return error(str(exc), 400)
