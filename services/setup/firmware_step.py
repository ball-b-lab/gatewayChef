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


# Milesight release notes: a target firmware only installs from at least this version
# (60.0.0.50: "update to 56.0.0.5/60.0.0.45 or later first, otherwise the upgrade fails").
MIN_FROM = {"60.0.0.50": "60.0.0.45"}


def upgrade_path(current, images):
    """Versions to install one after the other to reach the newest image. Raises ValueError
    when an intermediate firmware is needed but not in FIRMWARE_DIR."""
    path, at = [], current
    target = newest_image(images)
    while is_older(at, target):
        ok = [v for v in images if is_older(at, v) and not is_older(at, MIN_FROM.get(v, ""))]
        if not ok:
            need = MIN_FROM.get(target)
            raise ValueError(f"{at} -> {target} braucht erst mindestens {need}; diese Firmware fehlt in FIRMWARE_DIR")
        at = max(ok, key=_key)
        path.append(at)
    return path


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
    try:
        path = upgrade_path(current, images)
    except ValueError as exc:
        r.status, r.detail = FAIL, str(exc)
        return r
    plan = " -> ".join([current] + [images[v]["label"] for v in path])
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
    for i, version in enumerate(path, 1):
        hop = f"Schritt {i}/{len(path)}: " if len(path) > 1 else ""
        try:
            # on the bench, not yet in the field: the field stability gate (LNS, cellular) does not apply
            res = fl.firmware_upgrade(fleet, fleet.inventory.row, version, apply=True, images=images, force=True,
                                       progress=lambda msg, hop=hop: print(f"       ... Firmware: {hop}{msg}", flush=True))
        except Exception as exc:  # noqa: BLE001
            r.status, r.detail = FAIL, f"{plan}: {hop}{exc}"
            return r
        for c in res.get("checks", []):
            r.checks.append((hop + c["label"], c["ok"], c["info"]))
        if res.get("result") == "updated":
            r.status, r.detail = CHANGED, plan
            client.firmware = version
        elif res.get("result") != "ok":
            r.status, r.detail = FAIL, f"{plan}: {hop}{res.get('result')} {res.get('detail', '')}".strip()
            return r
    if r.status == OK:
        r.detail = res.get("detail", "")
    return r
