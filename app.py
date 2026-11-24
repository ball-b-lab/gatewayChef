import threading
import time
import webbrowser
import os
import sys
import subprocess
import requests
from pathlib import Path
from flask import Flask, redirect, render_template
from werkzeug.exceptions import HTTPException
from config import (
    PORT,
    HOST,
    DB_USER,
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_PASSWORD,
    DATABASE_URL,
    APP_MODE,
    ENABLE_LOCAL_AUTH,
    SKIP_AUTH,
    DB_API_PROVIDER_URL,
    VPN_PING_PROVIDER_URL,
    RECOMMENDED_GATEWAY_FIRMWARE,
    API_SERVICE_TOKEN,
    OIDC_ISSUER,
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_ALLOWED_GROUP,
    FLASK_SECRET_KEY,
)
from routes.gateway import bp as gateway_bp
from routes.db import bp as db_bp
from routes.network import bp as network_bp
from routes.chirpstack import bp as chirpstack_bp
from routes.milesight import bp as milesight_bp
from routes.webservice import bp as webservice_bp
from routes.fleet import bp as fleet_bp
from routes.vpn import bp as vpn_bp
from routes.station import bp as station_bp
from utils.response import error, ok

def resource_path(relative):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)).resolve()
    return str(base / relative)

def _git_sha_fallback():
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return output.strip()
    except Exception:
        return ""

def _version_payload():
    build_sha = os.getenv("APP_BUILD_SHA", "").strip() or _git_sha_fallback()
    return {
        "service": "gatewaychef",
        "app_mode": APP_MODE,
        "build_sha": build_sha or "unknown",
        "build_tag": os.getenv("APP_BUILD_TAG", "").strip() or "unknown",
        "build_time": os.getenv("APP_BUILD_TIME", "").strip() or "unknown",
    }


def _summarize_response_body(resp):
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            if payload.get("error", {}).get("message"):
                return payload["error"]["message"]
            if payload.get("data", {}).get("message"):
                return payload["data"]["message"]
            if payload.get("data", {}).get("build_sha"):
                return f"build_sha={payload['data'].get('build_sha')} app_mode={payload['data'].get('app_mode')}"
            if payload.get("data", {}).get("count") is not None:
                return f"count={payload['data'].get('count')} total={payload['data'].get('total_count')}"
        return str(payload)[:200]
    except ValueError:
        return (resp.text or "")[:200]


def _run_db_proxy_preflight():
    if APP_MODE != "local" or not DB_API_PROVIDER_URL:
        return

    provider = DB_API_PROVIDER_URL.rstrip("/")
    headers = {}
    if API_SERVICE_TOKEN:
        headers["X-API-Token"] = API_SERVICE_TOKEN

    checks = [
        ("version", "GET", f"{provider}/api/version", {}),
        ("db_table", "GET", f"{provider}/api/db/table-view?limit=1", {"headers": headers}),
    ]

    print("--- DB Proxy Preflight ---", flush=True)
    print(f"Provider: {provider}", flush=True)
    print(f"API token configured: {'yes' if API_SERVICE_TOKEN else 'no'}", flush=True)

    for label, method, url, extra in checks:
        try:
            resp = requests.request(method, url, timeout=6, **extra)
            summary = _summarize_response_body(resp)
            print(f"[preflight:{label}] HTTP {resp.status_code} {url}", flush=True)
            if summary:
                print(f"[preflight:{label}] {summary}", flush=True)
        except requests.RequestException as exc:
            print(f"[preflight:{label}] REQUEST FAILED {url}", flush=True)
            print(f"[preflight:{label}] {exc}", flush=True)
    print("--------------------------", flush=True)

app = Flask(
    __name__,
    template_folder=resource_path('templates'),
    static_folder=resource_path('static')
)


@app.errorhandler(Exception)
def handle_exception(e):
    """
    Return JSON for unhandled exceptions instead of HTML traceback.
    """
    try:
        if isinstance(e, HTTPException):
            return error(e.description, e.code)
        return error(str(e), 500)
    except Exception:
        return error("Internal Server Error", 500)


def _legacy_home():
    """The old single-gateway setup page stays the start page only in the packaged Windows app (still in use)."""
    return getattr(sys, "frozen", False) or os.getenv("LEGACY_UI_HOME", "").lower() == "true"


@app.route('/')
def index():
    if APP_MODE == 'cloud_api':
        return {"ok": True, "service": "gatewaychef-cloud-api", "mode": APP_MODE}
    if APP_MODE == 'cloud':
        return redirect('/fleet')
    from services.station import load_ports
    if load_ports():
        return redirect('/station')
    return redirect('/einrichtung' if _legacy_home() else '/fleet')


@app.route('/einrichtung')
def legacy_setup():
    """Old single-gateway setup UI (index.html). Kept running, no longer extended."""
    if APP_MODE == 'cloud_api':
        return {"ok": True, "service": "gatewaychef-cloud-api", "mode": APP_MODE}
    if APP_MODE == 'cloud':
        # cloud = remote maintenance only; on-site setup needs the gateway's own WLAN
        return redirect('/fleet')
    from services.station import load_ports
    if load_ports():
        # Linux station with setup ports: the station page replaces the old single-gateway UI
        return redirect('/station')
    return render_template(
        'index.html',
        runtime={
            "app_mode": APP_MODE,
            "db_api_proxy_enabled": bool(DB_API_PROVIDER_URL),
            "db_api_provider_url": DB_API_PROVIDER_URL or "",
            "vpn_ping_proxy_enabled": bool(VPN_PING_PROVIDER_URL),
            "vpn_ping_proxy_url": VPN_PING_PROVIDER_URL or "",
            "local_auth_enabled": bool(ENABLE_LOCAL_AUTH) and APP_MODE != 'cloud',
            "oidc_enabled": APP_MODE == 'cloud',
            "skip_auth_mode": bool(SKIP_AUTH),
            "recommended_gateway_firmware": RECOMMENDED_GATEWAY_FIRMWARE,
        },
    )

@app.route('/api/version', methods=['GET'])
def version():
    return ok(_version_payload())


if APP_MODE == 'cloud':
    from auth import oidc
    oidc.init_app(app, OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ALLOWED_GROUP, FLASK_SECRET_KEY)

app.register_blueprint(db_bp)
app.register_blueprint(network_bp)
if APP_MODE != 'cloud_api':
    if ENABLE_LOCAL_AUTH and APP_MODE != 'cloud':
        try:
            from routes.auth import bp as auth_bp
        except ModuleNotFoundError as exc:
            if exc.name != "jwt":
                raise
            auth_bp = None
            print("WARNUNG: jwt Paket fehlt. Auth-Blueprint wird nicht registriert.", flush=True)
        if auth_bp is not None:
            app.register_blueprint(auth_bp)
    if APP_MODE != 'cloud':
        # on-site setup (gateway WLAN, station ports): local tool only
        app.register_blueprint(gateway_bp)
        app.register_blueprint(chirpstack_bp)
        app.register_blueprint(milesight_bp)
        app.register_blueprint(webservice_bp)
        app.register_blueprint(station_bp)
    app.register_blueprint(fleet_bp)
    if APP_MODE == 'cloud' and os.getenv("ORDERS_WORKER", "1") == "1":
        # open fleet orders: run as soon as the gateway is online (services/orders.py)
        from services import fleet as _fl, orders as _orders
        from routes.fleet import refresh_gateway as _refresh
        _orders.start_worker(_fl.from_env, on_change=_refresh)
    app.register_blueprint(vpn_bp)


def open_browser():
    """Opens the default web browser to the app URL."""
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{PORT}/")


if __name__ == '__main__':
    print(f"--- Startup Configuration ---")
    print(f"Database: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"App mode: {APP_MODE}")
    if DATABASE_URL:
        print("Using DATABASE_URL from environment.")
    print(f"App Port: {PORT}")
    print(f"-----------------------------")

    if not DB_PASSWORD and not DATABASE_URL:
        print("WARNUNG: Weder DB_PASSWORD noch DATABASE_URL gefunden!")

    _run_db_proxy_preflight()

    open_browser_enabled = os.getenv("OPEN_BROWSER", "true").lower() == "true"
    # with the debug reloader every code change restarts the child process: open the browser only once
    if open_browser_enabled and not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Thread(target=open_browser).start()

    debug_enabled = os.getenv("FLASK_DEBUG", "true").lower() == "true" and APP_MODE == "local"
    app.run(host=HOST, port=PORT, debug=debug_enabled)
