import hmac

from flask import request

from config import API_SERVICE_TOKEN
from utils.response import error


def enforce_api_token():
    """
    Enforce X-API-Token when API_SERVICE_TOKEN is configured.
    Return Flask response on failure, otherwise None.
    """
    expected = API_SERVICE_TOKEN or ""
    if not expected:
        return None

    provided = request.headers.get("X-API-Token", "")
    if not provided:
        return error("Unauthorized.", 401)

    if not hmac.compare_digest(provided, expected):
        return error("Unauthorized.", 401)

    return None
