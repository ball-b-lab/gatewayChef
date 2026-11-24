"""
Rename a gateway (name carries the customer: "<x.y> <client no> - <client name>") everywhere we can.

plan() reads the current name per system, apply() writes the new one:
- GatewayChef inventory (gateway_inventory.gateway_name)     -> written
- ChirpStack gateway name (GET + PUT /api/gateways/<eui>)    -> written
- Webservice WS1: its API can only search and create (GET/POST /api/v2/gateway, Cortex 01/2026),
  so name and customer there must be changed by hand; plan() shows the current entry.
"""
import os
import re

import requests

from services.setup.adapters.platforms import ChirpStackLns
from services.setup.factory import build_inventory, build_webservice
from services.setup.model import Gateway, SetupError, normalize_eui

NAME_RE = re.compile(r"^[\w .:+\-/()&äöüÄÖÜß,]{2,100}$")
CLIENT_RE = re.compile(r"^(?P<prefix>\S+)\s+(?P<client_id>\d+)\s+-\s+(?P<client_name>.+)$")


class RenameError(ValueError):
    pass


def split_name(name):
    """'0.116 10999 - Muster GmbH' -> {"prefix", "client_id", "client_name"} (empty if not in that form)."""
    m = CLIENT_RE.match((name or "").strip())
    return m.groupdict() if m else {}


def _chirpstack():
    token = os.getenv("CHIRPSTACK_API_TOKEN", "")
    url = os.getenv("CHIRPSTACK_URL", "")
    if not (token and url):
        return None
    return ChirpStackLns(url, token, os.getenv("CHIRPSTACK_TENANT_ID", ""))


class Renamer:
    def __init__(self, inventory=None, chirpstack="env", webservice="env", http=requests):
        self.inventory = inventory or build_inventory()
        self.cs = _chirpstack() if chirpstack == "env" else chirpstack
        self.ws = build_webservice() if webservice == "env" else webservice
        self.http = http

    def _record(self, vpn_ip):
        rec = self.inventory.get(vpn_ip)
        if not rec:
            raise RenameError(f"{vpn_ip} nicht in der Datenbank")
        return rec

    def plan(self, vpn_ip, new_name):
        new_name = (new_name or "").strip()
        if not NAME_RE.match(new_name):
            raise RenameError("Name: 2–100 Zeichen, Buchstaben, Ziffern, Leerzeichen und . : + - / ( ) & ,")
        rec = self._record(vpn_ip)
        eui = normalize_eui(rec.get("eui"))
        targets = [{"system": "GatewayChef-Datenbank", "current": rec.get("gateway_name"),
                    "action": "same" if rec.get("gateway_name") == new_name else "change"}]
        if not self.cs:
            targets.append({"system": "ChirpStack", "current": None, "action": "skip",
                            "detail": "CHIRPSTACK_URL/CHIRPSTACK_API_TOKEN fehlen"})
        elif not eui:
            targets.append({"system": "ChirpStack", "current": None, "action": "skip", "detail": "keine EUI in der DB"})
        else:
            try:
                found = self.cs.find(Gateway(eui=eui))
                cur = ((found or {}).get("gateway") or {}).get("name")
                targets.append({"system": "ChirpStack", "current": cur,
                                "action": "missing" if not found else "same" if cur == new_name else "change",
                                "detail": None if found else "Gateway in ChirpStack nicht angelegt"})
            except (SetupError, requests.RequestException) as exc:
                targets.append({"system": "ChirpStack", "current": None, "action": "error", "detail": str(exc)[:200]})
        ws = {"system": "Webservice", "current": None, "action": "manual",
              "detail": "Die Webservice-API kann Gateways nur anlegen, nicht ändern: Name und Kunde dort von Hand umstellen."}
        if self.ws and eui:
            try:
                item = self.ws.find(Gateway(eui=eui))
                if item:
                    ws["current"] = item.get("name")
                    ws["client_id"] = item.get("clientId") or item.get("client_id")
                    if ws["current"] == new_name:
                        ws["action"], ws["detail"] = "same", None
                else:
                    ws["detail"] = "Gateway im Webservice nicht gefunden"
            except SetupError as exc:
                ws["detail"] = f"nicht lesbar: {exc}"
        targets.append(ws)
        new = split_name(new_name)
        old = split_name(rec.get("gateway_name"))
        return {"vpn_ip": vpn_ip, "eui": eui, "old_name": rec.get("gateway_name"), "new_name": new_name,
                "client_change": bool(new and old and new.get("client_id") != old.get("client_id")),
                "new_client": new, "targets": targets}

    def apply(self, vpn_ip, new_name):
        p = self.plan(vpn_ip, new_name)
        for t in p["targets"]:
            if t["action"] != "change":
                continue
            try:
                if t["system"] == "GatewayChef-Datenbank":
                    self.inventory.save(Gateway(vpn_ip=vpn_ip, name=p["new_name"]))
                elif t["system"] == "ChirpStack":
                    self._chirpstack_rename(p["eui"], p["new_name"])
                t["action"], t["detail"] = "done", None
            except (SetupError, requests.RequestException, RenameError) as exc:
                t["action"], t["detail"] = "error", str(exc)[:200]
        return p

    def _chirpstack_rename(self, eui, name):
        cs = self.cs
        found = cs.find(Gateway(eui=eui)) or {}
        gw = dict(found.get("gateway") or {})
        if not gw:
            raise RenameError("Gateway in ChirpStack nicht gefunden")
        gw["name"] = name
        resp = cs.http.put(f"{cs.base}/api/gateways/{eui.lower()}", json={"gateway": gw},
                           headers={"Authorization": f"Bearer {cs.token}"}, timeout=cs.timeout)
        if resp.status_code not in (200, 204):
            raise RenameError(f"ChirpStack HTTP {resp.status_code}: {resp.text[:200]}")
