from functools import wraps

from flask import g, request

from services.auth_service import AuthError, decode_access_token


def _extract_bearer_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AuthError("Authorization Bearer Token fehlt.", 401)
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise AuthError("Authorization Bearer Token fehlt.", 401)
    return token


def require_auth(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        payload = decode_access_token(token)
        g.auth_user = {
            "id": int(payload["sub"]),
            "email": payload.get("email"),
            "role": payload.get("role", "user"),
        }
        return handler(*args, **kwargs)

    return wrapper
