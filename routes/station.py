"""
Setup station page and API: one column per port, plus the job board with
running and finished jobs (setup runs and fleet updates).
"""
from flask import Blueprint, render_template, request

from services import station as st
from utils import station_credentials as creds
from utils.response import error, ok

bp = Blueprint("station", __name__)
_station = None


def station():
    global _station
    if _station is None:
        _station = st.Station()
    return _station


@bp.route("/station")
def station_page():
    return render_template("station.html")


@bp.route("/api/station/overview", methods=["GET"])
def station_overview():
    return ok({"ports": station().overview(), "jobs": [j.as_dict() for j in station().board.all()]})


@bp.route("/api/station/run", methods=["POST"])
def station_run():
    data = request.json or {}
    try:
        job = station().start_setup(data.get("port"), str(data.get("mode") or "dry"), data.get("options") or {})
    except (st.StationError, TypeError, ValueError) as exc:
        return error(str(exc), 400)
    return ok(job.as_dict())


@bp.route("/api/station/job/<int:job_id>", methods=["GET"])
def station_job(job_id):
    job = station().board.get(job_id)
    if not job:
        return error("Vorgang nicht gefunden.", 404)
    return ok(job.as_dict(with_log=True))


@bp.route("/api/station/credentials", methods=["GET"])
def station_credentials_status():
    return ok(creds.status())


@bp.route("/api/station/credentials", methods=["POST"])
def station_credentials_save():
    data = request.json or {}
    try:
        creds.save(data.get("webservice_user"), data.get("webservice_password"))
    except (ValueError, OSError) as exc:
        return error(str(exc), 400)
    return ok(creds.status())


@bp.route("/api/station/credentials", methods=["DELETE"])
def station_credentials_clear():
    creds.clear()
    return ok(creds.status())
