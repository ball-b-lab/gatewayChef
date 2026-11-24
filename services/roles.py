"""
Who may do what. Admins (cloud: Authentik group OIDC_ADMIN_GROUP, default "gatewaychef-admin")
may write risky patches and LNS orders other than our standard. Everyone may set the LNS to our
standard (Node-RED UDP 127.0.0.1:1702 first). A station (Linux laptop with setup ports) is not admin unless STATION_ADMIN=1;
the local tool on a developer machine is admin.
"""
import os

from flask import session


def is_admin():
    from config import APP_MODE
    if APP_MODE == "cloud":
        return bool(session.get("admin"))
    from services.station import load_ports
    if load_ports():
        return os.getenv("STATION_ADMIN") == "1"
    return True


def user_name():
    u = session.get("user") or {}
    return u.get("email") or u.get("name") or os.getenv("USER") or "lokal"
