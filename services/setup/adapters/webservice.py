"""
Webservice adapters. WS1 is today's webservice.ball-b.de (/api/v2/gateway,
Basic Auth). WS2 is the new /adminapi/v1 (Bearer, Idempotency-Key), spec:
bb-protocol-workbench/docs/ws2-api-schreibseite.md ("Gerät — Definition und
Identifikation"). Switching = WEBSERVICE_BACKEND=ws2.
"""
import requests

from services.setup.adapters.base import Registry
from services.setup.model import SetupError, normalize_eui


def _json(resp, what):
    try:
        return resp.json()
    except ValueError as exc:
        raise SetupError(f"{what}: HTTP {resp.status_code}, kein JSON") from exc


def _as_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "content", "items", "gateways", "devices", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
            if isinstance(payload.get(key), dict):
                return _as_list(payload[key])
    return []


class Ws1Webservice(Registry):
    name = "webservice(ws1)"
    LNS_CHIRPSTACK = 2

    def __init__(self, base_url, user, password, timeout=10, session=None):
        self.base = base_url.rstrip("/")
        self.auth = (user, password) if user and password else None
        self.timeout = timeout
        self.http = session or requests.Session()

    def missing_config(self):
        return [] if self.auth else ["WEBSERVICE_USER", "WEBSERVICE_PASSWORD"]

    def required_fields(self):
        return ["eui", "name", "serial_number", "sim_iccid", "sim_id", "client_id"]

    def find(self, gw):
        eui = normalize_eui(gw.eui).lower()
        try:
            resp = self.http.get(f"{self.base}/api/v2/gateway", params={"gatewayEui": eui},
                                 auth=self.auth, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SetupError(f"Webservice nicht erreichbar: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise SetupError(f"Webservice Suche HTTP {resp.status_code}")
        for item in _as_list(_json(resp, "Webservice")):
            if normalize_eui(item.get("gatewayEui") or item.get("gateway_eui") or item.get("eui")).lower() == eui:
                return item
        return None

    def _payload(self, gw):
        eui = normalize_eui(gw.eui).lower()
        client_id = int(gw.client_id) if str(gw.client_id).isdigit() else gw.client_id
        return {
            "clientId": client_id, "lns": self.LNS_CHIRPSTACK, "lnsAddress": gw.lns_address,
            "name": gw.name, "serialNumber": gw.serial_number, "gatewayId": eui, "gatewayEui": eui,
            "simIccid": gw.sim_iccid, "simId": gw.sim_id, "manufacturer": "Milesight",
            "type": gw.model or "UG65", "active": True,
        }

    def describe_create(self, gw):
        return self._payload(gw)

    def create(self, gw):
        data = self._payload(gw)
        try:
            resp = self.http.post(f"{self.base}/api/v2/gateway", params={"clientId": data["clientId"]},
                                  data=data, auth=self.auth, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SetupError(f"Webservice nicht erreichbar: {exc}") from exc
        if resp.status_code >= 400:
            raise SetupError(f"Webservice Anlegen HTTP {resp.status_code}: {resp.text[:300]}")
        return _json(resp, "Webservice")


class Ws2Webservice(Registry):
    """WS2 /adminapi/v1/devices. Device = deviceType + typed identifiers.
    Client assignment of a device is not yet specified in WS2 (open point in
    ws2-api-schreibseite.md) -> reported, not guessed."""
    name = "webservice(ws2)"

    def __init__(self, base_url, read_key, write_key, device_type="UG65", timeout=10, session=None):
        self.base = base_url.rstrip("/")
        self.read_key, self.write_key = read_key, write_key
        self.device_type = device_type
        self.timeout = timeout
        self.http = session or requests.Session()

    def missing_config(self):
        missing = []
        if not self.base:
            missing.append("WS2_URL")
        if not self.read_key:
            missing.append("WS2_READ_KEY")
        if not self.write_key:
            missing.append("WS2_WRITE_KEY")
        return missing

    def required_fields(self):
        return ["eui", "serial_number"]

    def find(self, gw):
        eui = normalize_eui(gw.eui).lower()
        try:
            resp = self.http.get(f"{self.base}/adminapi/v1/devices", params={"q": eui},
                                 headers={"Authorization": f"Bearer {self.read_key}"}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SetupError(f"WS2 nicht erreichbar: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise SetupError(f"WS2 Suche HTTP {resp.status_code}")
        for item in _as_list(_json(resp, "WS2")):
            idents = item.get("identifiers") or []
            values = {normalize_eui(i.get("identifier")).lower() for i in idents if i.get("type") == "eui"}
            if eui in values or normalize_eui(item.get("eui")).lower() == eui:
                return item
        return None

    def _payload(self, gw):
        idents = [{"type": "eui", "identifier": normalize_eui(gw.eui).lower(), "isPrimary": True}]
        if gw.serial_number:
            idents.append({"type": "serial", "identifier": gw.serial_number})
        if gw.sim_iccid:
            idents.append({"type": "iccid", "identifier": gw.sim_iccid})
        return {"deviceType": gw.model or self.device_type, "status": "active", "identifiers": idents}

    def describe_create(self, gw):
        return self._payload(gw)

    def create(self, gw):
        headers = {"Authorization": f"Bearer {self.write_key}",
                   "Idempotency-Key": f"gatewaychef-gw-{normalize_eui(gw.eui).lower()}"}
        try:
            resp = self.http.post(f"{self.base}/adminapi/v1/devices", json=self._payload(gw),
                                  headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SetupError(f"WS2 nicht erreichbar: {exc}") from exc
        if resp.status_code == 409:
            return {"exists": True}
        if resp.status_code >= 400:
            raise SetupError(f"WS2 Anlegen HTTP {resp.status_code}: {resp.text[:300]}")
        return _json(resp, "WS2")
