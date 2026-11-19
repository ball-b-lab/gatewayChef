"""Inventory adapters: direct PostgreSQL, or the gatewayChef cloud API (no DB
credentials on the operator laptop)."""
import requests

from services.setup.adapters.base import Inventory
from services.setup.model import SetupError

_FIELDS = ("vpn_ip", "private_key", "eui", "serial_number", "gateway_name",
           "sim_iccid", "sim_id", "sim_vendor_id", "status_overall", "wifi_ssid")

_SELECT = """
    SELECT gi.vpn_ip, gi.private_key, gi.eui, gi.serial_number, gi.gateway_name,
           sc.iccid, sc.sim_id, sc.vendor_id, gi.status_overall, gi.wifi_ssid
    FROM gateway_inventory gi
    LEFT JOIN sim_cards sc ON sc.id = gi.sim_card_id
    WHERE {where}
"""


class DbInventory(Inventory):
    name = "inventory(db)"

    def __init__(self, connect=None):
        if connect is None:
            from db.connection import get_db_connection
            connect = get_db_connection
        self._connect = connect

    def _conn(self):
        try:
            return self._connect()
        except Exception as exc:  # psycopg2.OperationalError etc.
            raise SetupError(f"Datenbank nicht erreichbar: {str(exc).strip()[:150]}") from exc

    def _one(self, where, params):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(_SELECT.format(where=where), params)
                row = cur.fetchone()
            return dict(zip(_FIELDS, row)) if row else None
        finally:
            conn.close()

    def get(self, vpn_ip):
        return self._one("gi.vpn_ip = %s", (vpn_ip,))

    def find_by_eui(self, eui):
        return self._one("upper(gi.eui) = upper(%s)", (eui,))

    def next_free(self):
        from services.provisioning_service import ProvisioningService, ProvisioningError
        conn = self._conn()
        try:
            return ProvisioningService(conn).fetch_next_free_ip()
        except ProvisioningError as exc:
            raise SetupError(exc.message) from exc
        finally:
            conn.rollback()
            conn.close()

    def save(self, gw):
        from services.provisioning_service import ProvisioningService, ProvisioningError
        conn = self._conn()
        try:
            return ProvisioningService(conn).update_customer_data(
                vpn_ip=gw.vpn_ip, gateway_name=gw.name, serial_number=gw.serial_number,
                eui=gw.eui, wifi_ssid=gw.wifi_ssid, sim_iccid=gw.sim_iccid,
                sim_vendor_id=gw.sim_vendor_id,
            )
        except ProvisioningError as exc:
            conn.rollback()
            raise SetupError(exc.message) from exc
        finally:
            conn.close()

    def mark_deployed(self, vpn_ip):
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE gateway_inventory SET status_overall='DEPLOYED', conf_gateway_done=TRUE,"
                    " last_gateway_sync_at=NOW() WHERE vpn_ip=%s", (vpn_ip,))
                if cur.rowcount == 0:
                    raise SetupError(f"Gateway {vpn_ip} nicht in gateway_inventory.")
            conn.commit()
        finally:
            conn.close()


class ApiInventory(Inventory):
    """Talks to the cloud gatewayChef (/api/db/*, X-API-Token)."""
    name = "inventory(api)"

    def __init__(self, base_url, token="", timeout=10, session=None):
        self.base = base_url.rstrip("/")
        self.headers = {"X-API-Token": token} if token else {}
        self.timeout = timeout
        self.http = session or requests.Session()

    def _call(self, method, path, body=None, allow_404=False):
        try:
            resp = self.http.request(method, self.base + path, json=body, headers=self.headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SetupError(f"Cloud-API nicht erreichbar: {exc}") from exc
        if allow_404 and resp.status_code == 404:
            return None
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SetupError(f"Cloud-API {path}: HTTP {resp.status_code}, kein JSON") from exc
        if resp.status_code >= 400 or not payload.get("ok", True):
            msg = (payload.get("error") or {}).get("message") if isinstance(payload, dict) else None
            raise SetupError(f"Cloud-API {path}: {msg or resp.status_code}")
        return payload.get("data")

    def get(self, vpn_ip):
        record = self._call("POST", "/api/db/gateway", {"vpn_ip": vpn_ip}, allow_404=True)
        if not record:
            return None
        key = self._call("POST", "/api/db/vpn-key", {"vpn_ip": vpn_ip}, allow_404=True) or {}
        return dict(record, private_key=key.get("private_key"))

    def find_by_eui(self, eui):
        record = self._call("POST", "/api/db/gateway", {"eui": eui}, allow_404=True)
        return dict(record, private_key=None) if record else None

    def next_free(self):
        return self._call("GET", "/api/db/fetch-ip")

    def save(self, gw):
        return self._call("POST", "/api/db/customer-update", {
            "vpn_ip": gw.vpn_ip, "gateway_name": gw.name, "serial_number": gw.serial_number,
            "eui": gw.eui, "wifi_ssid": gw.wifi_ssid, "sim_iccid": gw.sim_iccid,
            "sim_vendor_id": gw.sim_vendor_id,
        })

    def mark_deployed(self, vpn_ip):
        self._call("POST", "/api/db/mark-deployed", {"vpn_ip": vpn_ip})
