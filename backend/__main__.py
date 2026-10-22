"""Run ``python -m backend`` from the repository root."""

import os

from backend.app import create_app


def main() -> None:
    debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in ("1", "true", "yes")
    port = int(os.getenv("API_PORT") or os.getenv("FLASK_RUN_PORT") or "8000")
    create_app().run(
        host=os.getenv("API_HOST") or "0.0.0.0",
        port=port,
        debug=debug,
        threaded=True,
    )


if __name__ == "__main__":
    main()
