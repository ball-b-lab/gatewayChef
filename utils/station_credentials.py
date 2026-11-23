"""
Webservice login entered on the station page.

The operator can store their own Webservice (ws1) user and password on the station; setup runs
then use those instead of WEBSERVICE_USER/WEBSERVICE_PASSWORD from the env file. Without a stored
login the env values apply. Stored as JSON, mode 600, owned by the service user (the web UI and
the setup runs in the port namespaces both run as `gatewaychef` with HOME=/opt/gatewaychef).
The password is never sent back to the browser.
"""
import json
import os
import tempfile


def path():
    return os.getenv("STATION_CREDENTIALS_FILE") or os.path.join(
        os.path.expanduser("~"), "station-credentials.json")


def load():
    """{"webservice_user": ..., "webservice_password": ...} or {} when nothing is stored."""
    try:
        with open(path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not data.get("webservice_user") or not data.get("webservice_password"):
        return {}
    return {"webservice_user": str(data["webservice_user"]), "webservice_password": str(data["webservice_password"])}


def save(user, password):
    user, password = (user or "").strip(), password or ""
    if not user or not password:
        raise ValueError("Benutzer und Passwort angeben")
    if len(user) > 200 or len(password) > 200 or "\n" in user or "\n" in password:
        raise ValueError("Benutzer oder Passwort ungueltig")
    target = path()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target) or ".", prefix=".cred-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"webservice_user": user, "webservice_password": password}, fh)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def clear():
    try:
        os.unlink(path())
    except FileNotFoundError:
        pass


def webservice_login():
    """(user, password, source): stored station login first, else the env file."""
    stored = load()
    if stored:
        return stored["webservice_user"], stored["webservice_password"], "station"
    return os.getenv("WEBSERVICE_USER", ""), os.getenv("WEBSERVICE_PASSWORD", ""), "env"


def status():
    """For the page: which login applies, user name only."""
    user, password, source = webservice_login()
    return {"source": source if user and password else "none", "user": user or None}
