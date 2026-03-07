from flask import jsonify


def ok(data=None, *, trace_id=None, status=200):
    payload = {"ok": True, "data": data}
    if trace_id:
        payload["trace_id"] = trace_id
    return jsonify(payload), status


def fail(exc, *, trace_id=None):
    payload = {
        "ok": False,
        "error": {
            "message": exc.message,
            "code": exc.code,
            "details": exc.details,
            "retryable": exc.retryable,
        },
    }
    if exc.stage:
        payload["error"]["stage"] = exc.stage
    if trace_id:
        payload["trace_id"] = trace_id
    return jsonify(payload), exc.status_code
