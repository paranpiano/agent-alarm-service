"""Unit tests for server.main module.

Tests cover:
- create_app() returns a Flask app with the API blueprint registered
- create_app() creates data directories from config
- create_app() raises ConfigError on invalid config
- main() exits with code 1 on ConfigError
- main() starts dev server when --dev flag is passed
- main() starts waitress in production mode
- FLASK_ENV=development triggers dev mode
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from server.config import ConfigError


# ---------------------------------------------------------------------------
# create_app tests
# ---------------------------------------------------------------------------

class TestCreateApp:
    """Tests for the create_app() factory function."""

    @patch("server.main.LLMService")
    @patch("server.main.load_config")
    def test_returns_flask_app(self, mock_load_config, mock_llm_cls, tmp_path) -> None:
        config = self._make_config(tmp_path)
        mock_load_config.return_value = config
        mock_llm_cls.return_value = MagicMock()

        from server.main import create_app
        app = create_app()

        assert isinstance(app, Flask)

    @patch("server.main.LLMService")
    @patch("server.main.load_config")
    def test_registers_api_blueprint(self, mock_load_config, mock_llm_cls, tmp_path) -> None:
        config = self._make_config(tmp_path)
        mock_load_config.return_value = config
        mock_llm_cls.return_value = MagicMock()

        from server.main import create_app
        app = create_app()

        # The api blueprint should be registered with url_prefix /api/v1
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        assert "/api/v1/health" in rules

    @patch("server.main.LLMService")
    @patch("server.main.load_config")
    def test_creates_data_directories(self, mock_load_config, mock_llm_cls, tmp_path) -> None:
        config = self._make_config(tmp_path)
        mock_load_config.return_value = config
        mock_llm_cls.return_value = MagicMock()

        from server.main import create_app
        create_app()

        assert (tmp_path / "results").is_dir()
        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "unknown_images").is_dir()

    @patch("server.main.load_config")
    def test_raises_config_error(self, mock_load_config) -> None:
        mock_load_config.side_effect = ConfigError("bad config")

        from server.main import create_app
        with pytest.raises(ConfigError, match="bad config"):
            create_app()

    @patch("server.main.LLMService")
    @patch("server.main.load_config")
    def test_injects_llm_service_into_routes(self, mock_load_config, mock_llm_cls, tmp_path) -> None:
        config = self._make_config(tmp_path)
        mock_load_config.return_value = config
        mock_service = MagicMock()
        mock_llm_cls.return_value = mock_service

        from server.main import create_app
        with patch("server.main.init_routes") as mock_init_routes:
            create_app()
            # init_routes is called with llm_service + storage + logger
            mock_init_routes.assert_called_once()
            call_args = mock_init_routes.call_args
            assert call_args[0][0] is mock_service

    # Helper
    @staticmethod
    def _make_config(tmp_path: Path):
        """Build a minimal AppConfig-like mock with storage paths under tmp_path."""
        from server.config import ServerSettings, EmailSettings, StorageSettings, PromptConfig

        config = MagicMock()
        config.server = ServerSettings(host="127.0.0.1", port=8000, llm_timeout_seconds=30)
        config.storage = StorageSettings(
            results_dir=str(tmp_path / "results"),
            logs_dir=str(tmp_path / "logs"),
            unknown_images_dir=str(tmp_path / "unknown_images"),
        )
        return config


# ---------------------------------------------------------------------------
# main() tests
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for the main() entry point function."""

    @patch("server.main.create_app")
    def test_config_error_exits_with_code_1(self, mock_create_app) -> None:
        mock_create_app.side_effect = ConfigError("missing .env")

        from server.main import main
        with patch("sys.argv", ["main.py"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("server.main.create_app")
    def test_dev_flag_uses_flask_run(self, mock_create_app) -> None:
        app = MagicMock()
        app.config = {"APP_CONFIG": MagicMock()}
        app.config["APP_CONFIG"].server.host = "0.0.0.0"
        app.config["APP_CONFIG"].server.port = 8000
        mock_create_app.return_value = app

        from server.main import main
        with patch("sys.argv", ["main.py", "--dev"]):
            main()

        app.run.assert_called_once_with(host="0.0.0.0", port=8000, debug=True)

    @patch("waitress.serve")
    @patch("server.main.create_app")
    def test_production_uses_waitress(self, mock_create_app, mock_waitress_serve) -> None:
        app = MagicMock()
        app.config = {"APP_CONFIG": MagicMock()}
        app.config["APP_CONFIG"].server.host = "0.0.0.0"
        app.config["APP_CONFIG"].server.port = 8000
        mock_create_app.return_value = app

        from server.main import main
        with patch("sys.argv", ["main.py"]):
            with patch.dict("os.environ", {"FLASK_ENV": ""}, clear=False):
                main()

        mock_waitress_serve.assert_called_once_with(app, host="0.0.0.0", port=8000)

    @patch("server.main.create_app")
    def test_flask_env_development_triggers_dev_mode(self, mock_create_app) -> None:
        app = MagicMock()
        app.config = {"APP_CONFIG": MagicMock()}
        app.config["APP_CONFIG"].server.host = "0.0.0.0"
        app.config["APP_CONFIG"].server.port = 8000
        mock_create_app.return_value = app

        from server.main import main
        with patch("sys.argv", ["main.py"]):
            with patch.dict("os.environ", {"FLASK_ENV": "development"}, clear=False):
                main()

        app.run.assert_called_once_with(host="0.0.0.0", port=8000, debug=True)
