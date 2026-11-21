"""Milesight Development Platform and ChirpStack (LNS) adapters."""
import requests

from services.setup.adapters.base import Registry
from services.setup.model import SetupError, normalize_eui


class MilesightPlatform(Registry):
    name = "milesight"

    def __init__(self, base_url, client_id, client_secret, token_url="", timeout=10, session=None):
        self.base = (base_url or "").rstrip("/")
        self.client_id, self.client_secret = client_id, client_secret
        self.token_url = token_url or f"{self.base}/oauth/token"
        self.timeout = timeout
        self.http = session or requests.Session()
        self._token = None

    def missing_config(self):
        return [k for k, v in (("MILESIGHT_URL", self.base), ("MILESIGHT_CLIENT_ID", self.client_id),
                               ("MILESIGHT_CLIENT_SECRET", self.client_secret)) if not v]

    def _headers(self):
        if not self._token:
            try:
                resp = self.http.post(self.token_url, data={"grant_type": "client_credentials",
                                      "client_id": self.client_id, "client_secret": self.client_secret},
                                      timeout=self.timeout)
            except requests.RequestException as exc:
                raise SetupError(f"Milesight nicht erreichbar: {exc}") from exc
            if resp.status_code != 200:
                raise SetupError(f"Milesight Token HTTP {resp.status_code}")
            payload = resp.json()
            data = payload.get("data") or {}
            self._token = data.get("access_token") or data.get("token") or payload.get("access_token")
            if not self._token:
                raise SetupError("Milesight Token fehlt in Antwort")
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def find(self, gw):
        wanted = {v.upper() for v in (normalize_eui(gw.eui), gw.serial_number) if v}
        for key in ("snDevEUI", "devEUI"):
            for value in wanted:
                resp = self.http.post(f"{self.base}/device/openapi/v1/devices/search", headers=self._headers(),
                                      json={"pageSize": 5, "pageNumber": 1, key: value}, timeout=self.timeout)
                if resp.status_code != 200:
                    raise SetupError(f"Milesight Suche HTTP {resp.status_code}")
                for item in (resp.json().get("data") or {}).get("content") or []:
                    if {str(item.get("devEUI") or "").upper(), str(item.get("snDevEUI") or "").upper(),
                        str(item.get("sn") or "").upper()} & wanted:
                        return item
        return None

    def describe_create(self, gw):
        return {"snDevEUI": gw.serial_number or normalize_eui(gw.eui), "name": gw.name}

    def required_fields(self):
        return ["eui", "name"]

    def create(self, gw):
        resp = self.http.post(f"{self.base}/device/openapi/v1/devices", headers=self._headers(),
                              json=self.describe_create(gw), timeout=self.timeout)
        if resp.status_code != 200:
            raise SetupError(f"Milesight Anlegen HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json().get("data") or {}


class ChirpStackLns(Registry):
    name = "chirpstack"

    def __init__(self, base_url, token, tenant_id, stats_interval=30, timeout=10, session=None):
        self.base = (base_url or "").rstrip("/")
        self.token, self.tenant_id, self.stats_interval = token, tenant_id, stats_interval
        self.timeout = timeout
        self.http = session or requests.Session()

    def missing_config(self):
        return [k for k, v in (("CHIRPSTACK_URL", self.base and "example.com" not in self.base),
                               ("CHIRPSTACK_API_TOKEN", self.token), ("CHIRPSTACK_TENANT_ID", self.tenant_id)) if not v]

    def required_fields(self):
        return ["eui", "name", "serial_number"]

    def find(self, gw):
        resp = self.http.get(f"{self.base}/api/gateways/{normalize_eui(gw.eui).lower()}",
                             headers={"Authorization": f"Bearer {self.token}"}, timeout=self.timeout)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise SetupError(f"ChirpStack HTTP {resp.status_code}")
        return resp.json()

    def describe_create(self, gw):
        return {"gateway": {"gatewayId": normalize_eui(gw.eui).lower(), "name": gw.name,
                            "description": gw.serial_number, "tenantId": self.tenant_id,
                            "statsInterval": self.stats_interval, "tags": {"serial_number": gw.serial_number or ""}}}

    def create(self, gw):
        resp = self.http.post(f"{self.base}/api/gateways", json=self.describe_create(gw),
                              headers={"Authorization": f"Bearer {self.token}"}, timeout=self.timeout)
        if resp.status_code not in (200, 201):
            raise SetupError(f"ChirpStack Anlegen HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}
