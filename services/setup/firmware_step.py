"""
First setup step: bring the gateway to the newest firmware in FIRMWARE_DIR
before anything is configured (rule since 21.11.2026: always newest first).

Dry run reports "49 -> 50"; apply uploads, waits for the reboot and checks the
version, reusing the fleet firmware upgrade (same checks, LAN host instead of VPN).
Without FIRMWARE_DIR, or with FIRMWARE_AUTO_UPGRADE=0, the step is skipped.
"""
import os
import re

from services import firmware as fw
from services.setup.model import CHANGED, FAIL, OK, WOULD_CHANGE, StepResult


def _key(version):
    return [int(p) if p.isdigit() else p for p in re.split(r"[.\-]", str(version or ""))]


def newest_image(images):
    return max(images, key=_key) if images else None


def is_older(current, target):
    return bool(current and target and _key(current) < _key(target))


class _LanInventory:
    def __init__(self, host, eui, fallback_hosts=()):
        self.row = {"vpn_ip": host, "eui": eui, "gateway_name": host, "status_overall": "SETUP",
                    "fallback_hosts": [h for h in fallback_hosts if h]}

    def list_gateways(self):
        return [self.row]


def step_firmware(pipeline, apply, images=None, fleet_factory=None):
    r = StepResult("Firmware", OK)
    if os.getenv("FIRMWARE_AUTO_UPGRADE", "1") == "0":
        return None  # switched off: step does not appear at all
    images = fw.find_images() if images is None else images
    target = newest_image(images)
    if not target:
        r.status, r.detail = OK, "kein FIRMWARE_DIR: Firmware wird nicht angehoben"
        return r
    client = pipeline.client
    from utils.gateway_lan import gateway_passwords
    password, last = None, None
    for pw in [pipeline.password] + [p for p in gateway_passwords() if p != pipeline.password]:
        try:   # ours first, then the factory password (new gateway)
            client.login(pipeline.user, pw)
            client.get("yruo_wifi", "yruo_wifi")
            password = pw
            break
        except Exception as exc:  # noqa: BLE001 - preflight reports the details
            last = exc
    if password is None:
        r.status, r.detail = OK, f"Firmware nicht lesbar ({str(last)[:80]})"
        return r
    current = client.firmware
    if not is_older(current, target):
        r.detail = f"{current} (neueste: {target})"
        return r
    plan = f"{current} -> {images[target]['label']}"
    if not apply:
        r.status, r.detail = WOULD_CHANGE, plan
        return r
    from services import fleet as fl
    eui, vpn_ip = None, None
    try:
        from services.setup import checks
        dev = (checks.device_info(pipeline.host, http=pipeline.http).get("device")) or {}
        eui, vpn_ip = dev.get("eui"), dev.get("vpn_ip")
    except Exception:  # noqa: BLE001
        pass
    fleet = (fleet_factory or (lambda inv: fl.from_env(reachable_wait=120, gateway_password=password)))(None)
    fleet.inventory = _LanInventory(pipeline.host, eui, [vpn_ip])  # VPN as fallback (update over WLAN)
    try:
        # on the bench, not yet in the field: the field stability gate (LNS, cellular) does not apply
        res = fl.firmware_upgrade(fleet, fleet.inventory.row, target, apply=True, images=images, force=True,
                                   progress=lambda msg: print(f"       ... Firmware: {msg}", flush=True))
    except Exception as exc:  # noqa: BLE001
        r.status, r.detail = FAIL, f"{plan}: {exc}"
        return r
    for c in res.get("checks", []):
        r.checks.append((c["label"], c["ok"], c["info"]))
    if res.get("result") == "updated":
        r.status, r.detail = CHANGED, plan
        client.firmware = target
    elif res.get("result") == "ok":
        r.detail = res.get("detail", "")
    else:
        r.status, r.detail = FAIL, f"{plan}: {res.get('result')} {res.get('detail', '')}".strip()
    return r
