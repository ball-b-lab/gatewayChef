import requests
from flask import Blueprint, request
from config import CHIRPSTACK_URL, CHIRPSTACK_API_TOKEN, CHIRPSTACK_TENANT_ID, CHIRPSTACK_STATS_INTERVAL_SECS
from services.chirpstack import get_chirpstack_missing
from utils.response import ok, error

bp = Blueprint('chirpstack', __name__)


def _build_gateway_payload(eui, serial, gateway_name):
    return {
        "gateway": {
            "gatewayId": eui,
            "name": gateway_name,
            "description": serial,
            "tenantId": CHIRPSTACK_TENANT_ID,
            "statsInterval": CHIRPSTACK_STATS_INTERVAL_SECS,
            "tags": {
                "serial_number": serial
            }
        }
    }


@bp.route('/api/chirpstack/command', methods=['POST'])
def chirpstack_command():
    """
    Returns ChirpStack create payload for dry-run (no terminal output).
    """
    data = request.json
    eui = data.get('eui')
    serial = data.get('serial_number')
    gateway_name = data.get('gateway_name')

    if not all([eui, serial, gateway_name]):
        return error("Fehlende Daten (EUI, Serial, Name).", 400)

    missing = get_chirpstack_missing()
    if missing:
        return error("ChirpStack Konfiguration unvollstaendig.", 400, code="missing_config", data={"missing": missing})

    url = f"{CHIRPSTACK_URL}/api/gateways"

    payload = _build_gateway_payload(eui, serial, gateway_name)

    return ok({"status": "success", "payload": payload, "url": url})


@bp.route('/api/chirpstack/create', methods=['POST'])
def chirpstack_create():
    """
    Creates a ChirpStack gateway using the REST API.
    """
    data = request.json or {}
    eui = data.get('eui')
    serial = data.get('serial_number')
    gateway_name = data.get('gateway_name')

    if not all([eui, serial, gateway_name]):
        return error("Fehlende Daten (EUI, Serial, Name).", 400)

    missing = get_chirpstack_missing()
    if missing:
        return error("ChirpStack Konfiguration unvollstaendig.", 400, code="missing_config", data={"missing": missing})

    url = f"{CHIRPSTACK_URL}/api/gateways"
    headers = {
        "Authorization": f"Bearer {CHIRPSTACK_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = _build_gateway_payload(eui, serial, gateway_name)

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=8)
    except requests.RequestException as e:
        return error(f"ChirpStack Request Fehler: {e}", 502)

    if resp.status_code not in (200, 201):
        return error(f"ChirpStack Error {resp.status_code}", resp.status_code)

    try:
        result = resp.json() if resp.content else {}
    except ValueError:
        result = {}

    return ok({"status": "success", "data": result})


@bp.route('/api/chirpstack/config', methods=['GET'])
def chirpstack_config():
    missing = get_chirpstack_missing()
    return ok({"ready": len(missing) == 0, "missing": missing})


@bp.route('/api/chirpstack/check', methods=['POST'])
def chirpstack_check():
    """
    Checks ChirpStack for a gateway by EUI.
    """
    data = request.json
    eui = data.get('eui')

    if not eui:
        return error("Fehlende EUI.", 400)

    missing = get_chirpstack_missing()
    if missing:
        return error("ChirpStack Konfiguration unvollstaendig.", 400, code="missing_config", data={"missing": missing})

    url = f"{CHIRPSTACK_URL}/api/gateways/{eui}"
    headers = {"Authorization": f"Bearer {CHIRPSTACK_API_TOKEN}"}

    try:
        resp = requests.get(url, headers=headers, timeout=5)
    except requests.RequestException as e:
        return error(f"ChirpStack Request Fehler: {e}", 502)

    if resp.status_code == 200:
        return ok({"status": "success", "exists": True})
    if resp.status_code == 404:
        return ok({"status": "success", "exists": False})

    return error(f"ChirpStack Error {resp.status_code}", resp.status_code)
