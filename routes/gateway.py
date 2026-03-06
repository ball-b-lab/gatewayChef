import json
import traceback
import requests
from flask import Blueprint
from config import GATEWAY_URL, DEVICE_INFO_PATH, DEVICE_INFO_LORA_PATH, CELLULAR_STATUS_PATH
from utils.helpers import calculate_eui
from utils.response import ok, error

bp = Blueprint('gateway', __name__)


@bp.route('/api/gateway/device-info', methods=['GET'])
def gateway_device_info():
    """
    Reads device info from the gateway's Node-RED endpoint and derives EUI.
    """
    try:
        url = f"{GATEWAY_URL}{DEVICE_INFO_PATH}"
        resp = requests.get(url, timeout=5)

        if resp.status_code != 200:
            return error(f"Device-Info Error {resp.status_code}", resp.status_code)

        try:
            payload = resp.json()
        except ValueError:
            return error("Invalid JSON response from Gateway", 502)

        print(f"[gateway/device-info] payload={json.dumps(payload, ensure_ascii=True)}", flush=True)

        device = payload.get("device", {}) if isinstance(payload, dict) else {}
        raw_mac = device.get("mac") or payload.get("mac") or ""
        eui = device.get("eui") or calculate_eui(raw_mac)
        vpn_ip = device.get("vpn_ip") or payload.get("vpn_ip") or ""
        status = payload.get("status")
        wifi_ssid = device.get("wifi_ssid") or device.get("ssid") or payload.get("wifi_ssid") or payload.get("ssid") or ""
        interfaces = device.get("interfaces") or payload.get("interfaces") or {}
        cellular_online = device.get("cellular_online") if "cellular_online" in device else payload.get("cellular_online")

        return ok({
            "status": status,
            "mac": raw_mac,
            "eui": eui,
            "vpn_ip": vpn_ip,
            "wifi_ssid": wifi_ssid,
            "interfaces": interfaces,
            "cellular_online": cellular_online
        })

    except requests.exceptions.ConnectTimeout:
        return error("Gateway Zeitüberschreitung (Timeout). Prüfe Verbindung.", 504)
    except requests.exceptions.ConnectionError:
        return error("Gateway nicht erreichbar (Verbindungsfehler).", 502)
    except Exception as e:
        traceback.print_exc()
        return error(f"Critical Error: {str(e)}", 500)


@bp.route('/api/gateway/device-info-lora', methods=['GET'])
def gateway_device_info_lora():
    """
    Reads LoRa packet forwarder info from the gateway's Node-RED endpoint.
    """
    try:
        url = f"{GATEWAY_URL}{DEVICE_INFO_LORA_PATH}"
        resp = requests.get(url, timeout=5)

        if resp.status_code != 200:
            return error(f"Device-Info Lora Error {resp.status_code}", resp.status_code)

        try:
            payload = resp.json()
        except ValueError:
            return error("Invalid JSON response from Gateway", 502)

        print(f"[gateway/device-info-lora] payload={json.dumps(payload, ensure_ascii=True)}", flush=True)

        return ok(payload)

    except requests.exceptions.ConnectTimeout:
        return error("Gateway Zeitüberschreitung (Timeout). Prüfe Verbindung.", 504)
    except requests.exceptions.ConnectionError:
        return error("Gateway nicht erreichbar (Verbindungsfehler).", 502)
    except Exception as e:
        traceback.print_exc()
        return error(f"Critical Error: {str(e)}", 500)


@bp.route('/api/gateway/status-cellular', methods=['GET'])
def gateway_status_cellular():
    """
    Reads cellular status from the gateway's /status/cellular endpoint.
    """
    try:
        url = f"{GATEWAY_URL}{CELLULAR_STATUS_PATH}"
        resp = requests.get(url, timeout=5)

        if resp.status_code != 200:
            return error(f"Cellular Status Error {resp.status_code}", resp.status_code)

        try:
            payload = resp.json()
        except ValueError:
            return error("Invalid JSON response from Gateway", 502)

        return ok(payload)

    except requests.exceptions.ConnectTimeout:
        return error("Gateway Zeitüberschreitung (Timeout). Prüfe Verbindung.", 504)
    except requests.exceptions.ConnectionError:
        return error("Gateway nicht erreichbar (Verbindungsfehler).", 502)
    except Exception as e:
        traceback.print_exc()
        return error(f"Critical Error: {str(e)}", 500)
