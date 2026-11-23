"""VPN peer overview (/vpn): names and last handshake from the VPN server, joined with the DB.

The VPN server publishes a key-free peers.json (wgpeer json) on 172.30.0.1:8787, reachable only
through the tunnel. The cloud container is a VPN peer (172.30.0.20), so it can read it.
"""
import os

import psycopg2
import requests
from flask import Blueprint, render_template

from config import API_SERVICE_TOKEN, DB_API_PROVIDER_URL
from db.connection import get_db_connection
from services.provisioning_service import ProvisioningService
from utils.response import error, ok

bp = Blueprint("vpn", __name__)
PEERS_URL = os.getenv("VPN_PEERS_URL", "http://172.30.0.1:8787/peers.json")


@bp.route("/vpn")
def vpn_page():
    return render_template("vpn.html")


@bp.route("/api/vpn/peers", methods=["GET"])
def vpn_peers():
    try:
        resp = requests.get(PEERS_URL, timeout=(2, 5))
        resp.raise_for_status()
        doc = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return error(f"VPN-Server nicht erreichbar ({PEERS_URL}): {exc}", 502)
    db = {g["vpn_ip"]: g for g in _db_gateways()}
    for p in doc.get("peers", []):
        g = db.get(p.get("ip"))
        if g:
            p.update({"gateway_name": g["gateway_name"], "serial_number": g["serial_number"],
                      "eui": g["eui"], "status": g["status_overall"]})
    return ok(doc)


def _db_gateways():
    """Gateways from the DB; a local app without DB access asks the cloud DB API. Empty on error."""
    if DB_API_PROVIDER_URL:
        try:
            r = requests.get(DB_API_PROVIDER_URL.rstrip("/") + "/api/db/gateways", timeout=(2, 10),
                             headers={"X-API-Token": API_SERVICE_TOKEN} if API_SERVICE_TOKEN else {})
            return (r.json().get("data") or []) if r.ok else []
        except (requests.RequestException, ValueError):
            return []
    conn = None
    try:
        conn = get_db_connection()
        return ProvisioningService(conn).list_gateways()
    except psycopg2.Error:
        return []  # list still useful without DB names
    finally:
        if conn:
            conn.close()
