from flask import Blueprint, current_app, render_template, request

from gatewaychef_v2.config import current_env_status, missing_for_stage
from gatewaychef_v2.connectors import (
    ChirpStackConnector,
    GatewayConnector,
    InventoryConnector,
    MilesightConnector,
    NetworkConnector,
    WebserviceConnector,
)
from gatewaychef_v2.errors import GatewayChefV2Error
from gatewaychef_v2.repository import JsonProvisioningRepository
from gatewaychef_v2.response import fail, ok
from gatewaychef_v2.services import ProvisioningOrchestrator

bp = Blueprint(
    "gatewaychef_v2",
    __name__,
    url_prefix="/gatewaychef-v2",
    template_folder="templates",
    static_folder="static",
)


def _runtime():
    overrides = current_app.config.get("GATEWAYCHEF_V2_RUNTIME", {})
    repository = overrides.get("repository") or JsonProvisioningRepository()
    return ProvisioningOrchestrator(
        repository,
        gateway=overrides.get("gateway") or GatewayConnector(),
        inventory=overrides.get("inventory") or InventoryConnector(),
        chirpstack=overrides.get("chirpstack") or ChirpStackConnector(),
        milesight=overrides.get("milesight") or MilesightConnector(),
        webservice=overrides.get("webservice") or WebserviceConnector(),
        network=overrides.get("network") or NetworkConnector(),
        enforce_env_guards=overrides.get("enforce_env_guards", True),
    )


def _trace_id():
    incoming = (request.headers.get("X-Provisioning-Trace") or "").strip()
    if incoming:
        return incoming
    if request.view_args:
        return request.view_args.get("run_id")
    return None


def _webservice_credentials():
    payload = request.json or {}
    return {
        "username": (payload.get("webservice_username") or "").strip(),
        "password": payload.get("webservice_password") or "",
    }


@bp.route("/", methods=["GET"])
def index():
    return render_template("gatewaychef_v2/index.html")


@bp.route("/api/runtime", methods=["GET"])
def runtime_status():
    inventory = current_app.config.get("GATEWAYCHEF_V2_RUNTIME", {}).get("inventory") or InventoryConnector()
    gateway = current_app.config.get("GATEWAYCHEF_V2_RUNTIME", {}).get("gateway") or GatewayConnector()
    chirpstack = current_app.config.get("GATEWAYCHEF_V2_RUNTIME", {}).get("chirpstack") or ChirpStackConnector()
    milesight = current_app.config.get("GATEWAYCHEF_V2_RUNTIME", {}).get("milesight") or MilesightConnector()
    try:
        sim_vendors = inventory.list_sim_vendors()
    except Exception as exc:
        sim_vendors = []
        inventory_missing = [{"group": "inventory_runtime", "missing": [str(exc)]}]
    else:
        inventory_missing = missing_for_stage("inventory")
    data = {
        "env_status": current_env_status(),
        "missing_cloud_sync": missing_for_stage("cloud_sync"),
        "missing_inventory": inventory_missing,
        "sim_vendors": sim_vendors,
        "connections": [
            gateway.connection_status(),
            inventory.connection_status(),
            chirpstack.connection_status(),
            milesight.connection_status(),
        ],
    }
    return ok(data)


@bp.route("/api/connections", methods=["POST"])
def connection_status():
    overrides = current_app.config.get("GATEWAYCHEF_V2_RUNTIME", {})
    gateway = overrides.get("gateway") or GatewayConnector()
    inventory = overrides.get("inventory") or InventoryConnector()
    chirpstack = overrides.get("chirpstack") or ChirpStackConnector()
    milesight = overrides.get("milesight") or MilesightConnector()
    webservice = overrides.get("webservice") or WebserviceConnector()
    data = {
        "connections": [
            gateway.connection_status(),
            inventory.connection_status(),
            chirpstack.connection_status(),
            milesight.connection_status(),
            webservice.connection_status(_webservice_credentials()),
        ]
    }
    return ok(data)


@bp.route("/api/discovery", methods=["GET"])
def discovery():
    runtime = _runtime()
    try:
        return ok(runtime.discover_gateway())
    except Exception as exc:
        error = GatewayChefV2Error(
            f"Gateway Discovery fehlgeschlagen: {exc}",
            code="discovery_failed",
            status_code=502,
            stage="discovery",
            retryable=True,
        )
        return fail(error)


@bp.route("/api/runs", methods=["POST"])
def create_run():
    runtime = _runtime()
    try:
        data = request.json or {}
        data["requested_by"] = request.headers.get("X-Operator-Id") or data.get("operator_name")
        run = runtime.create_run(data)
        return ok(run, trace_id=run["run_id"], status=201)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=_trace_id())


@bp.route("/api/runs/<run_id>", methods=["GET"])
def get_run(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.get_run(run_id), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/precheck", methods=["POST"])
def run_precheck(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.precheck(run_id), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/reserve", methods=["POST"])
def reserve_inventory(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.reserve(run_id), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/confirm-config", methods=["POST"])
def confirm_config(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.confirm_config_applied(run_id, request.json or {}), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/cloud-sync", methods=["POST"])
def cloud_sync(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.sync_cloud(run_id, webservice_credentials=_webservice_credentials()), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/verify", methods=["POST"])
def verify(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.verify(run_id, webservice_credentials=_webservice_credentials()), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/finalize", methods=["POST"])
def finalize(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.finalize(run_id), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/report", methods=["GET"])
def report(run_id):
    runtime = _runtime()
    try:
        run = runtime.get_run(run_id)
        data = {
            "run_id": run["run_id"],
            "state": run["state"],
            "release_gate": run.get("report", {}).get("release_gate", "BLOCK"),
            "report": run.get("report", {}),
            "events": run.get("events", []),
        }
        return ok(data, trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)


@bp.route("/api/runs/<run_id>/secret-bundle", methods=["POST"])
def secret_bundle(run_id):
    runtime = _runtime()
    try:
        return ok(runtime.reveal_secret_bundle(run_id, request.json or {}), trace_id=run_id)
    except GatewayChefV2Error as exc:
        return fail(exc, trace_id=run_id)
