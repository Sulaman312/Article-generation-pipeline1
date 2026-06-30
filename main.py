"""Launch the HTTP API from the repository root (Flask).

Usage::
    python main.py

Equivalent (from repository root)::

    flask --app backend.app:create_app run --host 0.0.0.0 --port 8000 --debug
"""

from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parent
_repo_str = str(_REPO_ROOT)
if _repo_str not in sys.path:
    sys.path.insert(0, _repo_str)

from backend.app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    import os

    # Windows: debug reloader often hangs browser requests on :8000. Set FLASK_RELOAD=1 to enable.
    use_reloader = os.getenv("FLASK_RELOAD", "").strip() in ("1", "true", "yes")
    port = int(os.getenv("API_PORT") or os.getenv("FLASK_RUN_PORT") or "8000")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=True,
        use_reloader=use_reloader,
        threaded=True,
    )
