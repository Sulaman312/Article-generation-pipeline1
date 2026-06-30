"""Run ``python -m backend`` from the repository root."""

from backend.app import create_app


def main() -> None:
    create_app().run(host="0.0.0.0", port=8000, debug=True)


if __name__ == "__main__":
    main()
