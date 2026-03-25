"""Configuration loading module for the AI Alarm System server.

Loads and validates:
- prompt_config.yaml: LLM prompt settings and judgment criteria
- server_config.yaml: Server, client, email, and storage settings
- .env: Azure OpenAI credentials via python-dotenv

Aborts server startup if any required config is missing or malformed.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


# Directory containing this file (server/)
_SERVER_DIR = Path(__file__).resolve().parent

# Required top-level keys in prompt_config.yaml
_REQUIRED_PROMPT_KEYS = [
    "system_prompt",
    "equipment_definitions",
    "judgment_criteria",
    "response_format",
]

# Required environment variables for Azure OpenAI
_REQUIRED_ENV_VARS = [
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
]


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


@dataclass
class ServerSettings:
    """Server runtime settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    llm_timeout_seconds: int = 30


@dataclass
class EmailSettings:
    """Email notification settings."""

    smtp_host: str = ""
    smtp_port: int = 587
    sender: str = ""
    password: str = ""
    recipients: list[str] = field(default_factory=list)


@dataclass
class StorageSettings:
    """File storage path settings."""

    results_dir: str = "data/results"
    logs_dir: str = "data/logs"
    unknown_images_dir: str = "data/unknown_images"


@dataclass
class PromptConfig:
    """Prompt configuration loaded from prompt_config.yaml."""

    system_prompt: str
    equipment_definitions: dict[str, Any]
    judgment_criteria: dict[str, Any]
    response_format: dict[str, Any]


@dataclass
class AppConfig:
    """Top-level application configuration aggregating all settings."""

    prompt: PromptConfig
    server: ServerSettings
    email: EmailSettings
    storage: StorageSettings
    azure_endpoint: str
    azure_api_key: str
    api_version: str
    chat_model: str
    vision_model: str


def _load_yaml(filepath: Path, description: str) -> dict[str, Any]:
    """Load and parse a YAML file, raising ConfigError on failure."""
    if not filepath.is_file():
        raise ConfigError(f"{description} not found: {filepath}")
    try:
        with open(filepath, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{description} is malformed YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"{description} must be a YAML mapping, got {type(data).__name__}")
    return data


def _load_prompt_config(filepath: Path) -> PromptConfig:
    """Load and validate prompt_config.yaml."""
    data = _load_yaml(filepath, "Prompt config")

    missing = [k for k in _REQUIRED_PROMPT_KEYS if k not in data]
    if missing:
        raise ConfigError(f"Prompt config missing required keys: {', '.join(missing)}")

    return PromptConfig(
        system_prompt=data["system_prompt"],
        equipment_definitions=data["equipment_definitions"],
        judgment_criteria=data["judgment_criteria"],
        response_format=data["response_format"],
    )


def _load_server_config(filepath: Path) -> tuple[ServerSettings, EmailSettings, StorageSettings]:
    """Load and validate server_config.yaml."""
    data = _load_yaml(filepath, "Server config")

    srv = data.get("server", {})
    server_settings = ServerSettings(
        host=str(srv.get("host", "0.0.0.0")),
        port=int(srv.get("port", 8000)),
        llm_timeout_seconds=int(srv.get("llm_timeout_seconds", 30)),
    )

    em = data.get("email", {})
    email_settings = EmailSettings(
        smtp_host=str(em.get("smtp_host", "")),
        smtp_port=int(em.get("smtp_port", 587)),
        sender=str(em.get("sender", "")),
        password=str(em.get("password", "")),
        recipients=list(em.get("recipients", [])),
    )

    st = data.get("storage", {})
    storage_settings = StorageSettings(
        results_dir=str(st.get("results_dir", "data/results")),
        logs_dir=str(st.get("logs_dir", "data/logs")),
        unknown_images_dir=str(st.get("unknown_images_dir", "data/unknown_images")),
    )

    return server_settings, email_settings, storage_settings


def _load_env_vars() -> tuple[str, str, str, str, str]:
    """Load and validate required environment variables.

    Returns:
        Tuple of (endpoint, api_key, api_version, chat_model, vision_model).
    """
    load_dotenv(dotenv_path=_SERVER_DIR / ".env")

    missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        raise ConfigError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    api_version = os.getenv("API_VERSION", "2024-12-01-preview")
    chat_model = os.getenv("CHAT_MODEL", "gpt-4o-korea-rag")
    vision_model = os.getenv("VISION_MODEL", chat_model)

    return endpoint, api_key, api_version, chat_model, vision_model


def load_config(
    prompt_config_path: Path | None = None,
    server_config_path: Path | None = None,
) -> AppConfig:
    """Load all configuration and return an AppConfig instance.

    Args:
        prompt_config_path: Override path for prompt_config.yaml.
        server_config_path: Override path for server_config.yaml.

    Returns:
        Fully validated AppConfig.

    Raises:
        ConfigError: If any config file is missing, malformed, or
            required environment variables are not set.
    """
    if prompt_config_path is None:
        prompt_config_path = _SERVER_DIR / "prompt_config.yaml"
    if server_config_path is None:
        server_config_path = _SERVER_DIR / "server_config.yaml"

    prompt = _load_prompt_config(prompt_config_path)
    server_settings, email_settings, storage_settings = _load_server_config(server_config_path)
    endpoint, api_key, api_version, chat_model, vision_model = _load_env_vars()

    return AppConfig(
        prompt=prompt,
        server=server_settings,
        email=email_settings,
        storage=storage_settings,
        azure_endpoint=endpoint,
        azure_api_key=api_key,
        api_version=api_version,
        chat_model=chat_model,
        vision_model=vision_model,
    )
