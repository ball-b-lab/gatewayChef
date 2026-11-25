"""
Follow the gateway's WLAN when the setup renames it (WLAN mode of the Windows app).

The setup writes our SSID (bbdbmon_<x.y>) and key into the gateway. Its access point
restarts under the new name and the PC drops off. On Windows we add a WLAN profile for
the new name with netsh and connect; elsewhere we ask the user to switch by hand.
Either way we then wait until the gateway answers again on its LAN address.
"""
import os
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape

import requests

_PROFILE = """<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{name}</name>
  <SSIDConfig><SSID><name>{name}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM><security>
    <authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption>
    <sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{key}</keyMaterial></sharedKey>
  </security></MSM>
</WLANProfile>
"""


def _netsh(*args, run=subprocess.run):
    out = run(["netsh", "wlan", *args], capture_output=True, text=True, timeout=30,
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out.returncode == 0, (out.stdout or out.stderr or "").strip()[-200:]


def connect_windows(ssid, key, run=subprocess.run):
    """Add (or replace) a WLAN profile for ssid/key and connect. -> (ok, detail)."""
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_PROFILE.format(name=escape(ssid), key=escape(key)))
        ok, out = _netsh("add", "profile", f"filename={path}", "user=current", run=run)
        if not ok:
            return False, f"WLAN-Profil nicht angelegt: {out}"
    finally:
        try:
            os.remove(path)   # contains the WLAN key
        except OSError:
            pass
    return _netsh("connect", f"name={ssid}", f"ssid={ssid}", run=run)


def answers(host, http=requests):
    for scheme in ("https", "http"):
        try:
            http.get(f"{scheme}://{host}/", timeout=3, verify=False)
            return True
        except requests.RequestException:
            continue
    return False


def follow(ssid, key, host, say=print, wait_secs=180, sleep=time.sleep, run=subprocess.run,
           is_windows=None, http=requests):
    """After the gateway renamed its WLAN: switch this PC over and wait for the gateway. -> (ok, detail)."""
    is_windows = sys.platform.startswith("win") if is_windows is None else is_windows
    sleep(8)   # access point restarts under the new name
    deadline = time.monotonic() + wait_secs
    tries = 0
    while time.monotonic() < deadline:
        if is_windows:
            tries += 1
            ok, out = connect_windows(ssid, key, run=run)
            say(f"verbinde PC mit WLAN {ssid} ... ({'ok' if ok else out[:80]})")
        else:
            say(f"bitte diesen Rechner mit WLAN {ssid} verbinden (Schluessel wie im Profil)")
        for _ in range(6):
            if answers(host, http=http):
                return True, f"PC jetzt im WLAN {ssid}, Gateway antwortet"
            sleep(5)
    return False, f"Gateway nach WLAN-Wechsel nicht erreichbar: PC bitte mit {ssid} verbinden und neu starten"
