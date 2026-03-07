import threading
import time
import webbrowser
import os
import sys
from pathlib import Path
from flask import Flask, render_template
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
    DB_API_PROVIDER_URL,
)
from routes.gateway import bp as gateway_bp
from routes.db import bp as db_bp
from routes.auth import bp as auth_bp
from routes.network import bp as network_bp
from routes.chirpstack import bp as chirpstack_bp
from routes.milesight import bp as milesight_bp
from routes.webservice import bp as webservice_bp
from utils.response import error

def resource_path(relative):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)).resolve()
    return str(base / relative)

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


@app.route('/')
def index():
    if APP_MODE == 'cloud_api':
        return {"ok": True, "service": "gatewaychef-cloud-api", "mode": APP_MODE}
    return render_template(
        'index.html',
        runtime={
            "app_mode": APP_MODE,
            "db_api_proxy_enabled": bool(DB_API_PROVIDER_URL),
            "db_api_provider_url": DB_API_PROVIDER_URL or "",
        },
    )


app.register_blueprint(db_bp)
app.register_blueprint(network_bp)
if APP_MODE != 'cloud_api':
    app.register_blueprint(auth_bp)
    app.register_blueprint(gateway_bp)
    app.register_blueprint(chirpstack_bp)
    app.register_blueprint(milesight_bp)
    app.register_blueprint(webservice_bp)


def open_browser():
    """Opens the default web browser to the app URL."""
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{PORT}")


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

    open_browser_enabled = os.getenv("OPEN_BROWSER", "true").lower() == "true"
    if open_browser_enabled:
        threading.Thread(target=open_browser).start()

    debug_enabled = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    app.run(host=HOST, port=PORT, debug=debug_enabled)
