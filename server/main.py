"""Entry point for the AI Alarm System server.

Loads configuration, creates the Flask app, registers routes,
ensures data directories exist, and starts the server using
waitress (production) or Flask built-in server (development).

Usage:
    python -m server.main          # Production (waitress)
    python -m server.main --dev    # Development (Flask debug server)

Environment variable override:
    FLASK_ENV=development          # Same as --dev flag
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from flask import Flask

from server.api.routes import api_bp, init_routes
from server.config import ConfigError, load_config
from server.logger import JudgmentLogger, ResultStorage
from server.services.email_notifier import EmailNotifier
from server.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Create and configure the Flask application.

    Returns:
        Configured Flask app with registered blueprints.

    Raises:
        ConfigError: If configuration loading or validation fails.
    """
    config = load_config()

    app = Flask(__name__)

    # Create LLM service and inject into routes
    llm_service = LLMService(app_config=config)

    # Create storage and logger
    result_storage = ResultStorage(
        results_dir=config.storage.results_dir,
        unknown_images_dir=config.storage.unknown_images_dir,
    )
    judgment_logger = JudgmentLogger(logs_dir=config.storage.logs_dir)

    # Create SNS notifier for UNKNOWN status alerts
    email_notifier = EmailNotifier(config=config.sns)

    init_routes(llm_service, result_storage, judgment_logger, email_notifier)

    # Register API blueprint
    app.register_blueprint(api_bp)

    # Ensure data directories exist
    for dir_path in (
        config.storage.results_dir,
        config.storage.logs_dir,
        config.storage.unknown_images_dir,
    ):
        Path(dir_path).mkdir(parents=True, exist_ok=True)

    # Store config on app for potential later access
    app.config["APP_CONFIG"] = config

    return app


def main() -> None:
    """Parse arguments and start the server."""
    parser = argparse.ArgumentParser(description="AI Alarm System Server")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in development mode with Flask built-in server",
    )
    args = parser.parse_args()

    dev_mode = args.dev or os.getenv("FLASK_ENV", "").lower() == "development"

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if dev_mode else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        app = create_app()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    config = app.config["APP_CONFIG"]
    host = config.server.host
    port = config.server.port

    if dev_mode:
        print(f"Starting development server at http://{host}:{port}")
        app.run(host=host, port=port, debug=True)
    else:
        print(f"Starting production server at http://{host}:{port}")
        import waitress
        waitress.serve(app, host=host, port=port)


if __name__ == "__main__":
    main()
