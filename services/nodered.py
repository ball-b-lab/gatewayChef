"""
Node-RED on the gateway: read installed flow version, deploy a flow bundle,
roll back on failure.

Uses the standard Node-RED admin API below NODERED_ADMIN_ROOT (default
/node-red on the UG65):
  GET  <root>/auth/login            -> does it need a token?
  POST <root>/auth/token            -> bearer token (username/password)
  GET  <root>/flows   (API v2)      -> {"rev", "flows"}
  POST <root>/flows   (API v2)      -> full deploy
  GET  <root>/settings              -> Node-RED version

Flow version
  Bundles live in gateway_profiles/flows/<version>.json (plain flow export).
  The installed version is found by:
    1. hash match against a known bundle -> "1.4.0"
    2. a comment node named "gatewaychef-flow <version>" -> "1.4.0 (geaendert)"
       when the hash does not match (edited on the device)
    3. otherwise "unbekannt"
  Keep node ids stable between bundle versions: Node-RED keeps the stored
  credentials (MQTT passwords etc.) of nodes whose id stays the same.
"""
import glob
import hashlib
import json
import os
import re
import time

import requests

FLOW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gateway_profiles", "flows")
_VERSION_NODE = re.compile(r"^\s*gatewaychef-flow\s+(\S+)\s*$")
# Editor-only fields: moving a node in the editor must not count as a change.
_LAYOUT_KEYS = {"x", "y", "w", "h", "l", "selected", "dirty", "changed", "moved", "valid"}


class NodeRedError(Exception):
    pass


def flow_hash(flows):
    """Stable hash over the logic of a flow export (layout and order ignored)."""
    nodes = []
    for node in flows or []:
        nodes.append({k: v for k, v in node.items() if k not in _LAYOUT_KEYS and k != "credentials"})
    nodes.sort(key=lambda n: str(n.get("id")))
    raw = json.dumps(nodes, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


_LEGACY_VERSION = re.compile(r'const\s+flowVersion\s*=\s*"([^"]+)"')


def declared_version(flows):
    """Comment node 'gatewaychef-flow <v>'; older flows only set flowVersion in a function."""
    for node in flows or []:
        if node.get("type") == "comment":
            match = _VERSION_NODE.match(str(node.get("name") or ""))
            if match:
                return match.group(1)
    for node in flows or []:
        if node.get("type") == "function":
            match = _LEGACY_VERSION.search(str(node.get("func") or ""))
            if match:
                return match.group(1)
    return None


_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_secrets(text, secrets):
    """Bundles keep secrets as {{name}}; they are filled only for the deploy, never stored in git."""
    missing = sorted({k for k in _PLACEHOLDER.findall(text) if not (secrets or {}).get(k)})
    if missing:
        raise NodeRedError(f"Flow-Bundle braucht Werte: {', '.join(missing)}")
    return _PLACEHOLDER.sub(lambda m: json.dumps(str(secrets[m.group(1)]))[1:-1], text)


def default_secrets():
    from services.gateway_config import encrypt_login_password
    pw = os.getenv("GATEWAY_PASSWORD", "")
    return {"gateway_login_password_enc": encrypt_login_password(pw)} if pw else {}


def load_bundles(flow_dir=FLOW_DIR, secrets=None):
    """{version: {"flows": [...], "hash": ...}} from gateway_profiles/flows/*.json.
    Placeholders are rendered with `secrets` (default: from the environment) so the
    hash matches what is installed on the gateway."""
    secrets = default_secrets() if secrets is None else secrets
    bundles = {}
    for path in sorted(glob.glob(os.path.join(flow_dir, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if _PLACEHOLDER.search(text):
            try:
                text = render_secrets(text, secrets)
            except NodeRedError:
                continue  # cannot be deployed or recognised without the secret
        flows = json.loads(text)
        if isinstance(flows, dict):
            flows = flows.get("flows") or []
        version = os.path.splitext(os.path.basename(path))[0]
        bundles[version] = {"flows": flows, "hash": flow_hash(flows), "path": path}
    return bundles


def identify(flows, bundles):
    h = flow_hash(flows)
    for version, bundle in bundles.items():
        if bundle["hash"] == h:
            return {"version": version, "hash": h, "modified": False}
    declared = declared_version(flows)
    if declared:
        return {"version": declared, "hash": h, "modified": True}
    return {"version": None, "hash": h, "modified": None}


def latest_version(bundles):
    def key(v):
        return [int(p) if p.isdigit() else p for p in re.split(r"[.\-]", v)]
    return max(bundles, key=key) if bundles else None


class NodeRedClient:
    def __init__(self, host, username="", password="", root=None, timeout=10, session=None):
        root = root if root is not None else os.getenv("NODERED_ADMIN_ROOT", "/node-red")
        self.base = f"http://{host}{root.rstrip('/')}"
        self.username, self.password = username, password
        self.timeout = timeout
        self.http = session or requests.Session()
        self.token = None

    def _headers(self, extra=None):
        h = {"Node-RED-API-Version": "v2"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h.update(extra or {})
        return h

    def _req(self, method, path, **kw):
        try:
            resp = self.http.request(method, self.base + path, timeout=self.timeout, **kw)
        except requests.RequestException as exc:
            raise NodeRedError(f"Node-RED nicht erreichbar: {type(exc).__name__}") from exc
        if resp.status_code == 401:
            raise NodeRedError("Node-RED: nicht angemeldet (NODERED_USER/NODERED_PASSWORD pruefen)")
        if resp.status_code >= 400:
            raise NodeRedError(f"Node-RED {method} {path}: HTTP {resp.status_code}")
        return resp

    def login(self):
        scheme = self._req("GET", "/auth/login").json()
        if not scheme or scheme.get("type") != "credentials":
            return  # no admin auth configured
        if not self.password:
            raise NodeRedError("Node-RED verlangt Login, NODERED_PASSWORD fehlt")
        data = {"client_id": "node-red-admin", "grant_type": "password", "scope": "*",
                "username": self.username, "password": self.password}
        self.token = self._req("POST", "/auth/token", data=data).json().get("access_token")
        if not self.token:
            raise NodeRedError("Node-RED Login fehlgeschlagen")

    def settings(self):
        return self._req("GET", "/settings", headers=self._headers()).json()

    def get_flows(self):
        data = self._req("GET", "/flows", headers=self._headers()).json()
        if isinstance(data, list):  # API v1 answer
            return {"rev": None, "flows": data}
        return data

    def deploy(self, flows, rev=None):
        body = {"flows": flows}
        if rev:
            body["rev"] = rev
        resp = self._req("POST", "/flows", json=body,
                         headers=self._headers({"Node-RED-Deployment-Type": "full"}))
        return resp.json() if resp.content else {}


def status(client, bundles):
    """Read-only: Node-RED version + installed flow version."""
    client.login()
    current = client.get_flows()
    info = identify(current["flows"], bundles)
    try:
        info["nodered"] = client.settings().get("version")
    except NodeRedError:
        info["nodered"] = None
    latest = latest_version(bundles)
    info["latest"] = latest
    info["up_to_date"] = bool(latest and info["version"] == latest and not info["modified"])
    return info


def update(client, bundle, post_check, backup_dir=None, settle_secs=5, sleep=time.sleep):
    """
    Deploy `bundle`, then run post_check() -> (ok, detail). On failure the
    previous flows are deployed again and post_check runs once more.
    Returns dict with result, before/after version, rollback info.
    """
    client.login()
    before = client.get_flows()
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        path = os.path.join(backup_dir, f"flows-{time.strftime('%Y%m%d-%H%M%S')}-{flow_hash(before['flows'])}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(before["flows"], fh, indent=1)
    if flow_hash(before["flows"]) == bundle["hash"]:
        ok, detail = post_check()
        return {"result": "unchanged" if ok else "failed", "detail": detail, "rolled_back": False}

    client.deploy(bundle["flows"], before.get("rev"))
    sleep(settle_secs)
    after = client.get_flows()
    if flow_hash(after["flows"]) != bundle["hash"]:
        ok, detail = False, "Flows nach Deploy nicht wie erwartet (Hash weicht ab)"
    else:
        ok, detail = post_check()
    if ok:
        return {"result": "updated", "detail": detail, "rolled_back": False}

    client.deploy(before["flows"], after.get("rev"))
    sleep(settle_secs)
    back_ok, back_detail = post_check()
    return {"result": "failed", "detail": detail, "rolled_back": True,
            "rollback_ok": back_ok, "rollback_detail": back_detail}
