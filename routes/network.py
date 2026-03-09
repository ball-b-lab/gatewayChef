import ipaddress
import subprocess
import platform
import time
import requests
from flask import Blueprint, request
from config import VPN_PING_PROVIDER_URL, VPN_PING_SERVICE_TOKEN
from utils.response import ok, error

bp = Blueprint('network', __name__)

GATEWAY_HEALTH_TIMEOUT_SECS = 8
GATEWAY_HEALTH_RETRIES = 2
GATEWAY_HEALTH_RETRY_DELAY_SECS = 0.35


def _validate_host(host):
    if not host:
        return None, ("Host fehlt.", 400)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None, ("Ungueltige IP.", 400)
    return host, None


def _run_local_ping(host):
    try:
        system_name = platform.system().lower()
        if 'windows' in system_name:
            # Windows: -n count, -w timeout (ms)
            cmd = ["ping", "-n", "1", "-w", "1000", host]
        else:
            # Linux/Mac: -c count, -W timeout (ms or seconds depending on impl)
            # Linux ping -W is usually seconds, MacOS -W is ms. 
            # Safe bet for 1 second is usually ok.
            cmd = ["ping", "-c", "1", "-W", "1000", host]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='replace',
            timeout=3
        )
        
        # Output is already decoded as text thanks to text=True and errors='replace'
        stdout_text = result.stdout
        stderr_text = result.stderr
        
        ok_status = result.returncode == 0
        output = (stdout_text or stderr_text or "").strip()
        return {"ok": ok_status, "output": output}
    except Exception as e:
        raise RuntimeError(f"Ping Fehler: {e}") from e


def _gateway_health_url(host):
    return f"http://{host}/node-red/lora/health"


def _fetch_gateway_health_direct(host):
    url = _gateway_health_url(host)
    for attempt in range(GATEWAY_HEALTH_RETRIES):
        try:
            resp = requests.get(url, timeout=GATEWAY_HEALTH_TIMEOUT_SECS)
            break
        except requests.RequestException as exc:
            if attempt < GATEWAY_HEALTH_RETRIES - 1:
                time.sleep(GATEWAY_HEALTH_RETRY_DELAY_SECS)
            else:
                return None, (f"Gateway Health Fehler: {exc}", 502)

    if resp.status_code != 200:
        return None, (f"Gateway Health Fehler {resp.status_code}", resp.status_code)

    try:
        payload = resp.json()
    except ValueError:
        return None, ("Gateway Health lieferte ungueltiges JSON.", 502)

    return {"ok": True, "via": "http_health", "url": url, "payload": payload}, None


def _proxy_gateway_health(host):
    url = f"{VPN_PING_PROVIDER_URL}/api/network/gateway-health"
    headers = {"Content-Type": "application/json"}
    if VPN_PING_SERVICE_TOKEN:
        headers["X-Ping-Service-Token"] = VPN_PING_SERVICE_TOKEN
    payload = {}
    for attempt in range(GATEWAY_HEALTH_RETRIES):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json={"host": host},
                timeout=GATEWAY_HEALTH_TIMEOUT_SECS,
            )
            payload = resp.json() if resp.content else {}
            break
        except requests.RequestException as exc:
            if attempt < GATEWAY_HEALTH_RETRIES - 1:
                time.sleep(GATEWAY_HEALTH_RETRY_DELAY_SECS)
                continue
            return None, (f"Gateway Health Proxy Fehler: {exc}", 502)
        except ValueError:
            return None, ("Gateway Health Proxy lieferte ungueltiges JSON.", 502)

    if resp.status_code >= 400:
        msg = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
        return None, (msg or "Gateway Health Proxy Fehler.", resp.status_code)

    data_out = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data_out, dict):
        return None, ("Gateway Health Proxy Antwort unvollstaendig.", 502)

    data_out.setdefault("via", "cloud_http_health")
    return data_out, None


@bp.route('/api/network/ping', methods=['POST'])
def ping_host():
    """
    Pings a host locally (from current app runtime).
    """
    data = request.json or {}
    host, err = _validate_host(data.get('host'))
    if err:
        return error(err[0], err[1])
    try:
        return ok(_run_local_ping(host))
    except RuntimeError as exc:
        return error(str(exc), 500)


@bp.route('/api/network/ping-service', methods=['POST'])
def ping_service():
    """
    Ping endpoint for cloud service usage.
    If VPN_PING_SERVICE_TOKEN is configured, caller must send
    X-Ping-Service-Token header.
    """
    if VPN_PING_SERVICE_TOKEN:
        provided = request.headers.get("X-Ping-Service-Token", "")
        if provided != VPN_PING_SERVICE_TOKEN:
            return error("Unauthorized.", 401)

    data = request.json or {}
    host, err = _validate_host(data.get('host'))
    if err:
        return error(err[0], err[1])
    try:
        return ok(_run_local_ping(host))
    except RuntimeError as exc:
        return error(str(exc), 500)


@bp.route('/api/network/vpn-check', methods=['POST'])
def vpn_check():
    """
    Legacy alias for the VPN reachability check.
    Uses the gateway HTTP health endpoint instead of ICMP ping.
    """
    data = request.json or {}
    host, err = _validate_host(data.get('vpn_ip') or data.get('host'))
    if err:
        return error(err[0], err[1])
    if VPN_PING_PROVIDER_URL:
        data_out, proxy_err = _proxy_gateway_health(host)
        if proxy_err:
            return error(proxy_err[0], proxy_err[1])
        return ok(data_out)

    data_out, direct_err = _fetch_gateway_health_direct(host)
    if direct_err:
        return error(direct_err[0], direct_err[1])
    return ok(data_out)


@bp.route('/api/network/gateway-health', methods=['POST'])
def gateway_health():
    """
    Reachability check via HTTP against the gateway's health endpoint over VPN.
    This avoids relying on the system `ping` binary in restricted runtimes.
    """
    data = request.json or {}
    host, err = _validate_host(data.get('vpn_ip') or data.get('host'))
    if err:
        return error(err[0], err[1])

    if VPN_PING_PROVIDER_URL:
        data_out, proxy_err = _proxy_gateway_health(host)
        if proxy_err:
            return error(proxy_err[0], proxy_err[1])
        return ok(data_out)

    data_out, direct_err = _fetch_gateway_health_direct(host)
    if direct_err:
        return error(direct_err[0], direct_err[1])
    return ok(data_out)
