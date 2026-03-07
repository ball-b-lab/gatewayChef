from flask import jsonify


def ok(data=None):
    return jsonify({"ok": True, "data": data})


def error(message, status=400, code=None, data=None):
    payload = {"message": message}
    if code:
        payload["code"] = code
    return jsonify({"ok": False, "data": data, "error": payload}), status
