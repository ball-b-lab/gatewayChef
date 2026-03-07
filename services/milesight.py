import requests
from config import MILESIGHT_URL, MILESIGHT_CLIENT_ID, MILESIGHT_CLIENT_SECRET, MILESIGHT_TOKEN_URL


def get_milesight_missing():
    missing = []
    if not MILESIGHT_URL:
        missing.append("MILESIGHT_URL")
    if not MILESIGHT_CLIENT_ID:
        missing.append("MILESIGHT_CLIENT_ID")
    if not MILESIGHT_CLIENT_SECRET:
        missing.append("MILESIGHT_CLIENT_SECRET")
    if not (MILESIGHT_TOKEN_URL or MILESIGHT_URL):
        missing.append("MILESIGHT_TOKEN_URL")
    return missing


def milesight_token_url():
    if MILESIGHT_TOKEN_URL:
        return MILESIGHT_TOKEN_URL
    return f"{MILESIGHT_URL}/oauth/token"


def milesight_get_token():
    url = milesight_token_url()
    data = {
        "grant_type": "client_credentials",
        "client_id": MILESIGHT_CLIENT_ID,
        "client_secret": MILESIGHT_CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = requests.post(url, data=data, headers=headers, timeout=8)
    if resp.status_code != 200:
        raise RuntimeError(f"Token Error {resp.status_code}")

    payload = resp.json()
    data = payload.get("data", {})
    token = (
        data.get("access_token")
        or data.get("token")
        or payload.get("access_token")
        or payload.get("token")
    )
    if not token:
        raise RuntimeError("Token missing in response")
    return token
