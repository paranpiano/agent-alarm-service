"""Unit tests for server.config module.

Tests cover:
- Loading and validating prompt_config.yaml
- Loading and validating server_config.yaml
- Loading .env environment variables
- Error handling for missing/malformed config files
"""

import os
from pathlib import Path

import pytest
import yaml

from server.config import (
    AppConfig,
    ConfigError,
    PromptConfig,
    ServerSettings,
    StorageSettings,
    load_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def valid_prompt_config(tmp_path: Path) -> Path:
    """Create a minimal valid prompt_config.yaml."""
    data = {
        "system_prompt": "You are an AI expert.",
        "equipment_definitions": {"S520": {"name": "S520"}},
        "judgment_criteria": {"step1": "Identify panels."},
        "response_format": {"type": "json", "schema": "{}"},
    }
    filepath = tmp_path / "prompt_config.yaml"
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)
    return filepath


@pytest.fixture()
def valid_server_config(tmp_path: Path) -> Path:
    """Create a minimal valid server_config.yaml."""
    data = {
        "server": {"host": "127.0.0.1", "port": 9000, "llm_timeout_seconds": 15},
        "email": {"smtp_host": "mail.example.com", "smtp_port": 465},
        "storage": {"results_dir": "out/results"},
    }
    filepath = tmp_path / "server_config.yaml"
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)
    return filepath


@pytest.fixture()
def env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required Azure environment variables."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key-123")
    monkeypatch.setenv("API_VERSION", "2024-12-01-preview")
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o")
    monkeypatch.setenv("VISION_MODEL", "gpt-4o")


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestLoadConfigSuccess:
    """Tests for successful config loading."""

    def test_load_full_config(
        self,
        valid_prompt_config: Path,
        valid_server_config: Path,
        env_vars: None,
    ) -> None:
        cfg = load_config(
            prompt_config_path=valid_prompt_config,
            server_config_path=valid_server_config,
        )
        assert isinstance(cfg, AppConfig)
        assert isinstance(cfg.prompt, PromptConfig)
        assert cfg.prompt.system_prompt == "You are an AI expert."
        assert "S520" in cfg.prompt.equipment_definitions

    def test_server_settings_parsed(
        self,
        valid_prompt_config: Path,
        valid_server_config: Path,
        env_vars: None,
    ) -> None:
        cfg = load_config(
            prompt_config_path=valid_prompt_config,
            server_config_path=valid_server_config,
        )
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 9000
        assert cfg.server.llm_timeout_seconds == 15

    def test_env_vars_loaded(
        self,
        valid_prompt_config: Path,
        valid_server_config: Path,
        env_vars: None,
    ) -> None:
        cfg = load_config(
            prompt_config_path=valid_prompt_config,
            server_config_path=valid_server_config,
        )
        assert cfg.azure_endpoint == "https://test.openai.azure.com/"
        assert cfg.azure_api_key == "test-key-123"
        assert cfg.api_version == "2024-12-01-preview"

    def test_defaults_applied_for_missing_optional_sections(
        self,
        valid_prompt_config: Path,
        tmp_path: Path,
        env_vars: None,
    ) -> None:
        """server_config.yaml with only 'server' section still works."""
        minimal = tmp_path / "server_config.yaml"
        with open(minimal, "w", encoding="utf-8") as f:
            yaml.dump({"server": {"port": 7777}}, f)

        cfg = load_config(
            prompt_config_path=valid_prompt_config,
            server_config_path=minimal,
        )
        assert cfg.server.port == 7777
        # Defaults for email and storage
        assert cfg.email.smtp_port == 587
        assert cfg.storage.results_dir == "data/results"


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------

class TestLoadConfigErrors:
    """Tests for config validation failures."""

    def test_missing_prompt_config_file(
        self,
        valid_server_config: Path,
        env_vars: None,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(ConfigError, match="not found"):
            load_config(
                prompt_config_path=missing,
                server_config_path=valid_server_config,
            )

    def test_missing_server_config_file(
        self,
        valid_prompt_config: Path,
        env_vars: None,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(ConfigError, match="not found"):
            load_config(
                prompt_config_path=valid_prompt_config,
                server_config_path=missing,
            )

    def test_malformed_yaml(
        self,
        valid_server_config: Path,
        env_vars: None,
        tmp_path: Path,
    ) -> None:
        bad_yaml = tmp_path / "bad.yaml"
        with open(bad_yaml, "w", encoding="utf-8") as f:
            f.write("{{invalid yaml content::")
        with pytest.raises(ConfigError, match="malformed YAML"):
            load_config(
                prompt_config_path=bad_yaml,
                server_config_path=valid_server_config,
            )

    def test_prompt_config_missing_required_keys(
        self,
        valid_server_config: Path,
        env_vars: None,
        tmp_path: Path,
    ) -> None:
        incomplete = tmp_path / "prompt.yaml"
        with open(incomplete, "w", encoding="utf-8") as f:
            yaml.dump({"system_prompt": "hello"}, f)
        with pytest.raises(ConfigError, match="missing required keys"):
            load_config(
                prompt_config_path=incomplete,
                server_config_path=valid_server_config,
            )

    def test_yaml_not_a_mapping(
        self,
        valid_server_config: Path,
        env_vars: None,
        tmp_path: Path,
    ) -> None:
        list_yaml = tmp_path / "list.yaml"
        with open(list_yaml, "w", encoding="utf-8") as f:
            yaml.dump(["a", "b", "c"], f)
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_config(
                prompt_config_path=list_yaml,
                server_config_path=valid_server_config,
            )

    def test_missing_env_var_endpoint(
        self,
        valid_prompt_config: Path,
        valid_server_config: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        with pytest.raises(ConfigError, match="AZURE_OPENAI_ENDPOINT"):
            load_config(
                prompt_config_path=valid_prompt_config,
                server_config_path=valid_server_config,
            )

    def test_missing_env_var_api_key(
        self,
        valid_prompt_config: Path,
        valid_server_config: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x.openai.azure.com/")
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="AZURE_OPENAI_API_KEY"):
            load_config(
                prompt_config_path=valid_prompt_config,
                server_config_path=valid_server_config,
            )
