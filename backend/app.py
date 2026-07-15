"""Flask application factory."""

import logging
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS

from backend import auth_store, mongo_storage
from backend.api.routes import api_bp
from backend.logging_config import configure_logging, register_request_logging

logger = logging.getLogger(__name__)

_PUBLIC_EXACT = {"/health", "/ready", "/auth/login", "/"}
_PUBLIC_PREFIXES = ("/static/", "/assets/")
# Client-side app routes must return index.html without API auth; React logs in itself.
_SPA_SHELL_PREFIXES = ("/w/",)
_ASSET_SUFFIXES = (
    ".js",
    ".css",
    ".map",
    ".ico",
    ".png",
    ".svg",
    ".jpg",
    ".jpeg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".txt",
    ".json",
)


def _request_can_change_workspace() -> bool:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        return True
    if request.method != "GET":
        return False
    # Legacy GET that may still write template images on first read.
    return request.path.endswith("/images/template")


def _is_spa_shell_path(path: str) -> bool:
    """Browser document routes for the React app (not JSON API endpoints)."""
    if path == "/":
        return True
    return any(path.startswith(prefix) for prefix in _SPA_SHELL_PREFIXES)


def _is_public_path(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    if path in _PUBLIC_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
        return True
    if method in {"GET", "HEAD"} and _is_spa_shell_path(path):
        return True
    if method in {"GET", "HEAD"} and path.endswith(_ASSET_SUFFIXES):
        return True
    return False


def _extract_token() -> str | None:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    query = request.args.get("token")
    if query:
        return str(query).strip() or None
    return None


def create_app() -> Flask:
    configure_logging(level=logging.INFO)
    logger.info("ContentFlow backend starting")
    mongo_storage.initialize_runtime_cache_background()
    if not mongo_storage.enabled():
        try:
            auth_store.ensure_default_admin()
        except Exception:
            logger.exception("Failed to seed in-memory admin user")

    ui_build_dir = Path(__file__).resolve().parent.parent / "atlas-ui" / "build"
    # Vite emits hashed bundles under build/assets/; SPA files served below.
    app = Flask(
        __name__,
        static_folder=str(ui_build_dir / "assets"),
        static_url_path="/assets",
    )
    # Dev UI on :3000 calling API on :8000 — Authorization bearer works with "*".
    CORS(
        app,
        resources={
            r"/*": {
                "origins": "*",
                "methods": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": ["Authorization", "Content-Type", "Accept"],
                "expose_headers": ["X-Request-ID"],
            }
        },
    )
    register_request_logging(app)
    app.register_blueprint(api_bp)

    @app.before_request
    def require_hydrated_workspace():
        if mongo_storage.runtime_ready():
            return None
        path = request.path or "/"
        if path in {"/", "/health", "/ready", "/auth/login"} or path.startswith(
            ("/static/", "/assets/")
        ):
            return None
        # Always allow the SPA shell so deep links (e.g. /w/Client/overview) load HTML.
        if request.method in {"GET", "HEAD"} and _is_spa_shell_path(path):
            return None
        if path.startswith("/auth/"):
            return None
        status = mongo_storage.startup_status()
        return (
            jsonify(
                ok=False,
                detail="Waiting for MongoDB hydration to complete.",
                hydration=status,
            ),
            503,
        )

    @app.before_request
    def require_login():
        path = request.path or "/"
        if _is_public_path(path, request.method):
            return None

        token = _extract_token()
        session = auth_store.resolve_session(token)
        if not session or not session.get("username"):
            return jsonify(detail="Authentication required. Please log in."), 401

        g.auth_user = {
            "username": session["username"],
            "role": "admin" if session["username"] == "admin" else "user",
            "token": session.get("token"),
        }
        return None

    @app.after_request
    def persist_workspace_mutations(response):
        if not mongo_storage.enabled() or not _request_can_change_workspace():
            return response
        if not mongo_storage.runtime_ready():
            return response
        try:
            mongo_storage.sync_cache(delete_missing=True)
        except Exception:
            logger.exception(
                "MongoDB persistence failed after %s %s",
                request.method,
                request.path,
            )
            if response.status_code < 400:
                return jsonify(
                    detail=(
                        "The operation completed locally but could not be persisted "
                        "to MongoDB. Check the service logs."
                    )
                ), 503
        return response

    @app.get("/")
    def serve_ui_root():
        if (ui_build_dir / "index.html").is_file():
            return send_from_directory(ui_build_dir, "index.html")
        return {
            "ok": True,
            "service": "ContentFlow API",
            "ui": "Run `cd atlas-ui && npm start` in development.",
            "health": "/health",
            "clients": "/clients",
            "auth": "/auth/login",
        }

    @app.get("/<path:path>")
    def serve_ui_path(path: str):
        target = ui_build_dir / path
        if target.is_file():
            return send_from_directory(ui_build_dir, path)
        if (ui_build_dir / "index.html").is_file():
            return send_from_directory(ui_build_dir, "index.html")
        return {"error": "Not found"}, 404

    return app
