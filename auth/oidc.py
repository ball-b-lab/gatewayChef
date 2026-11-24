"""Authentik login (OIDC authorization code + PKCE) for APP_MODE=cloud.

Every request needs a logged-in session, except:
  - /auth/*, /api/version, /healthz (login flow, monitoring)
  - machine clients (local GatewayChef apps) on /api/db/* and /api/network/*
    with a valid X-API-Token / X-Ping-Service-Token (unchanged behaviour).
Pages without a session are redirected to Authentik, API calls get 401.
"""
import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode

import jwt
import requests
from flask import Blueprint, current_app, g, jsonify, redirect, request, session

bp = Blueprint("oidc", __name__)

PUBLIC = ("/auth/", "/api/version", "/healthz", "/static/", "/api/gw/report", "/api/interface/")  # interface: public contract docs; report: own token check
MACHINE = ("/api/db/", "/api/network/", "/api/fleet/snapshots", "/api/fleet/reports/", "/api/fleet/gateway/")  # reads for stations


class OidcConfig:
    def __init__(self, issuer, client_id, client_secret, allowed_group="", http=requests):
        if not (issuer and client_id and client_secret):
            raise RuntimeError("APP_MODE=cloud braucht OIDC_ISSUER, OIDC_CLIENT_ID und OIDC_CLIENT_SECRET.")
        self.issuer = issuer.rstrip("/") + "/"
        self.client_id, self.client_secret = client_id, client_secret
        self.allowed_group = allowed_group.strip()
        self.http = http
        self._meta, self._jwks = None, None

    @property
    def meta(self):
        if self._meta is None:
            r = self.http.get(self.issuer + ".well-known/openid-configuration", timeout=10)
            r.raise_for_status()
            self._meta = r.json()
        return self._meta

    def verify_id_token(self, id_token, nonce):
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self.meta["jwks_uri"])
        key = self._jwks.get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=["RS256", "ES256"], audience=self.client_id,
                            issuer=self.meta.get("issuer", self.issuer.rstrip("/")))
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("nonce passt nicht")
        return claims


def _cfg():
    return current_app.config["OIDC"]


def _token_ok():
    from config import API_SERVICE_TOKEN, VPN_PING_SERVICE_TOKEN
    for header, expected in (("X-API-Token", API_SERVICE_TOKEN), ("X-Ping-Service-Token", VPN_PING_SERVICE_TOKEN)):
        got = request.headers.get(header, "")
        if expected and got and hmac.compare_digest(got, expected):
            return True
    return False


def guard():
    """before_request hook for the whole app."""
    path = request.path
    if path.startswith(PUBLIC):
        return None
    user = session.get("user")
    if user and session.get("exp", 0) > time.time():
        g.user = user
        return None
    if path.startswith(MACHINE) and _token_ok():
        g.user = {"name": "api-token"}
        return None
    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": {"message": "Nicht angemeldet."}}), 401
    return redirect("/auth/login?next=" + requests.utils.quote(request.full_path.rstrip("?"), safe=""))


def _redirect_uri():
    # behind Coolify/Traefik; ProxyFix in init_app makes url_root https
    return request.url_root.rstrip("/") + "/auth/callback"


@bp.route("/auth/login")
def login():
    cfg = _cfg()
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    nxt = request.args.get("next", "/")
    session["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier,
                       "next": nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code", "client_id": cfg.client_id, "redirect_uri": _redirect_uri(),
         "scope": "openid profile email", "state": state, "nonce": nonce,
         "code_challenge": challenge, "code_challenge_method": "S256"}
    return redirect(cfg.meta["authorization_endpoint"] + "?" + urlencode(q))


@bp.route("/auth/callback")
def callback():
    cfg = _cfg()
    pending = session.pop("oidc", None)
    if not pending or not hmac.compare_digest(request.args.get("state", ""), pending["state"]):
        return "Login abgelaufen, bitte neu laden.", 400
    if request.args.get("error"):
        return f"Authentik: {request.args.get('error')}", 403
    r = cfg.http.post(cfg.meta["token_endpoint"], timeout=15, data={
        "grant_type": "authorization_code", "code": request.args.get("code", ""),
        "redirect_uri": _redirect_uri(), "code_verifier": pending["verifier"],
        "client_id": cfg.client_id, "client_secret": cfg.client_secret})
    if r.status_code != 200:
        return "Anmeldung bei Authentik fehlgeschlagen.", 502
    try:
        claims = cfg.verify_id_token(r.json()["id_token"], pending["nonce"])
    except Exception as exc:  # noqa: BLE001 - any token problem means no login
        current_app.logger.warning("OIDC id_token abgelehnt: %s", exc)
        return "Anmeldung ungültig.", 403
    groups = claims.get("groups") or []
    if cfg.allowed_group and cfg.allowed_group not in groups:
        return f"Kein Zugriff: Gruppe '{cfg.allowed_group}' fehlt.", 403
    session.clear()
    session.permanent = True
    session["user"] = {"name": claims.get("name") or claims.get("preferred_username"),
                       "email": claims.get("email"), "sub": claims.get("sub")}
    session["exp"] = time.time() + 12 * 3600
    current_app.logger.info("Login: %s", session["user"]["email"])
    return redirect(pending["next"])


@bp.route("/auth/logout")
def logout():
    session.clear()
    end = _cfg().meta.get("end_session_endpoint")
    return redirect(end or "/")


@bp.route("/auth/me")
def me():
    user = session.get("user") if session.get("exp", 0) > time.time() else None
    return jsonify({"ok": bool(user), "data": user})


def init_app(app, issuer, client_id, client_secret, allowed_group, secret_key):
    if not secret_key or len(secret_key) < 32:
        raise RuntimeError("APP_MODE=cloud braucht FLASK_SECRET_KEY (mind. 32 Zeichen).")
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.secret_key = secret_key
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=12 * 3600)
    app.config["OIDC"] = OidcConfig(issuer, client_id, client_secret, allowed_group)
    app.register_blueprint(bp)
    app.before_request(guard)
