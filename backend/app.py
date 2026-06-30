"""Flask application factory."""

import logging
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.api.routes import api_bp
from backend.logging_config import configure_logging, register_request_logging
from backend import mongo_storage

logger = logging.getLogger(__name__)

def _request_can_change_workspace() -> bool:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        return True
    if request.method != "GET":
        return False
    # These legacy GET handlers may repair/cache an artifact on first read.
    return (
        "/artifacts/" in request.path
        or request.path.endswith("/images/template")
    )


def create_app() -> Flask:
    configure_logging(level=logging.INFO)
    logger.info("ContentFlow backend starting")
    mongo_storage.initialize_runtime_cache()

    ui_build_dir = Path(__file__).resolve().parent.parent / "atlas-ui" / "build"
    app = Flask(
        __name__,
        static_folder=str(ui_build_dir / "static"),
        static_url_path="/static",
    )
    # Match prior FastAPI behavior: allow browser dev servers on any port (:3000, :3001, …).
    CORS(
        app,
        resources={
            r"/*": {
                "origins": "*",
                "methods": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": "*",
            }
        },
    )
    register_request_logging(app)
    app.register_blueprint(api_bp)

    @app.after_request
    def persist_workspace_mutations(response):
        if not mongo_storage.enabled() or not _request_can_change_workspace():
            return response
        try:
            mongo_storage.sync_cache()
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
