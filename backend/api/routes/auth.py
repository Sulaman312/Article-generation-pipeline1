"""Login / logout / current-user API."""

from __future__ import annotations

from flask import g, jsonify, request

from backend import auth_store
from backend.api.blueprint import api_bp


@api_bp.post("/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return jsonify(detail="Username and password are required."), 400

    try:
        user = auth_store.authenticate(username, password)
    except Exception:
        return jsonify(detail="Authentication service unavailable."), 503

    if not user:
        return jsonify(detail="Invalid username or password."), 401

    token = auth_store.create_session(user["username"])
    return jsonify(
        token=token,
        username=user["username"],
        role=user.get("role") or "user",
    )


@api_bp.post("/auth/logout")
def logout():
    token = _bearer_or_query_token()
    auth_store.revoke_session(token)
    return "", 204


@api_bp.get("/auth/me")
def me():
    user = getattr(g, "auth_user", None)
    if not user:
        return jsonify(detail="Not authenticated."), 401
    return jsonify(username=user["username"], role=user.get("role") or "user")


def _bearer_or_query_token() -> str | None:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    query = request.args.get("token")
    if query:
        return str(query).strip() or None
    return None
