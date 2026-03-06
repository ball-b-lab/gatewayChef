import ipaddress
import subprocess
import platform
import requests
from flask import Blueprint, request
from config import VPN_PING_PROVIDER_URL, VPN_PING_SERVICE_TOKEN
from utils.response import ok, error

bp = Blueprint('network', __name__)


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
    VPN reachability check.
    - If VPN_PING_PROVIDER_URL is set, forwards request to cloud ping service.
    - Otherwise falls back to local ping.
    """
    data = request.json or {}
    host, err = _validate_host(data.get('vpn_ip') or data.get('host'))
    if err:
        return error(err[0], err[1])

    if VPN_PING_PROVIDER_URL:
        url = f"{VPN_PING_PROVIDER_URL}/api/network/ping-service"
        headers = {"Content-Type": "application/json"}
        if VPN_PING_SERVICE_TOKEN:
            headers["X-Ping-Service-Token"] = VPN_PING_SERVICE_TOKEN
        try:
            resp = requests.post(url, headers=headers, json={"host": host}, timeout=5)
            payload = resp.json() if resp.content else {}
        except requests.RequestException as exc:
            return error(f"VPN Ping Proxy Fehler: {exc}", 502)
        except ValueError:
            return error("VPN Ping Proxy lieferte ungueltiges JSON.", 502)

        if resp.status_code >= 400:
            msg = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
            return error(msg or "VPN Ping Proxy Fehler.", resp.status_code)

        data_out = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data_out, dict):
            return error("VPN Ping Proxy Antwort unvollstaendig.", 502)
        return ok(data_out)

    try:
        return ok(_run_local_ping(host))
    except RuntimeError as exc:
        return error(str(exc), 500)
