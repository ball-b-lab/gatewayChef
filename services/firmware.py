"""
Firmware upgrade of a UG65, on the LAN or over the VPN.

Upload path (from the gateway's web UI, FW 60.0.0.49):
  POST /cgi-bin/file-import  multipart/form-data
    sessionid = web session id
    size      = file size in bytes
    filename  = "type=<T>&file=<F>"   (<T>/<F> of the upgrade page: FIRMWARE_UPLOAD_TYPE / _FILE)
    file      = the .bin image
  Success answer: JSON with size + checksum. The UI treats a 404 after >30 s as
  "upload went through, upgrade already running"; we do the same.
  After the reboot GET /islogin -> result[0].upgrade_error (0 / missing = ok).

The two form values <T>/<F> are NOT in the saved UI code (the upgrade page is
loaded separately). They must be confirmed on a device once; until then
FIRMWARE_UPLOAD_TYPE/_FILE are unset and an upgrade refuses to start, because
the same endpoint also imports backups and other files.

Sequence: pre-check -> upload -> wait offline/online -> post-check
  post-check: firmware == target, upgrade_error == 0, right EUI answers,
  interface still compatible with the profile, Node-RED flow hash unchanged.
"""
import os
import re
import time

import requests

from services import gateway_config as gc

_IMAGE = re.compile(r"(\d+\.\d+\.\d+\.\d+)(-r\d+)?\.bin$", re.I)


class FirmwareError(Exception):
    pass


def find_images(directory=None):
    """{"60.0.0.49": {"label": "60.0.0.49-r4", "path": ..., "size": ...}} from FIRMWARE_DIR."""
    directory = directory or os.getenv("FIRMWARE_DIR", "")
    images = {}
    if not directory or not os.path.isdir(directory):
        return images
    for name in sorted(os.listdir(directory)):
        m = _IMAGE.search(name)
        if m:
            path = os.path.join(directory, name)
            images[m.group(1)] = {"label": m.group(1) + (m.group(2) or ""), "path": path,
                                  "size": os.path.getsize(path)}
    return images


def upload_form():
    t, f = os.getenv("FIRMWARE_UPLOAD_TYPE", ""), os.getenv("FIRMWARE_UPLOAD_FILE", "")
    if not t or not f:
        raise FirmwareError("FIRMWARE_UPLOAD_TYPE/FIRMWARE_UPLOAD_FILE nicht gesetzt (einmal am Geraet ermitteln, "
                            "siehe docs/GATEWAY_SETUP_KONZEPT.md, Abschnitt Firmware-Update)")
    return t, f


def session_id(client):
    for item in getattr(client, "login_result", None) or []:
        if isinstance(item, dict):
            for key in ("sessionid", "session_id", "td"):
                if item.get(key):
                    return item[key]
    cookies = getattr(client.session, "cookies", None)
    if cookies is not None:
        for key in ("td", "sessionid"):
            if cookies.get(key):
                return cookies.get(key)
    raise FirmwareError("Keine Web-Session-ID nach dem Login gefunden")


def upload(client, host, image, timeout=1800, http=None):
    http = http or client.session
    ftype, ffile = upload_form()
    t0 = time.monotonic()
    with open(image["path"], "rb") as fh:
        try:
            resp = http.post(f"http://{host}/cgi-bin/file-import", timeout=timeout,
                             data={"sessionid": session_id(client), "size": str(image["size"]),
                                   "filename": f"type={ftype}&file={ffile}"},
                             files={"file": (os.path.basename(image["path"]), fh, "application/octet-stream")})
        except requests.RequestException as exc:
            # Gateway starts flashing and drops the connection: same as the UI's special case.
            if time.monotonic() - t0 > 30:
                return "started (Verbindung waehrend Upgrade getrennt)"
            raise FirmwareError(f"Upload fehlgeschlagen: {type(exc).__name__}") from exc
    if resp.status_code == 401:
        raise FirmwareError("Upload abgelehnt: Session ungueltig")
    if resp.status_code == 404 and time.monotonic() - t0 > 30:
        return "started (404 nach langem Upload, wie im Web-UI)"
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if data.get("size") and data.get("checksum"):
        return f"hochgeladen ({data.get('size')} Bytes, Pruefsumme {data.get('checksum')})"
    raise FirmwareError(f"Upload abgelehnt: HTTP {resp.status_code} {data.get('message') or data.get('templet_code') or ''}")


def upgrade_error(host, http=requests, timeout=8):
    try:
        data = http.get(f"http://{host}/islogin", timeout=timeout).json()
        return ((data.get("result") or [{}])[0] or {}).get("upgrade_error")
    except (requests.RequestException, ValueError, AttributeError, IndexError):
        return None


def wait_reboot(is_up, wait_secs, sleep=time.sleep, interval=10):
    """Wait until the gateway was down once and is up again. Returns (ok, detail)."""
    deadline = time.monotonic() + wait_secs
    went_down = False
    while time.monotonic() < deadline:
        up = is_up()
        if not up:
            went_down = True
        elif went_down:
            return True, "Neustart erkannt, wieder erreichbar"
        sleep(interval)
    return (False, "nicht wieder erreichbar") if went_down else (False, "kein Neustart erkannt")
