import json
import requests
from flask import Blueprint, request
from utils.response import ok, error

bp = Blueprint('webservice', __name__)

WEBSERVICE_BASE_URL = 'https://webservice.ball-b.de'


def _auth_from_payload(payload):
    username = (payload or {}).get('username') or ''
    password = (payload or {}).get('password') or ''
    if not username or not password:
        return None, error('Webservice Login fehlt (Benutzer/Passwort).', 401)
    return (username, password), None


@bp.route('/api/webservice/clientsearch', methods=['POST'])
def client_search():
    payload = request.get_json(silent=True) or {}
    auth, auth_error = _auth_from_payload(payload)
    if auth_error:
        return auth_error
    query = (payload.get('query') or '').strip()
    if len(query) < 3:
        return error('Bitte mindestens 3 Zeichen eingeben.', 400)
    url = f"{WEBSERVICE_BASE_URL}/api/v2/clientsearch"
    try:
        resp = requests.get(url, params={'query': query}, auth=auth, timeout=8)
    except requests.RequestException as exc:
        print(f"[webservice/clientsearch] request_error={exc}", flush=True)
        return error('Webservice Anfrage fehlgeschlagen.', 502)
    if resp.status_code >= 400:
        print(f"[webservice/clientsearch] status={resp.status_code} body={resp.text[:400]}", flush=True)
        return error('Webservice Zugriff fehlgeschlagen.', resp.status_code)
    return ok(resp.json())


@bp.route('/api/webservice/gateways', methods=['POST'])
def gateway_list():
    payload = request.get_json(silent=True) or {}
    auth, auth_error = _auth_from_payload(payload)
    if auth_error:
        return auth_error
    client_id = payload.get('clientId')
    if not client_id:
        return error('clientId fehlt.', 400)
    url = f"{WEBSERVICE_BASE_URL}/api/v2/gateway"
    try:
        resp = requests.get(url, params={'clientId': client_id}, auth=auth, timeout=8)
    except requests.RequestException as exc:
        print(f"[webservice/gateways] request_error={exc}", flush=True)
        return error('Webservice Anfrage fehlgeschlagen.', 502)
    if resp.status_code >= 400:
        print(f"[webservice/gateways] status={resp.status_code} body={resp.text[:400]}", flush=True)
        return error('Webservice Zugriff fehlgeschlagen.', resp.status_code)
    return ok(resp.json())


@bp.route('/api/webservice/search-by-eui', methods=['POST'])
def search_by_eui():
    payload = request.get_json(silent=True) or {}
    auth, auth_error = _auth_from_payload(payload)
    if auth_error:
        return auth_error
    eui = payload.get('eui')
    if not eui:
        return error('EUI fehlt.', 400)
    
    # User hint: "WHERE eui LIKE '12345%'"
    url = f"{WEBSERVICE_BASE_URL}/api/v2/gateway"
    try:
        resp = requests.get(url, params={'gatewayEui': eui}, auth=auth, timeout=8)
    except requests.RequestException as exc:
        print(f"[webservice/search-by-eui] request_error={exc}", flush=True)
        return error('Webservice Anfrage fehlgeschlagen.', 502)
    
    if resp.status_code >= 400:
        print(f"[webservice/search-by-eui] status={resp.status_code} body={resp.text[:400]}", flush=True)
        return error('Webservice Zugriff fehlgeschlagen.', resp.status_code)
    
    return ok(resp.json())


@bp.route('/api/webservice/create-gateway', methods=['POST'])
def create_gateway():
    payload = request.get_json(silent=True) or {}
    auth, auth_error = _auth_from_payload(payload)
    if auth_error:
        return auth_error

    # Required fields
    required = ['clientId', 'lns', 'name', 'gatewayId', 'gatewayEui', 'simIccid', 'simId', 'manufacturer', 'type', 'serialNumber']
    missing = [f for f in required if not payload.get(f)]
    if missing:
        return error(f"Fehlende Felder: {', '.join(missing)}", 400)

    # Proxy to Webservice
    url = f"{WEBSERVICE_BASE_URL}/api/v2/gateway"
    
    # Try to cast clientId to int, as some APIs are strict
    client_id_val = payload['clientId']
    try:
        client_id_val = int(client_id_val)
    except (ValueError, TypeError):
        pass

    # Prepare external payload
    data = {
        'clientId': client_id_val,
        'lns': payload['lns'],
        'lnsAddress': payload.get('lnsAddress'),
        'name': payload['name'],
        'serialNumber': payload['serialNumber'],
        # Backward / provider compatibility aliases.
        'serial': payload['serialNumber'],
        'serial_number': payload['serialNumber'],
        'gatewayId': payload['gatewayId'],
        'gatewayEui': payload['gatewayEui'],
        'simIccid': payload['simIccid'],
        'simId': payload['simId'],
        'manufacturer': payload['manufacturer'],
        'type': payload['type'],
        'nfc': payload.get('nfc'),
        'active': payload.get('active')
    }

    params = {'clientId': client_id_val}
    try:
        # Use data=data to send as application/x-www-form-urlencoded
        resp = requests.post(url, params=params, data=data, auth=auth, timeout=10)
    except requests.RequestException as exc:
        print(f"[webservice/create-gateway] request_error={exc}", flush=True)
        return error('Webservice Anfrage fehlgeschlagen.', 502)

    print(f"--- Webservice API POST Request ---", flush=True)
    print(f"URL: {resp.request.url}", flush=True)
    
    # Mask Authorization header for logging
    req_headers = dict(resp.request.headers)
    if 'Authorization' in req_headers:
        req_headers['Authorization'] = 'Basic ***'
    
    print(f"Headers: {req_headers}", flush=True)
    print(f"Body: {resp.request.body}", flush=True)
    print(f"----------------------------------", flush=True)

    print(f"--- Webservice API Response ---", flush=True)
    print(f"Status: {resp.status_code}", flush=True)
    print(f"Body: {resp.text}", flush=True)
    print(f"-------------------------------", flush=True)

    if resp.status_code >= 400:
        print(f"[webservice/create-gateway] status={resp.status_code} body={resp.text[:400]}", flush=True)
        # Try to pass through the specific error message from webservice if JSON
        try:
            err_body = resp.json()
            msg = err_body.get('message') or err_body.get('error') or 'Webservice Fehler'
            return error(msg, resp.status_code)
        except:
            return error('Webservice Zugriff fehlgeschlagen.', resp.status_code)
            
    return ok(resp.json())
