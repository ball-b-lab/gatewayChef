import json

import requests

from config import (
    API_SERVICE_TOKEN,
    CHIRPSTACK_API_TOKEN,
    CHIRPSTACK_STATS_INTERVAL_SECS,
    CHIRPSTACK_TENANT_ID,
    CHIRPSTACK_URL,
    DB_API_PROVIDER_URL,
    DB_API_TIMEOUT_SECS,
    MILESIGHT_CLIENT_ID,
    MILESIGHT_URL,
    VPN_PING_PROVIDER_URL,
    VPN_PING_SERVICE_TOKEN,
)
from db.connection import get_db_connection
from gatewaychef_v2.errors import ExternalServiceError
from routes.webservice import WEBSERVICE_BASE_URL
from routes.network import _run_local_ping
from services.milesight import milesight_get_token
from utils.helpers import derive_wifi_ssid, normalize_vpn_ip


def _trim_text(value, limit=400):
    text = (value or "").strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _parse_error_body(resp):
    try:
        payload = resp.json()
    except ValueError:
        return _trim_text(resp.text)
    if isinstance(payload, dict):
        message = payload.get("message")
        if not message and isinstance(payload.get("error"), dict):
            message = payload["error"].get("message")
        if not message and payload.get("error"):
            message = str(payload.get("error"))
        return _trim_text(message or json.dumps(payload, ensure_ascii=True))
    return _trim_text(str(payload))


def _normalize_list_payload(payload):
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "clients", "gateways", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize_webservice_lns(value):
    if value is None:
        return 2
    text = str(value).strip()
    if not text:
        return 2
    if text.isdigit():
        return int(text)
    lowered = text.lower()
    mapping = {
        "chirpstack": 2,
        "chirp": 2,
        "2": 2,
    }
    return mapping.get(lowered, text)


def _normalize_eui(value):
    return "".join(ch for ch in str(value or "") if ch in "0123456789abcdefABCDEF").upper()


def _normalize_client_id(value):
    text = str(value or "").strip()
    if text.isdigit():
        return str(int(text))
    return text


def _request_json(method, url, *, service, timeout=8, **kwargs):
    try:
        resp = requests.request(method=method, url=url, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise ExternalServiceError(
            service,
            f"{service} Anfrage fehlgeschlagen: {exc}",
            code="request_failed",
            details={"url": url},
        ) from exc
    if resp.status_code >= 400:
        raise ExternalServiceError(
            service,
            f"{service} Fehler {resp.status_code}: {_parse_error_body(resp)}",
            code="http_error",
            status_code=502,
            details={"url": url, "http_status": resp.status_code, "response_body": _parse_error_body(resp)},
        )
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        raise ExternalServiceError(
            service,
            f"{service} lieferte ungueltiges JSON.",
            code="invalid_json",
            details={"url": url, "response_body": _trim_text(resp.text)},
        ) from exc


class GatewayConnector:
    def __init__(self, base_url="http://192.168.1.1"):
        self.base_url = base_url.rstrip("/")

    def fetch_device_info(self):
        return _request_json("GET", f"{self.base_url}/node-red/device-info", service="gateway", timeout=5)

    def fetch_lora_info(self):
        return _request_json("GET", f"{self.base_url}/node-red/device-info-lora", service="gateway", timeout=5)

    def fetch_lora_health(self):
        return _request_json("GET", f"{self.base_url}/node-red/lora/health", service="gateway", timeout=5)

    def connection_status(self):
        try:
            payload = self.fetch_lora_health()
            return {
                "ok": True,
                "service": "gateway",
                "message": f"Gateway erreichbar, LoRa {payload.get('status') or '-'}",
                "details": {"lns_connected": bool(payload.get("lns_connected"))},
            }
        except ExternalServiceError as exc:
            return {"ok": False, "service": "gateway", "message": exc.message, "details": exc.details}


class NetworkConnector:
    def ping(self, vpn_ip):
        host = normalize_vpn_ip(vpn_ip)
        if not host:
            return {"ok": False, "output": "VPN IP fehlt."}
        if VPN_PING_PROVIDER_URL:
            headers = {"Content-Type": "application/json"}
            if VPN_PING_SERVICE_TOKEN:
                headers["X-Ping-Service-Token"] = VPN_PING_SERVICE_TOKEN
            payload = _request_json(
                "POST",
                f"{VPN_PING_PROVIDER_URL.rstrip('/')}/api/network/gateway-health",
                service="gateway_health",
                headers=headers,
                json={"host": host},
                timeout=5,
            )
            return {
                "ok": bool(payload.get("ok")),
                "output": (payload.get("payload") or {}).get("status") or "ok",
                "via": "cloud_http_health",
                "payload": payload.get("payload"),
                "url": payload.get("url"),
            }
        return _run_local_ping(host)


class InventoryConnector:
    def __init__(self, provider_url=None, api_token=None, timeout=None):
        self.provider_url = (provider_url or DB_API_PROVIDER_URL or "").rstrip("/")
        self.api_token = api_token if api_token is not None else API_SERVICE_TOKEN
        self.timeout = timeout or DB_API_TIMEOUT_SECS

    def _request(self, method, path, *, json_body=None):
        if not self.provider_url:
            return None
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["X-API-Token"] = self.api_token
        payload = _request_json(
            method,
            f"{self.provider_url}{path}",
            service="cloud_api",
            headers=headers,
            json=json_body,
            timeout=self.timeout,
        )
        if payload.get("ok") is not True:
            raise ExternalServiceError(
                "cloud_api",
                payload.get("error", {}).get("message") or "Cloud DB API Fehler",
                code=payload.get("error", {}).get("code") or "api_error",
                details={"response_body": payload},
            )
        return payload.get("data")

    def connection_status(self):
        try:
            vendors = self.list_sim_vendors()
            return {
                "ok": True,
                "service": "cloud_api",
                "message": f"Cloud API erreichbar, {len(vendors)} SIM-Vendoren geladen",
                "details": {},
            }
        except ExternalServiceError as exc:
            return {"ok": False, "service": "cloud_api", "message": exc.message, "details": exc.details}

    def list_sim_vendors(self):
        data = self._request("GET", "/api/sim/vendors")
        if data is not None:
            return data.get("vendors", [])
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, vendor_name, apn
                    FROM sim_vendors
                    ORDER BY vendor_name
                    """
                )
                return [{"id": row[0], "name": row[1], "apn": row[2]} for row in cur.fetchall()]
        finally:
            conn.close()

    def peek_next_free_ip(self):
        data = self._request("GET", "/api/db/fetch-ip")
        if data is not None:
            return data
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT vpn_ip, private_key
                    FROM gateway_inventory
                    WHERE status_overall = 'FREE'
                    ORDER BY vpn_ip
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                return {"vpn_ip": row[0], "private_key": row[1]} if row else None
        finally:
            conn.close()

    def reserve_inventory(self, *, gateway_name, serial_number, sim_vendor_id, sim_iccid):
        if self.provider_url:
            ip_record = self._request("GET", "/api/db/fetch-ip")
            update_result = self._request(
                "POST",
                "/api/db/customer-update",
                json_body={
                    "vpn_ip": ip_record["vpn_ip"],
                    "gateway_name": gateway_name,
                    "serial_number": serial_number,
                    "sim_vendor_id": sim_vendor_id,
                    "sim_iccid": sim_iccid,
                },
            )
            vendor = self.find_sim_vendor(sim_vendor_id)
            return {
                "vpn_ip": ip_record["vpn_ip"],
                "private_key": ip_record.get("private_key"),
                "apn": vendor.get("apn") if vendor else None,
                "wifi_ssid": derive_wifi_ssid(ip_record["vpn_ip"]),
                "sim_id": update_result.get("sim_id"),
                "sim_card_id": update_result.get("sim_card_id"),
            }
        from services.provisioning_service import ProvisioningService

        conn = get_db_connection()
        try:
            service = ProvisioningService(conn)
            ip_record = service.fetch_next_free_ip()
            update_result = service.update_customer_data(
                vpn_ip=ip_record["vpn_ip"],
                gateway_name=gateway_name,
                serial_number=serial_number,
                sim_vendor_id=sim_vendor_id,
                sim_iccid=sim_iccid,
            )
            vendor = self.find_sim_vendor(sim_vendor_id)
            return {
                "vpn_ip": ip_record["vpn_ip"],
                "private_key": ip_record["private_key"],
                "apn": vendor.get("apn") if vendor else None,
                "wifi_ssid": derive_wifi_ssid(ip_record["vpn_ip"]),
                "sim_id": update_result.get("sim_id"),
                "sim_card_id": update_result.get("sim_card_id"),
            }
        finally:
            conn.close()

    def fetch_vpn_key(self, vpn_ip):
        data = self._request("POST", "/api/db/vpn-key", json_body={"vpn_ip": vpn_ip})
        if data is not None:
            return data
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT private_key, serial_number
                    FROM gateway_inventory
                    WHERE vpn_ip = %s
                    """,
                    (vpn_ip,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {"private_key": row[0], "serial_number": row[1]}
        finally:
            conn.close()

    def find_sim_vendor(self, vendor_id):
        for vendor in self.list_sim_vendors():
            if str(vendor["id"]) == str(vendor_id):
                return vendor
        return None

    def fetch_gateway_record(self, *, vpn_ip=None, eui=None, serial_number=None):
        data = self._request(
            "POST",
            "/api/db/gateway",
            json_body={"vpn_ip": vpn_ip, "eui": eui, "serial_number": serial_number},
        )
        if data is not None:
            return data
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                if vpn_ip:
                    cur.execute(
                        """
                        SELECT gi.vpn_ip, gi.eui, gi.wifi_ssid, gi.serial_number, gi.gateway_name,
                               gi.status_overall, gi.apn, gi.lora_gateway_id,
                               sc.iccid, sc.vendor_id, sv.vendor_name, gi.sim_card_id, sc.sim_id
                        FROM gateway_inventory gi
                        LEFT JOIN sim_cards sc ON sc.id = gi.sim_card_id
                        LEFT JOIN sim_vendors sv ON sv.id = sc.vendor_id
                        WHERE gi.vpn_ip = %s
                        """,
                        (vpn_ip,),
                    )
                elif eui:
                    cur.execute(
                        """
                        SELECT gi.vpn_ip, gi.eui, gi.wifi_ssid, gi.serial_number, gi.gateway_name,
                               gi.status_overall, gi.apn, gi.lora_gateway_id,
                               sc.iccid, sc.vendor_id, sv.vendor_name, gi.sim_card_id, sc.sim_id
                        FROM gateway_inventory gi
                        LEFT JOIN sim_cards sc ON sc.id = gi.sim_card_id
                        LEFT JOIN sim_vendors sv ON sv.id = sc.vendor_id
                        WHERE gi.eui = %s
                        """,
                        (eui,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT gi.vpn_ip, gi.eui, gi.wifi_ssid, gi.serial_number, gi.gateway_name,
                               gi.status_overall, gi.apn, gi.lora_gateway_id,
                               sc.iccid, sc.vendor_id, sv.vendor_name, gi.sim_card_id, sc.sim_id
                        FROM gateway_inventory gi
                        LEFT JOIN sim_cards sc ON sc.id = gi.sim_card_id
                        LEFT JOIN sim_vendors sv ON sv.id = sc.vendor_id
                        WHERE gi.serial_number = %s
                        """,
                        (serial_number,),
                    )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "vpn_ip": row[0],
                    "eui": row[1],
                    "wifi_ssid": row[2],
                    "serial_number": row[3],
                    "gateway_name": row[4],
                    "status_overall": row[5],
                    "apn": row[6],
                    "lora_gateway_id": row[7],
                    "sim_iccid": row[8],
                    "sim_vendor_id": row[9],
                    "sim_vendor_name": row[10],
                    "sim_card_id": row[11],
                    "sim_id": row[12],
                }
        finally:
            conn.close()

    def save_final_snapshot(self, payload):
        if self.provider_url:
            return self._request(
                "POST",
                "/api/provision",
                json_body={
                    "vpn_ip": payload["vpn_ip"],
                    "eui": payload["eui"],
                    "serial_number": payload["serial_number"],
                    "gateway_name": payload["gateway_name"],
                    "sim_iccid": payload.get("sim_iccid"),
                    "sim_vendor_id": payload.get("sim_vendor_id") or "1",
                    "wifi_ssid": payload["wifi_ssid"],
                    "apn": payload.get("apn"),
                    "cellular_status": payload.get("cellular_status"),
                    "lte_connected": payload.get("lte_connected"),
                    "cellular_ip": payload.get("cellular_ip"),
                    "vpn_key_present": payload.get("vpn_key_present"),
                    "gateway_vendor": payload.get("gateway_vendor"),
                    "gateway_model": payload.get("gateway_model"),
                    "lora_gateway_eui": payload.get("lora_gateway_eui"),
                    "lora_gateway_id": payload.get("lora_gateway_id"),
                    "lora_active_server": payload.get("lora_active_server"),
                    "lora_status": payload.get("lora_status"),
                    "lora_pending": payload.get("lora_pending"),
                    "final_check_ok": True,
                },
            )
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE gateway_inventory
                    SET eui = %s,
                        serial_number = %s,
                        gateway_name = %s,
                        wifi_ssid = %s,
                        apn = %s,
                        cellular_status = %s,
                        lte_connected = %s,
                        cellular_ip = %s,
                        vpn_key_present = %s,
                        gateway_vendor = %s,
                        gateway_model = %s,
                        lora_gateway_eui = %s,
                        lora_gateway_id = %s,
                        lora_active_server = %s,
                        lora_status = %s,
                        lora_pending = %s,
                        last_gateway_sync_at = now(),
                        status_overall = %s,
                        conf_gateway_done = %s
                    WHERE vpn_ip = %s
                    """,
                    (
                        payload["eui"],
                        payload["serial_number"],
                        payload["gateway_name"],
                        payload["wifi_ssid"],
                        payload.get("apn"),
                        payload.get("cellular_status"),
                        payload.get("lte_connected"),
                        payload.get("cellular_ip"),
                        payload.get("vpn_key_present"),
                        payload.get("gateway_vendor"),
                        payload.get("gateway_model"),
                        payload.get("lora_gateway_eui"),
                        payload.get("lora_gateway_id"),
                        payload.get("lora_active_server"),
                        payload.get("lora_status"),
                        payload.get("lora_pending"),
                        payload.get("status_overall", "VERIFIED"),
                        payload.get("conf_gateway_done", True),
                        payload["vpn_ip"],
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def mark_done(self, vpn_ip):
        if self.provider_url:
            self._request("POST", "/api/confirm", json_body={"vpn_ip": vpn_ip})
            return
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE gateway_inventory
                    SET status_overall = 'DEPLOYED',
                        updated_at = now()
                    WHERE vpn_ip = %s
                    """,
                    (vpn_ip,),
                )
            conn.commit()
        finally:
            conn.close()


class ChirpStackConnector:
    def check_gateway(self, eui):
        headers = {"Authorization": f"Bearer {CHIRPSTACK_API_TOKEN}"}
        resp = requests.get(f"{CHIRPSTACK_URL}/api/gateways/{eui}", headers=headers, timeout=8)
        if resp.status_code == 404:
            return {"exists": False}
        if resp.status_code >= 400:
            raise ExternalServiceError(
                "chirpstack",
                f"ChirpStack Fehler {resp.status_code}: {_parse_error_body(resp)}",
                code="http_error",
                details={"http_status": resp.status_code, "response_body": _parse_error_body(resp)},
            )
        return {"exists": True, "payload": resp.json() if resp.content else {}}

    def create_gateway(self, *, eui, serial_number, gateway_name):
        headers = {
            "Authorization": f"Bearer {CHIRPSTACK_API_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "gateway": {
                "gatewayId": eui,
                "name": gateway_name,
                "description": serial_number,
                "tenantId": CHIRPSTACK_TENANT_ID,
                "statsInterval": CHIRPSTACK_STATS_INTERVAL_SECS,
                "tags": {"serial_number": serial_number},
            }
        }
        return _request_json(
            "POST",
            f"{CHIRPSTACK_URL}/api/gateways",
            service="chirpstack",
            headers=headers,
            json=payload,
            timeout=8,
        )

    def connection_status(self):
        try:
            resp = requests.get(
                f"{CHIRPSTACK_URL}/api/gateways/0000000000000000",
                headers={"Authorization": f"Bearer {CHIRPSTACK_API_TOKEN}"},
                timeout=8,
            )
            if resp.status_code not in (200, 404):
                raise ExternalServiceError(
                    "chirpstack",
                    f"ChirpStack Fehler {resp.status_code}: {_parse_error_body(resp)}",
                    code="http_error",
                    details={"http_status": resp.status_code, "response_body": _parse_error_body(resp)},
                )
            return {"ok": True, "service": "chirpstack", "message": "ChirpStack erreichbar", "details": {}}
        except ExternalServiceError as exc:
            return {"ok": False, "service": "chirpstack", "message": exc.message, "details": exc.details}


class MilesightConnector:
    def check_device(self, eui):
        token = milesight_get_token()
        payload = _request_json(
            "POST",
            f"{MILESIGHT_URL}/device/openapi/v1/devices/search",
            service="milesight",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"pageSize": 1, "pageNumber": 1, "devEUI": eui},
            timeout=8,
        )
        content = payload.get("data", {}).get("content", [])
        exists = False
        details = {}
        if content:
            item = content[0]
            dev_eui = (item.get("devEUI") or "").upper()
            sn_dev_eui = (item.get("snDevEUI") or "").upper()
            exists = eui.upper() in {dev_eui, sn_dev_eui}
            if exists:
                details = item
        return {"exists": exists, "payload": details}

    def create_device(self, *, eui, serial_number, gateway_name):
        token = milesight_get_token()
        return _request_json(
            "POST",
            f"{MILESIGHT_URL}/device/openapi/v1/devices",
            service="milesight",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"snDevEUI": serial_number or eui, "name": gateway_name},
            timeout=8,
        )

    def connection_status(self):
        try:
            token = milesight_get_token()
            _request_json(
                "POST",
                f"{MILESIGHT_URL}/device/openapi/v1/devices/search",
                service="milesight",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"pageSize": 1, "pageNumber": 1},
                timeout=8,
            )
            return {"ok": True, "service": "milesight", "message": "Milesight erreichbar", "details": {}}
        except Exception as exc:
            if isinstance(exc, ExternalServiceError):
                return {"ok": False, "service": "milesight", "message": exc.message, "details": exc.details}
            return {"ok": False, "service": "milesight", "message": f"Milesight Token Fehler: {exc}", "details": {}}


class WebserviceConnector:
    def _auth(self, credentials):
        return (credentials.get("username") or "", credentials.get("password") or "")

    def _request(self, method, path, *, credentials, params=None, data=None, timeout=8):
        url = f"{WEBSERVICE_BASE_URL}{path}"
        safe_payload = data or {}
        safe_params = params or {}
        should_log = method.upper() == "POST" and path == "/api/v2/gateway"
        if should_log:
            print(
                f"[gatewaychef_v2/webservice] request method={method} url={url} params={json.dumps(safe_params, ensure_ascii=True)} payload={json.dumps(safe_payload, ensure_ascii=True)}",
                flush=True,
            )
        try:
            resp = requests.request(
                method=method,
                url=url,
                params=params,
                data=data,
                auth=self._auth(credentials),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            if should_log:
                print(
                    f"[gatewaychef_v2/webservice] request_error method={method} url={url} error={exc}",
                    flush=True,
                )
            raise ExternalServiceError(
                "webservice",
                f"webservice Anfrage fehlgeschlagen: {exc}",
                code="request_failed",
                details={"url": url, "request_params": safe_params, "request_payload": safe_payload},
            ) from exc

        response_body = _trim_text(resp.text)
        if should_log:
            print(
                f"[gatewaychef_v2/webservice] response method={method} url={resp.request.url} status={resp.status_code} body={response_body}",
                flush=True,
            )

        if resp.status_code >= 400:
            raise ExternalServiceError(
                "webservice",
                f"webservice Fehler {resp.status_code}: {_parse_error_body(resp)}",
                code="http_error",
                status_code=502,
                details={
                    "url": url,
                    "http_status": resp.status_code,
                    "response_body": _parse_error_body(resp),
                    "request_params": safe_params,
                    "request_payload": safe_payload,
                },
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise ExternalServiceError(
                "webservice",
                "webservice lieferte ungueltiges JSON.",
                code="invalid_json",
                details={
                    "url": url,
                    "response_body": response_body,
                    "request_params": safe_params,
                    "request_payload": safe_payload,
                },
            ) from exc

    def _extract_client(self, item):
        if not isinstance(item, dict):
            return {}
        client = item.get("client") or item.get("customer") or {}
        return {
            "client_id": (
                item.get("clientId")
                or item.get("client_id")
                or item.get("customerId")
                or client.get("id")
                or client.get("clientId")
                or client.get("customerId")
                or ""
            ),
            "client_name": (
                item.get("clientName")
                or item.get("client_name")
                or item.get("customerName")
                or client.get("name")
                or client.get("clientName")
                or client.get("customerName")
                or ""
            ),
            "gateway_name": item.get("name") or item.get("gatewayName") or "",
            "serial_number": item.get("serialNumber") or item.get("serial_number") or item.get("serial") or "",
            "lns": item.get("lns") or "",
        }

    def _extract_client_search_item(self, item):
        if not isinstance(item, dict):
            return {}
        client = item.get("client") or item.get("customer") or {}
        client_id = str(
            item.get("clientId")
            or item.get("client_id")
            or item.get("id")
            or item.get("customerId")
            or item.get("customer_id")
            or item.get("number")
            or client.get("id")
            or client.get("clientId")
            or client.get("customerId")
            or ""
        ).strip()
        return {
            "client_id": client_id,
            "client_name": (
                item.get("name")
                or item.get("clientName")
                or item.get("client_name")
                or item.get("customerName")
                or item.get("customer_name")
                or item.get("title")
                or client.get("name")
                or client.get("clientName")
                or client.get("customerName")
                or client_id
            ),
        }

    def search_gateway(self, eui, credentials):
        data = self._request(
            "GET",
            "/api/v2/gateway",
            credentials=credentials,
            params={"gatewayEui": eui},
            timeout=8,
        )
        items = _normalize_list_payload(data)
        return {"exists": bool(items), "payload": items}

    def lookup_gateway(self, eui, credentials):
        result = self.search_gateway(eui, credentials)
        items = result.get("payload") or []
        first = items[0] if items else {}
        return {
            "exists": bool(items),
            "payload": items,
            "match": self._extract_client(first),
        }

    def lookup_client(self, client_id, credentials):
        query = str(client_id or "").strip()
        if not query:
            return None
        data = self._request(
            "GET",
            "/api/v2/clientsearch",
            credentials=credentials,
            params={"query": query},
            timeout=8,
        )
        items = _normalize_list_payload(data)
        extracted = [self._extract_client_search_item(item) for item in items]
        normalized_query = _normalize_client_id(query)
        exact = next((item for item in extracted if _normalize_client_id(item.get("client_id")) == normalized_query), None)
        return {
            "exists": bool(exact),
            "payload": items,
            "match": exact or {},
        }

    def search_clients(self, query, credentials):
        term = str(query or "").strip()
        if len(term) < 3:
            return {"items": []}
        data = self._request(
            "GET",
            "/api/v2/clientsearch",
            credentials=credentials,
            params={"query": term},
            timeout=8,
        )
        items = _normalize_list_payload(data)
        return {
            "items": [item for item in (self._extract_client_search_item(entry) for entry in items) if item.get("client_id")],
        }

    def create_gateway(self, payload, credentials):
        gateway_id = _normalize_eui(payload.get("eui"))
        gateway_eui = _normalize_eui(payload.get("eui"))
        client_id_value = payload["client_id"]
        try:
            client_id_value = int(client_id_value)
        except (ValueError, TypeError):
            pass
        request_data = {
            "clientId": client_id_value,
            "lns": _normalize_webservice_lns(payload.get("lns")),
            "lnsAddress": payload.get("lns_address"),
            "name": payload["gateway_name"],
            "serialNumber": payload["serial_number"],
            "serial": payload["serial_number"],
            "serial_number": payload["serial_number"],
            "gatewayId": gateway_id,
            "gatewayEui": gateway_eui,
            "simIccid": payload["sim_iccid"],
            "simId": payload["sim_id"],
            "manufacturer": payload["manufacturer"],
            "type": payload["gateway_type"],
            "nfc": payload.get("nfc"),
            "active": True,
        }
        data = {
            **request_data,
        }
        try:
            result = self._request(
                "POST",
                "/api/v2/gateway",
                credentials=credentials,
                params={"clientId": client_id_value},
                data=data,
                timeout=10,
            )
            return result
        except ExternalServiceError as exc:
            details = dict(exc.details or {})
            details["request_params"] = {"clientId": client_id_value}
            details["request_payload"] = request_data
            raise ExternalServiceError(
                "webservice",
                exc.message,
                code=exc.code,
                status_code=exc.status_code,
                details=details,
                stage=exc.stage,
                retryable=exc.retryable,
            ) from exc

    def connection_status(self, credentials=None):
        if not credentials or not credentials.get("username") or not credentials.get("password"):
            return {"ok": None, "service": "webservice", "message": "Webservice Zugangsdaten fehlen", "details": {}}
        try:
            self._request(
                "GET",
                "/api/v2/clientsearch",
                credentials=credentials,
                params={"query": "tes"},
                timeout=8,
            )
            return {"ok": True, "service": "webservice", "message": "Webservice erreichbar", "details": {}}
        except ExternalServiceError as exc:
            return {"ok": False, "service": "webservice", "message": exc.message, "details": exc.details}


class FakeInventoryConnector:
    def __init__(self):
        self.vendors = [{"id": 1, "name": "Telco", "apn": "iot.apn"}]
        self.next_ip = {"vpn_ip": "10.10.10.10", "private_key": "MASKED-PRIVATE-KEY"}
        self.saved = None
        self.done = None
        self.record = None

    def list_sim_vendors(self):
        return list(self.vendors)

    def peek_next_free_ip(self):
        return dict(self.next_ip)

    def reserve_inventory(self, *, gateway_name, serial_number, sim_vendor_id, sim_iccid):
        return {
            "vpn_ip": self.next_ip["vpn_ip"],
            "private_key": self.next_ip["private_key"],
            "apn": "iot.apn",
            "wifi_ssid": derive_wifi_ssid(self.next_ip["vpn_ip"]),
            "sim_id": "SIM-001",
            "sim_card_id": 5,
        }

    def find_sim_vendor(self, vendor_id):
        return self.vendors[0]

    def fetch_gateway_record(self, *, vpn_ip=None, eui=None, serial_number=None):
        return self.record

    def fetch_vpn_key(self, vpn_ip):
        return {"private_key": self.next_ip["private_key"], "serial_number": "SER-001"}

    def save_final_snapshot(self, payload):
        self.saved = json.loads(json.dumps(payload))
        self.record = {
            "vpn_ip": payload["vpn_ip"],
            "eui": payload["eui"],
            "wifi_ssid": payload["wifi_ssid"],
            "serial_number": payload["serial_number"],
            "gateway_name": payload["gateway_name"],
            "status_overall": payload["status_overall"],
            "apn": payload.get("apn"),
            "lora_gateway_id": payload.get("lora_gateway_id"),
            "sim_iccid": payload.get("sim_iccid"),
            "sim_card_id": 5,
            "sim_id": payload.get("sim_id"),
        }

    def mark_done(self, vpn_ip):
        self.done = vpn_ip
        if self.record:
            self.record["status_overall"] = "DEPLOYED"

    def connection_status(self):
        return {"ok": True, "service": "cloud_api", "message": "Cloud API Test-Connector aktiv", "details": {}}


class FakeCloudConnector:
    def __init__(self, exists=False):
        self.exists = exists
        self.created = []

    def check_gateway(self, eui):
        return {"exists": self.exists}

    def check_device(self, eui):
        return {"exists": self.exists}

    def search_gateway(self, eui, credentials):
        return {"exists": self.exists}

    def create_gateway(self, *args, **payload):
        if args:
            payload = {"args": args, **payload}
        self.created.append(payload)
        self.exists = True
        return {"created": True}

    def create_device(self, *args, **payload):
        if args:
            payload = {"args": args, **payload}
        self.created.append(payload)
        self.exists = True
        return {"created": True}

    def connection_status(self, credentials=None):
        return {"ok": True, "service": "fake_cloud", "message": "Test-Connector aktiv", "details": {}}


class FakeGatewayConnector:
    def __init__(self, *, device_info=None, lora=None, lora_health=None):
        self.device_info = device_info or {
            "device": {
                "eui": "AA11BB22CC33DD44",
                "vpn_ip": "10.10.10.10",
                "wifi_ssid": derive_wifi_ssid("10.10.10.10"),
                "mac": "AA:11:BB:22:CC:33",
                "cellular_online": True,
            }
        }
        self.lora = lora or {
            "gateway_id": "AA11BB22CC33DD44",
            "active_server": "chirpstack",
            "status": "connected",
                "pending": False,
        }
        self.lora_health = lora_health or {
            "status": "ONLINE",
            "lns_connected": True,
            "last_seen": "2026-03-07T11:37:52.483Z",
            "seconds_since_ack": 4,
            "seconds_since_stat": 8,
        }

    def fetch_device_info(self):
        return json.loads(json.dumps(self.device_info))

    def fetch_lora_info(self):
        return json.loads(json.dumps(self.lora))

    def fetch_lora_health(self):
        return json.loads(json.dumps(self.lora_health))

    def connection_status(self):
        return {"ok": True, "service": "gateway", "message": "Gateway Test-Connector aktiv", "details": {}}


class FakeNetworkConnector:
    def __init__(self, ok=True):
        self.ok_value = ok

    def ping(self, vpn_ip):
        return {"ok": self.ok_value, "output": "ok" if self.ok_value else "failed"}
