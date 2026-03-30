import json
import requests
from flask import Blueprint, request
from config import MILESIGHT_URL, MILESIGHT_CLIENT_ID
from services.milesight import get_milesight_missing, milesight_get_token, milesight_token_url
from utils.response import ok, error

bp = Blueprint('milesight', __name__)


def _matches_identifier(item, identifier_key, identifier_value):
    expected = (identifier_value or "").strip().upper()
    if not expected:
        return False
    candidates = []
    if identifier_key == "devEUI":
        candidates.extend([
            item.get("devEUI"),
        ])
    elif identifier_key == "snDevEUI":
        candidates.extend([
            item.get("snDevEUI"),
            item.get("sn"),
        ])
    else:
        candidates.extend([
            item.get(identifier_key),
        ])
    normalized_candidates = {str(value).strip().upper() for value in candidates if value}
    return expected in normalized_candidates


def _search_milesight_device(headers, identifier_key, identifier_value):
    url = f"{MILESIGHT_URL}/device/openapi/v1/devices/search"
    body = {
        "pageSize": 1,
        "pageNumber": 1,
        identifier_key: identifier_value
    }
    resp = requests.post(url, headers=headers, json=body, timeout=8)
    if resp.status_code != 200:
        return None, error(f"Milesight Error {resp.status_code}", resp.status_code)
    try:
        payload = resp.json()
    except ValueError:
        return None, error("Invalid JSON response from Milesight", 502)
    content = payload.get("data", {}).get("content", [])
    if isinstance(content, list) and content:
        for item in content:
            if _matches_identifier(item, identifier_key, identifier_value):
                return item, None
    return None, None


@bp.route('/api/milesight/config', methods=['GET'])
def milesight_config():
    missing = get_milesight_missing()
    return ok({"ready": len(missing) == 0, "missing": missing})


@bp.route('/api/milesight/check', methods=['POST'])
def milesight_check():
    """
    Checks Milesight Development Platform for a device by EUI and optional serial.
    """
    data = request.json or {}
    eui = (data.get('eui') or '').strip()
    requested_serial_number = (data.get('serial_number') or '').strip()

    if not eui and not requested_serial_number:
        return error("Fehlende EUI oder Serial.", 400)

    missing = get_milesight_missing()
    if missing:
        return error("Milesight Konfiguration unvollstaendig.", 400, code="missing_config", data={"missing": missing})

    try:
        token = milesight_get_token()
    except Exception as e:
        return error(f"Milesight Token Fehler: {e}", 502)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        item = None
        route_error = None
        search_candidates = []
        if eui:
            search_candidates.extend([
                ("snDevEUI", eui),
                ("devEUI", eui),
            ])
        if requested_serial_number:
            search_candidates.extend([
                ("snDevEUI", requested_serial_number),
                ("devEUI", requested_serial_number),
            ])
        for identifier_key, identifier_value in search_candidates:
            item, route_error = _search_milesight_device(headers, identifier_key, identifier_value)
            if route_error or item:
                break
    except requests.RequestException as e:
        return error(f"Milesight Request Fehler: {e}", 502)
    if route_error:
        return route_error

    exists = False
    serial_number = None
    device_name = None
    device_model = None
    device_details = {}
    if item:
        dev_eui = (item.get("devEUI") or "").upper()
        sn_dev_eui = (item.get("snDevEUI") or "").upper()
        candidate_values = {value.upper() for value in (eui, requested_serial_number) if value}
        exists = bool(candidate_values.intersection({dev_eui, sn_dev_eui}))
        if exists:
            serial_number = item.get("sn") or item.get("serial_number")
            device_name = item.get("name")
            device_model = item.get("model")
            device_details = {
                "serial_number": serial_number,
                "name": device_name,
                "model": device_model,
                "firmware_version": item.get("firmwareVersion"),
                "hardware_version": item.get("hardwareVersion"),
                "imei": item.get("imei"),
                "connect_status": item.get("connectStatus"),
                "mac": item.get("mac"),
                "device_id": item.get("deviceId")
            }

    return ok({
        "status": "success",
        "exists": exists,
        "serial_number": serial_number,
        "name": device_name,
        "model": device_model,
        "details": device_details
    })


@bp.route('/api/milesight/command', methods=['POST'])
def milesight_command():
    """
    Prints a Milesight create device command to the terminal (test only).
    """
    data = request.json
    eui = data.get('eui')
    gateway_name = data.get('gateway_name')

    if not all([eui, gateway_name]):
        return error("Fehlende Daten (EUI, Name).", 400)

    missing = get_milesight_missing()
    if missing:
        return error("Milesight Konfiguration unvollstaendig.", 400, code="missing_config", data={"missing": missing})

    token_url = milesight_token_url()
    create_url = f"{MILESIGHT_URL}/device/openapi/v1/devices"

    token_cmd = (
        "curl -X POST \\\n"
        f"  '{token_url}' \\\n"
        "  -H 'Content-Type: application/x-www-form-urlencoded' \\\n"
        f"  -d 'grant_type=client_credentials&client_id={MILESIGHT_CLIENT_ID}&client_secret=<MILESIGHT_CLIENT_SECRET>'"
    )

    create_payload = {
        "snDevEUI": eui,
        "name": gateway_name
    }

    create_cmd = (
        "curl -X POST \\\n"
        f"  '{create_url}' \\\n"
        "  -H 'Authorization: Bearer <MILESIGHT_ACCESS_TOKEN>' \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        f"  -d '{json.dumps(create_payload)}'"
    )

    print("\n--- Milesight Token (TEST COMMAND) ---")
    print(token_cmd)
    print("--- END COMMAND ---\n")
    print("--- Milesight Create Device (TEST COMMAND) ---")
    print(create_cmd)
    print("--- END COMMAND ---\n")

    return ok({"status": "success", "message": "Milesight commands printed to terminal."})


@bp.route('/api/milesight/dry-run', methods=['POST'])
def milesight_dry_run():
    """
    Performs a dry-run: validates token and checks existence, but does not create.
    """
    data = request.json
    eui = data.get('eui')
    gateway_name = data.get('gateway_name')

    if not all([eui, gateway_name]):
        return error("Fehlende Daten (EUI, Name).", 400)

    missing = get_milesight_missing()
    if missing:
        return error("Milesight Konfiguration unvollstaendig.", 400, code="missing_config", data={"missing": missing})

    try:
        token = milesight_get_token()
    except Exception as e:
        return error(f"Milesight Token Fehler: {e}", 502)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        item, route_error = _search_milesight_device(headers, "snDevEUI", eui)
        if not item:
            item, route_error = _search_milesight_device(headers, "devEUI", eui)
    except requests.RequestException as e:
        return error(f"Milesight Request Fehler: {e}", 502)
    if route_error:
        return route_error

    exists = False
    if item:
        dev_eui = (item.get("devEUI") or "").upper()
        sn_dev_eui = (item.get("snDevEUI") or "").upper()
        exists = eui.upper() in (dev_eui, sn_dev_eui)

    create_payload = {
        "snDevEUI": eui,
        "name": gateway_name
    }

    return ok({
        "status": "success",
        "exists": exists,
        "would_create": not exists,
        "create_payload": create_payload
    })


@bp.route('/api/milesight/create', methods=['POST'])
def milesight_create():
    """
    Create a device via Milesight Development Platform.
    """
    data = request.json or {}
    eui = data.get('eui')
    serial_number = data.get('serial_number')
    gateway_name = data.get('gateway_name')

    if not gateway_name:
        return error("Fehlender Gateway Name.", 400)
    if not (serial_number or eui):
        return error("Fehlende Serial oder EUI.", 400)

    missing = get_milesight_missing()
    if missing:
        return error("Milesight Konfiguration unvollstaendig.", 400, code="missing_config", data={"missing": missing})

    try:
        token = milesight_get_token()
    except Exception as e:
        return error(f"Milesight Token Fehler: {e}", 502)

    create_url = f"{MILESIGHT_URL}/device/openapi/v1/devices"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "snDevEUI": serial_number or eui,
        "name": gateway_name
    }

    try:
        resp = requests.post(create_url, headers=headers, json=payload, timeout=8)
    except requests.RequestException as e:
        return error(f"Milesight Request Fehler: {e}", 502)

    if resp.status_code != 200:
        return error(f"Milesight Error {resp.status_code}", resp.status_code)

    try:
        result = resp.json()
    except ValueError:
        return error("Invalid JSON response from Milesight", 502)

    data = result.get("data", {}) if isinstance(result, dict) else {}
    return ok({
        "status": "success",
        "data": data,
        "request_id": result.get("requestId") if isinstance(result, dict) else None
    })
