import json
import psycopg2
import requests
from flask import Blueprint, Response, request
from db.connection import get_db_connection
from db.sim import assign_sim, SimAssignmentError
from services.provisioning_service import ProvisioningError, ProvisioningService
from utils.helpers import derive_wifi_ssid, normalize_vpn_ip
from utils.api_token import enforce_api_token
from utils.response import ok, error
from config import APP_MODE, API_SERVICE_TOKEN, DB_API_PROVIDER_URL, DB_API_TIMEOUT_SECS

bp = Blueprint('db', __name__)


@bp.before_request
def _require_api_token():
    if APP_MODE == "local" and DB_API_PROVIDER_URL:
        return _proxy_to_cloud_db_api()
    if APP_MODE == "cloud_api":
        return enforce_api_token()
    return None


def _proxy_to_cloud_db_api():
    provider = (DB_API_PROVIDER_URL or "").rstrip("/")
    if not provider:
        return None

    host_candidates = {
        request.host_url.rstrip("/"),
        f"http://{request.host}".rstrip("/"),
        f"https://{request.host}".rstrip("/"),
    }
    if provider in host_candidates:
        return error("DB_API_PROVIDER_URL zeigt auf dieselbe lokale Instanz.", 500)

    target_url = f"{provider}{request.path}"
    headers = {"Content-Type": request.headers.get("Content-Type", "application/json")}
    if API_SERVICE_TOKEN:
        headers["X-API-Token"] = API_SERVICE_TOKEN

    try:
        upstream = requests.request(
            method=request.method,
            url=target_url,
            params=request.args,
            data=request.get_data(),
            headers=headers,
            timeout=DB_API_TIMEOUT_SECS,
        )
    except requests.RequestException as exc:
        return error(f"DB API Proxy Fehler: {exc}", 502)

    return Response(
        upstream.content,
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "application/json"),
    )



@bp.route('/api/db/fetch-ip', methods=['GET'])
def fetch_ip():
    """
    Fetch the next free VPN IP from the database.
    """
    conn = None
    try:
        conn = get_db_connection()
        service = ProvisioningService(conn)
        return ok(service.fetch_next_free_ip())

    except ProvisioningError as e:
        return error(e.message, e.status_code)
    except psycopg2.Error as e:
        return error(f"Datenbank Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()


@bp.route('/api/db/vpn-key', methods=['POST'])
def fetch_vpn_key():
    """
    Fetch VPN private key and serial by VPN IP.
    """
    conn = None
    try:
        data = request.json or {}
        vpn_ip = data.get('vpn_ip')

        conn = get_db_connection()
        service = ProvisioningService(conn)
        return ok(service.fetch_vpn_key(vpn_ip))
    except ProvisioningError as e:
        return error(e.message, e.status_code)
    except psycopg2.Error as e:
        return error(f"Datenbank Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()


@bp.route('/api/db/gateway', methods=['POST'])
def fetch_gateway_record():
    """
    Fetch gateway record by VPN IP or EUI for comparison.
    """
    data = request.json or {}
    vpn_ip = data.get('vpn_ip')
    eui = data.get('eui')
    serial_number = data.get('serial_number')
    if not vpn_ip and not eui and not serial_number:
        return error("VPN IP, EUI oder Serial fehlt.", 400)

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if vpn_ip:
            cur.execute("""
                SELECT gi.vpn_ip, gi.eui, gi.wifi_ssid, gi.serial_number, gi.gateway_name,
                       gi.status_overall,
                       sc.iccid, sc.vendor_id, sv.vendor_name, gi.sim_card_id, sc.sim_id
                FROM gateway_inventory gi
                LEFT JOIN sim_cards sc ON sc.id = gi.sim_card_id
                LEFT JOIN sim_vendors sv ON sv.id = sc.vendor_id
                WHERE gi.vpn_ip = %s
            """, (vpn_ip,))
        elif eui:
            cur.execute("""
                SELECT gi.vpn_ip, gi.eui, gi.wifi_ssid, gi.serial_number, gi.gateway_name,
                       gi.status_overall,
                       sc.iccid, sc.vendor_id, sv.vendor_name, gi.sim_card_id, sc.sim_id
                FROM gateway_inventory gi
                LEFT JOIN sim_cards sc ON sc.id = gi.sim_card_id
                LEFT JOIN sim_vendors sv ON sv.id = sc.vendor_id
                WHERE gi.eui = %s
            """, (eui,))
        else:
            cur.execute("""
                SELECT gi.vpn_ip, gi.eui, gi.wifi_ssid, gi.serial_number, gi.gateway_name,
                       gi.status_overall,
                       sc.iccid, sc.vendor_id, sv.vendor_name, gi.sim_card_id, sc.sim_id
                FROM gateway_inventory gi
                LEFT JOIN sim_cards sc ON sc.id = gi.sim_card_id
                LEFT JOIN sim_vendors sv ON sv.id = sc.vendor_id
                WHERE gi.serial_number = %s
            """, (serial_number,))
        row = cur.fetchone()
        if not row:
            return error("Gateway nicht gefunden.", 404)
        return ok({
            "vpn_ip": row[0],
            "eui": row[1],
            "wifi_ssid": row[2],
            "serial_number": row[3],
            "gateway_name": row[4],
            "status_overall": row[5],
            "sim_iccid": row[6],
            "sim_vendor_id": row[7],
            "sim_vendor_name": row[8],
            "sim_card_id": row[9],
            "sim_id": row[10]
        })
    except psycopg2.Error as e:
        return error(f"Datenbank Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()


@bp.route('/api/db/customer-update', methods=['POST'])
def update_customer_data():
    """
    Update customer data (name/serial/SIM) by VPN IP.
    """
    data = request.json or {}
    vpn_ip = data.get('vpn_ip')
    gateway_name = data.get('gateway_name')
    serial_number = data.get('serial_number')
    sim_iccid = data.get('sim_iccid')
    sim_vendor_id = data.get('sim_vendor_id')
    sim_card_id = data.get('sim_card_id')

    if not vpn_ip:
        return error("VPN IP fehlt.", 400)

    if not any([gateway_name, serial_number, sim_iccid, sim_vendor_id, sim_card_id]):
        return error("Keine Kundendaten vorhanden.", 400)

    conn = None
    try:
        conn = get_db_connection()
        service = ProvisioningService(conn)
        result = service.update_customer_data(
            vpn_ip=vpn_ip,
            gateway_name=gateway_name,
            serial_number=serial_number,
            sim_iccid=sim_iccid,
            sim_vendor_id=sim_vendor_id,
            sim_card_id=sim_card_id,
        )
        return ok(result)
    except ProvisioningError as e:
        return error(e.message, e.status_code)
    except psycopg2.Error as e:
        return error(f"Datenbank Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()


@bp.route('/api/provision', methods=['POST'])
def provision():
    """
    Updates the database with the provisioned details.
    """
    data = request.json
    print(f"[api/provision] payload={json.dumps(data or {}, ensure_ascii=True)}", flush=True)

    vpn_ip = normalize_vpn_ip(data.get('vpn_ip'))
    eui = data.get('eui')
    serial = data.get('serial_number')
    gateway_name = data.get('gateway_name')
    sim_iccid = data.get('sim_iccid')
    sim_vendor_id = data.get('sim_vendor_id')
    sim_card_id = data.get('sim_card_id')
    wifi_ssid = data.get('wifi_ssid')
    wifi_ip = data.get('wifi_ip')
    apn = data.get('apn')
    cellular_status = data.get('cellular_status')
    lte_connected = data.get('lte_connected')
    cellular_ip = data.get('cellular_ip')
    vpn_key_present = data.get('vpn_key_present')
    gateway_vendor = data.get('gateway_vendor')
    gateway_model = data.get('gateway_model')
    lora_gateway_eui = data.get('lora_gateway_eui')
    lora_gateway_id = data.get('lora_gateway_id')
    lora_active_server = data.get('lora_active_server')
    lora_status = data.get('lora_status')
    lora_pending = data.get('lora_pending')
    final_check_ok = data.get('final_check_ok')

    if not eui and lora_gateway_eui:
        eui = lora_gateway_eui
    if not lora_gateway_id and lora_gateway_eui:
        lora_gateway_id = lora_gateway_eui
    if cellular_ip == "":
        cellular_ip = None

    if not wifi_ssid:
        wifi_ssid = derive_wifi_ssid(vpn_ip)

    missing = []
    if not vpn_ip:
        missing.append("vpn_ip")
    if not eui:
        missing.append("eui")
    if not serial:
        missing.append("serial_number")
    if not gateway_name:
        missing.append("gateway_name")
    if not sim_vendor_id:
        missing.append("sim_vendor_id")
    if not sim_iccid:
        missing.append("sim_iccid")
    if missing:
        return error(
            "Fehlende Daten: " + ", ".join(missing),
            400,
            code="missing_fields",
            data={"missing": missing}
        )

    if sim_vendor_id == "":
        sim_vendor_id = None
    if sim_card_id == "":
        sim_card_id = None
    if sim_iccid == "":
        sim_iccid = None

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id
            FROM gateway_inventory
            WHERE vpn_ip = %s
            FOR UPDATE
        """, (vpn_ip,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return error(f"IP {vpn_ip} nicht gefunden oder update fehlgeschlagen.", 404)
        gateway_id = row[0]

        try:
            assigned_sim_id = assign_sim(cur, gateway_id, sim_vendor_id, sim_iccid, sim_card_id)
        except SimAssignmentError as e:
            conn.rollback()
            return error(e.message, e.status_code)

        status_value = 'DEPLOYED'
        conf_done_value = True

        cur.execute("""
            UPDATE gateway_inventory
            SET eui = %s, serial_number = %s, gateway_name = %s,
                sim_card_id = %s,
                wifi_ssid = %s,
                wifi_ip = %s,
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
                assigned_at = NOW(),
                last_gateway_sync_at = NOW(),
                status_overall = %s, conf_gateway_done = %s
            WHERE id = %s
        """, (
            eui, serial, gateway_name, assigned_sim_id,
            wifi_ssid, wifi_ip, apn, cellular_status, lte_connected, cellular_ip,
            vpn_key_present, gateway_vendor, gateway_model, lora_gateway_eui, lora_gateway_id, lora_active_server,
            lora_status, lora_pending,
            status_value, conf_done_value,
            gateway_id
        ))

        if cur.rowcount == 0:
            conn.rollback()
            return error(f"IP {vpn_ip} nicht gefunden oder update fehlgeschlagen.", 404)

        conn.commit()
        return ok({"status": "success", "message": f"Gateway {gateway_name} erfolgreich provisioniert."})

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error(f"Datenbank Update Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()


@bp.route('/api/sim/vendors', methods=['GET'])
def list_sim_vendors():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, vendor_name, apn
            FROM sim_vendors
            ORDER BY vendor_name
        """)
        vendors = [
            {"id": row[0], "name": row[1], "apn": row[2]}
            for row in cur.fetchall()
        ]
        return ok({"vendors": vendors})
    except psycopg2.Error as e:
        return error(f"Datenbank Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()


@bp.route('/api/sim/next', methods=['POST'])
def next_sim():
    data = request.json or {}
    vendor_id = data.get('vendor_id')
    if not vendor_id:
        return error("SIM Vendor fehlt.", 400)

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, iccid, sim_id
            FROM sim_cards
            WHERE vendor_id = %s AND assigned_gateway_id IS NULL
            ORDER BY id
            LIMIT 1
        """, (vendor_id,))
        row = cur.fetchone()
        if not row:
            return error("Keine freie SIM gefunden.", 404)
        return ok({"id": row[0], "iccid": row[1], "sim_id": row[2]})
    except psycopg2.Error as e:
        return error(f"Datenbank Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()


@bp.route('/api/confirm', methods=['POST'])
def confirm_provision():
    """
    Confirms the provisioning process by marking the record as DEPLOYED.
    """
    data = request.json
    vpn_ip = data.get('vpn_ip')

    if not vpn_ip:
        return error("Fehlende VPN IP.", 400)

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE gateway_inventory
            SET status_overall = 'DEPLOYED'
            WHERE vpn_ip = %s
        """, (vpn_ip,))

        if cur.rowcount == 0:
            conn.rollback()
            return error(f"IP {vpn_ip} nicht gefunden oder update fehlgeschlagen.", 404)

        conn.commit()
        return ok({"status": "success", "message": f"Gateway {vpn_ip} als DEPLOYED markiert."})

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error(f"Datenbank Update Fehler: {e}", 500)
    finally:
        if conn:
            conn.close()
