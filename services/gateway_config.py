"""
Automated configuration of Milesight UG65 gateways via the gateway's internal
web API (POST /cgi), as used by the gateway's own web UI.

Protocol (derived from the UI JavaScript of FW 60.0.0.49):
  - every call: {"id", "execute": 1, "core", "function", "values"}
  - login:  core=user, function=login, values=[{username, password(AES), base=web_login}]
  - read:   function=get, values=[{"base": <base>}]
  - write:  function=set, values=[{"base", "index", "value": {changed fields}}]
  - commit: core=yruo_apply, function=apply
  - status -2 means "not logged in / session expired"

A profile (JSON) describes the target state. Device specific values are
written as "{{placeholder}}" and filled from a DeviceVars dict.
"""
import base64
import copy
import json
import os
import re
from dataclasses import dataclass, field

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # self-signed HTTPS on newer firmware
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Fixed key/iv hard-coded in the gateway's login.js (not a secret of ours).
_LOGIN_AES_KEY = b"1111111111111111"
_LOGIN_AES_IV = b"2222222222222222"

PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gateway_profiles")
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_SECRET_FIELD = re.compile(r"key|pass|secret|psk|token|private|pwd|cert", re.I)


class GatewayConfigError(Exception):
    pass


def encrypt_login_password(password):
    padder = padding.PKCS7(128).padder()
    data = padder.update(password.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_LOGIN_AES_KEY), modes.CBC(_LOGIN_AES_IV)).encryptor()
    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode("ascii")


class UG65Client:
    def __init__(self, host="192.168.1.1", timeout=10, session=None):
        self.url = f"http://{host}/cgi"
        self.timeout = timeout
        self.session = session or requests.Session()
        self.firmware = None
        self.model = None
        self._id = 1

    def _call(self, core, function, values, timeout=None):
        body = {"id": self._id, "execute": 1, "core": core, "function": function, "values": values}
        self._id += 1
        try:
            kw = {"allow_redirects": False} if isinstance(self.session, requests.Session) else {}
            resp = self.session.post(self.url, data=json.dumps(body), timeout=timeout or self.timeout, **kw)
            if kw and resp.is_redirect and self.url.startswith("http://") and \
                    str(resp.headers.get("Location", "")).startswith("https://"):
                # newer firmware (factory state): web server only on HTTPS, self-signed certificate
                self.url = "https://" + self.url[len("http://"):]
                self.session.verify = False
                resp = self.session.post(self.url, data=json.dumps(body), timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise GatewayConfigError(f"Gateway nicht erreichbar: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GatewayConfigError(f"Ungueltige Antwort vom Gateway (HTTP {resp.status_code})") from exc
        self.firmware = payload.get("rtver") or self.firmware
        self.model = payload.get("model") or self.model
        status = payload.get("status")
        if status == -2:
            raise GatewayConfigError("Nicht eingeloggt oder Sitzung abgelaufen.")
        if status != 0:
            raise GatewayConfigError(f"{core}/{function} fehlgeschlagen: status={status} result={payload.get('result')}")
        return payload.get("result") or []

    def login(self, username, password):
        values = [{"username": username, "password": encrypt_login_password(password), "base": "web_login"}]
        try:
            self.login_result = self._call("user", "login", values)
        except GatewayConfigError as exc:
            raise GatewayConfigError(f"Login fehlgeschlagen: {exc}") from exc

    def get(self, core, base):
        result = self._call(core, "get", [{"base": base}])
        entry = result[0] if result and isinstance(result[0], dict) else {}
        if entry.get("error"):
            raise GatewayConfigError(f"{core}/{base}: {entry['error']}")
        return entry.get("get") or []

    def set(self, core, base, index, value):
        return self._call(core, "set", [{"base": base, "index": index, "value": value}])

    def apply(self, timeout=60):
        """Apply restarts services (WLAN, packet forwarder); the answer can come late or
        never. A read timeout here is not an error: callers read the values back anyway."""
        try:
            return self._call("yruo_apply", "apply", [], timeout=max(timeout, self.timeout))
        except GatewayConfigError as exc:
            if isinstance(exc.__cause__, requests.ReadTimeout):
                return []
            raise

    def reboot(self):
        return self._call("yruo_upgrade", "reboot", [])


# ---------------------------------------------------------------- profiles

def load_profile(name_or_path):
    path = name_or_path
    if not os.path.isfile(path):
        path = os.path.join(PROFILE_DIR, f"{name_or_path}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _version_key(v):
    return [int(p) if p.isdigit() else p for p in re.split(r"[.\-]", v or "")]


def known_profiles(model="ug65"):
    """{firmware: profile name} for all gateway_profiles/<model>-<fw>.json"""
    out = {}
    for f in os.listdir(PROFILE_DIR):
        if f.startswith(f"{model}-") and f.endswith(".json"):
            out[f[len(model) + 1:-5]] = f[:-5]
    return out


def profile_for_firmware(firmware, model="ug65"):
    """Exact profile for this firmware, otherwise the newest one (checked for compatibility later)."""
    profiles = known_profiles(model)
    if firmware in profiles:
        return profiles[firmware]
    if not profiles:
        raise GatewayConfigError("Kein Gateway-Profil vorhanden.")
    return profiles[max(profiles, key=_version_key)]


def firmware_compat(client, profile, policy=None):
    """
    Same firmware as the profile -> exact. Otherwise read every profile section from
    the gateway and compare the interface (sections, fields, types):
      compatible   -> only new fields, nothing missing: allowed unless policy is strict
      incompatible -> missing sections/fields or changed types: never allowed
    Returns {"status", "allowed", "deltas"}.
    """
    policy = (policy or os.getenv("FIRMWARE_POLICY", "compatible")).lower()
    if not profile.get("firmware") or client.firmware == profile.get("firmware"):
        return {"status": "exact", "allowed": True, "deltas": []}
    from services.profile_check import check
    result = check(client, profile)
    deltas = [f"{r['label']}: {r['problem']} ({r['detail']})" for r in result["report"]]
    status = "compatible" if result["compatible"] else "incompatible"
    return {"status": status, "allowed": status == "compatible" and policy != "strict", "deltas": deltas}


class _Skipped:
    """Placeholder whose value is missing in a dry run (survives deepcopy)."""

    def __deepcopy__(self, memo):
        return self

    def __repr__(self):
        return "<nicht geprueft>"


SKIPPED = _Skipped()


def render(obj, device_vars, skip_missing=False):
    """Replace {{placeholders}} recursively. Missing vars raise (or become SKIPPED)."""
    if isinstance(obj, dict):
        return {k: render(v, device_vars, skip_missing) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render(v, device_vars, skip_missing) for v in obj]
    if isinstance(obj, str):
        whole = _PLACEHOLDER.fullmatch(obj)
        if skip_missing and any(device_vars.get(k) in (None, "") for k in _PLACEHOLDER.findall(obj)):
            return SKIPPED
        def repl(match):
            key = match.group(1)
            if device_vars.get(key) in (None, ""):
                raise GatewayConfigError(f"Geraetewert fehlt: {key}")
            return str(device_vars[key])
        if whole:
            repl(whole)
            return device_vars[whole.group(1)]
        return _PLACEHOLDER.sub(repl, obj)
    return obj


def device_vars_from_inventory(vpn_ip, private_key, gateway_eui, wifi_key, wifi_ssid=None):
    from utils.helpers import derive_wifi_ssid

    return {
        "gateway_id": (gateway_eui or "").replace(":", "").upper(),
        "vpn_address": f"{vpn_ip}/32" if vpn_ip and "/" not in vpn_ip else vpn_ip,
        "vpn_private_key": private_key,
        "wifi_ssid": wifi_ssid or derive_wifi_ssid(vpn_ip),
        "wifi_key": wifi_key,
    }


# ---------------------------------------------------------------- planning

@dataclass
class Change:
    core: str
    base: str
    index: object
    label: str
    fields: dict = field(default_factory=dict)      # field -> (current, target)
    peers: list = field(default_factory=list)        # wireguard peer ops

    def set_value(self):
        value = {k: target for k, (_, target) in self.fields.items()}
        if self.peers:
            value["peers"] = self.peers
        return value


def _mask(fieldname, value):
    if _SECRET_FIELD.search(fieldname) and isinstance(value, str) and value:
        return f"***({len(value)})"
    return value


def _find_entry(entries, index):
    for entry in entries:
        if str(entry.get("index")) == str(index):
            return entry
    if index is None and len(entries) == 1:
        return entries[0]
    return None


def _matches(have, want):
    """True if `have` contains everything `want` specifies. Extra keys in dicts
    (e.g. read-only status like servs[].connected) are ignored."""
    if isinstance(want, dict):
        return isinstance(have, dict) and all(_matches(have.get(k), v) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(have, list) and len(have) == len(want) and all(_matches(h, w) for h, w in zip(have, want))
    return have == want


def _plan_peers(current_peers, target_peers):
    ops = []
    by_name = {p.get("name"): p for p in current_peers or []}
    for target in target_peers:
        current = by_name.get(target.get("name"))
        if current is None:
            ops.append(dict(target, action=1))
            continue
        merged = dict(current)
        merged.update(target)
        if not _matches(current, target):
            ops.append(dict(merged, action=2))
    return ops


def plan(client, profile, device_vars, skip_missing=False):
    """Compare gateway against profile. skip_missing=True (dry run only) ignores
    fields whose device value is not known; such a plan is not executable."""
    target_fw = profile.get("firmware")
    sections = render(profile["sections"], device_vars, skip_missing)
    skipped = []
    changes = []
    for section in sections:
        core, base = section["core"], section["base"]
        entries = client.get(core, base)
        entry = _find_entry(entries, section.get("index"))
        if entry is None:
            raise GatewayConfigError(f"{core}/{base}: Eintrag index={section.get('index')} nicht gefunden")
        current = entry.get("value") or {}
        target = copy.deepcopy(section["value"])
        target_peers = target.pop("peers", None)
        change = Change(core, base, entry.get("index"), section.get("label", f"{core}/{base}"))
        for key, want in target.items():
            if want is SKIPPED:
                skipped.append(f"{change.label}: {key}")
                continue
            have = current.get(key)
            if not _matches(have, want):
                change.fields[key] = (have, want)
        if target_peers is not None:
            for peer in target_peers:
                for key in [k for k, v in peer.items() if v is SKIPPED]:
                    skipped.append(f"{change.label}: peer {peer.get('name')}.{key}")
                    del peer[key]
            change.peers = _plan_peers(current.get("peers"), target_peers)
        if change.fields or change.peers:
            changes.append(change)
    return {
        "firmware": client.firmware,
        "model": client.model,
        "firmware_ok": not target_fw or client.firmware == target_fw,
        "target_firmware": target_fw,
        "changes": changes,
        "skipped": skipped,
    }


def format_plan(result):
    lines = [f"Gateway {result['model']} FW {result['firmware']} (Profil: {result['target_firmware']})"]
    if not result["firmware_ok"]:
        lines.append("!! Firmware passt nicht zum Profil.")
    if not result["changes"]:
        lines.append("OK: Konfiguration entspricht dem Profil.")
    for ch in result["changes"]:
        lines.append(f"- {ch.label} ({ch.core}/{ch.base} index={ch.index})")
        for key, (have, want) in ch.fields.items():
            lines.append(f"    {key}: {_mask(key, have)!r} -> {_mask(key, want)!r}")
        for op in ch.peers:
            lines.append(f"    peer {op.get('name')}: {'anlegen' if op['action'] == 1 else 'aendern'}")
    for item in result.get("skipped") or []:
        lines.append(f"  (nicht geprueft, Wert fehlt: {item})")
    return "\n".join(lines)


def execute(client, result, force_firmware=False):
    if result.get("skipped"):
        raise GatewayConfigError("Plan unvollstaendig (fehlende Geraetewerte), Schreiben nicht erlaubt.")
    if not result["firmware_ok"] and not force_firmware:
        raise GatewayConfigError(
            f"Firmware {result['firmware']} ist fuer Profil {result['target_firmware']} nicht freigegeben."
        )
    for ch in result["changes"]:
        client.set(ch.core, ch.base, ch.index, ch.set_value())
    if result["changes"]:
        client.apply()
    return len(result["changes"])
