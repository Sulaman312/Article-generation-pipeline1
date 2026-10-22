"""User credentials and session tokens for API login.

When MongoDB is enabled, users and sessions live in the `users` and
`auth_sessions` collections. When MongoDB is disabled (local tests), an
in-memory store is used with the same default admin account.
"""

from __future__ import annotations

import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from backend import config

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_memory_users: dict[str, dict[str, Any]] = {}
_memory_sessions: dict[str, dict[str, Any]] = {}
_seeded = False
_indexes_ready = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session_ttl() -> timedelta:
    days = getattr(config, "AUTH_SESSION_DAYS", 14) or 14
    try:
        days = max(1, int(days))
    except (TypeError, ValueError):
        days = 14
    return timedelta(days=days)


def _default_username() -> str:
    return (getattr(config, "AUTH_DEFAULT_USERNAME", None) or "admin").strip() or "admin"


def _default_password() -> str:
    return (getattr(config, "AUTH_DEFAULT_PASSWORD", None) or "admin123").strip() or "admin123"


def _mongo_collections():
    global _indexes_ready
    from backend import mongo_storage

    if not mongo_storage.enabled():
        return None, None
    db = mongo_storage.get_database()
    users = db["users"]
    sessions = db["auth_sessions"]
    if not _indexes_ready:
        users.create_index("username", unique=True)
        sessions.create_index("token", unique=True)
        sessions.create_index("expires_at", expireAfterSeconds=0)
        _indexes_ready = True
    return users, sessions


def ensure_default_admin(*, force_reset: bool = False) -> None:
    """Create the default admin user if missing (password stored hashed)."""
    global _seeded
    username = _default_username()
    password = _default_password()
    password_hash = generate_password_hash(password)

    with _LOCK:
        users_col, _ = _mongo_collections()
        if users_col is not None:
            existing = users_col.find_one({"username": username})
            if existing and not force_reset:
                _seeded = True
                return
            doc = {
                "username": username,
                "password_hash": password_hash,
                "role": "admin",
                "updated_at": _utcnow(),
            }
            if existing:
                users_col.update_one(
                    {"username": username},
                    {"$set": doc},
                )
                logger.info("Reset password for MongoDB user %r", username)
            else:
                doc["created_at"] = _utcnow()
                users_col.insert_one(doc)
                logger.info("Seeded MongoDB admin user %r", username)
            _seeded = True
            return

        if username in _memory_users and not force_reset:
            _seeded = True
            return
        _memory_users[username] = {
            "username": username,
            "password_hash": password_hash,
            "role": "admin",
            "created_at": _utcnow(),
        }
        logger.info("Seeded in-memory admin user %r", username)
        _seeded = True


def ensure_ready() -> None:
    """Ensure auth store is initialized (admin seeded)."""
    if _seeded:
        return
    try:
        ensure_default_admin()
    except Exception:
        logger.exception("Failed to seed default admin user")
        raise


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    ensure_ready()
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        return None

    with _LOCK:
        users_col, _ = _mongo_collections()
        if users_col is not None:
            doc = users_col.find_one({"username": username})
        else:
            doc = _memory_users.get(username)

        if not doc:
            return None
        if not check_password_hash(str(doc.get("password_hash") or ""), password):
            return None
        return {
            "username": str(doc["username"]),
            "role": str(doc.get("role") or "user"),
        }


def create_session(username: str) -> str:
    ensure_ready()
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    expires = now + _session_ttl()
    row = {
        "token": token,
        "username": username,
        "created_at": now,
        "expires_at": expires,
    }
    with _LOCK:
        _, sessions_col = _mongo_collections()
        if sessions_col is not None:
            sessions_col.insert_one(row)
        else:
            _memory_sessions[token] = row
    return token


def resolve_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    token = token.strip()
    if not token:
        return None

    ensure_ready()
    now = _utcnow()
    with _LOCK:
        _, sessions_col = _mongo_collections()
        if sessions_col is not None:
            doc = sessions_col.find_one({"token": token})
            if not doc:
                return None
            expires = doc.get("expires_at")
            if isinstance(expires, datetime):
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires < now:
                    sessions_col.delete_one({"token": token})
                    return None
            return {
                "username": str(doc.get("username") or ""),
                "token": token,
            }

        doc = _memory_sessions.get(token)
        if not doc:
            return None
        expires = doc.get("expires_at")
        if isinstance(expires, datetime) and expires < now:
            _memory_sessions.pop(token, None)
            return None
        return {
            "username": str(doc.get("username") or ""),
            "token": token,
        }


def revoke_session(token: str | None) -> None:
    if not token:
        return
    token = token.strip()
    with _LOCK:
        _, sessions_col = _mongo_collections()
        if sessions_col is not None:
            sessions_col.delete_one({"token": token})
        else:
            _memory_sessions.pop(token, None)


def reset_memory_store_for_tests() -> None:
    """Clear in-memory auth state (unit tests only)."""
    global _seeded, _indexes_ready
    with _LOCK:
        _memory_users.clear()
        _memory_sessions.clear()
        _seeded = False
        _indexes_ready = False
