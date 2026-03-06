import psycopg2
from flask import Blueprint, g, request

from auth.jwt_auth import require_auth
from db.connection import get_db_connection
from repositories.user_repository import UserRepository
from services.auth_service import (
    AuthError,
    create_access_token,
    hash_password,
    validate_login_payload,
    validate_registration_payload,
    verify_password,
)
from utils.response import error, ok

bp = Blueprint("auth", __name__)


def _serialize_user(user):
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user.get("full_name"),
        "role": user["role"],
    }


@bp.route("/api/auth/register", methods=["POST"])
def register():
    conn = None
    try:
        data = request.json or {}
        email, password, full_name = validate_registration_payload(data)

        conn = get_db_connection()
        repo = UserRepository(conn)

        existing = repo.get_by_email(email)
        if existing:
            return error("E-Mail bereits registriert.", 409)

        user = repo.create(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role="user",
        )
        conn.commit()

        token = create_access_token(user)
        return ok({"token": token, "user": _serialize_user(user)})
    except AuthError as exc:
        if conn:
            conn.rollback()
        return error(exc.message, exc.status_code)
    except psycopg2.Error as exc:
        if conn:
            conn.rollback()
        return error(f"Datenbank Fehler: {exc}", 500)
    finally:
        if conn:
            conn.close()


@bp.route("/api/auth/login", methods=["POST"])
def login():
    conn = None
    try:
        data = request.json or {}
        email, password = validate_login_payload(data)

        conn = get_db_connection()
        repo = UserRepository(conn)
        user = repo.get_by_email(email)
        if not user or not verify_password(password, user["password_hash"]):
            return error("Ungueltige Anmeldedaten.", 401)

        token = create_access_token(user)
        return ok({"token": token, "user": _serialize_user(user)})
    except AuthError as exc:
        return error(exc.message, exc.status_code)
    except psycopg2.Error as exc:
        return error(f"Datenbank Fehler: {exc}", 500)
    finally:
        if conn:
            conn.close()


@bp.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    conn = None
    try:
        conn = get_db_connection()
        repo = UserRepository(conn)
        user = repo.get_by_id(g.auth_user["id"])
        if not user:
            return error("Benutzer nicht gefunden.", 404)
        return ok(_serialize_user(user))
    except psycopg2.Error as exc:
        return error(f"Datenbank Fehler: {exc}", 500)
    finally:
        if conn:
            conn.close()
