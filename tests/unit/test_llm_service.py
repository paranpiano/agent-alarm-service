"""Unit tests for server.services.llm_service module.

Tests cover:
- _build_prompt() includes all judgment criteria from PromptConfig
- _parse_response() handles valid JSON correctly
- _parse_response() handles invalid JSON (returns UNKNOWN)
- _parse_response() handles markdown-fenced JSON
- analyze_image() constructs correct HumanMessage structure
"""

import base64
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.config import AppConfig, EmailSettings, PromptConfig, ServerSettings, SnsSettings, StorageSettings
from server.models import JudgmentStatus, LLMResponse
from server.services.llm_service import LLMService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def prompt_config() -> PromptConfig:
    """Create a PromptConfig with realistic judgment criteria."""
    return PromptConfig(
        system_prompt="You are an AI expert analyzing HMI panel images.",
        equipment_definitions={
            "S520": {
                "name": "S520 - Preheating & Curing",
                "ng_condition": "Any quantity >= 3000 is NG",
            },
            "S540": {
                "name": "S540 - Robot",
                "ng_condition": "Red or black background color is NG",
            },
        },
        judgment_criteria={
            "step1_identification": "Identify 4 panels. If not all found, UNKNOWN.",
            "step2_data_extraction": "Extract data from each equipment.",
            "step3_judgment": (
                "[NG conditions]\n"
                "- S520, S530, S810: quantity >= 3000 is NG\n"
                "- S540: red or black background is NG\n"
                "[OK conditions]\n"
                "- No NG conditions and all data extracted\n"
                "[UNKNOWN conditions]\n"
                "- Any equipment not identified\n"
                "- Required data not fully extracted"
            ),
        },
        response_format={
            "type": "json",
            "schema": '{"status": "OK | NG | UNKNOWN", "reason": "..."}',
        },
    )


@pytest.fixture()
def app_config(prompt_config: PromptConfig) -> AppConfig:
    """Create a minimal AppConfig for testing."""
    return AppConfig(
        prompt=prompt_config,
        server=ServerSettings(host="0.0.0.0", port=8000, llm_timeout_seconds=30),
        email=EmailSettings(),
        sns=SnsSettings(),
        storage=StorageSettings(),
        azure_endpoint="https://test.openai.azure.com/",
        azure_api_key="test-key-123",
        api_version="2024-12-01-preview",
        chat_model="gpt-4o",
        vision_model="gpt-4o",
    )


@pytest.fixture()
def llm_service(app_config: AppConfig) -> LLMService:
    """Create an LLMService with a mocked AzureChatOpenAI client."""
    with patch("server.services.llm_service.get_azure_vision_llm") as mock_factory:
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm
        service = LLMService(app_config)
    return service


# ---------------------------------------------------------------------------
# _build_prompt() tests
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    """Tests for LLMService._build_prompt()."""

    def test_includes_system_prompt(self, llm_service: LLMService) -> None:
        prompt = llm_service._build_prompt()
        assert "You are an AI expert analyzing HMI panel images." in prompt

    def test_includes_equipment_definitions(self, llm_service: LLMService) -> None:
        prompt = llm_service._build_prompt()
        assert "S520 - Preheating & Curing" in prompt
        assert "S540 - Robot" in prompt

    def test_includes_all_judgment_criteria_steps(self, llm_service: LLMService) -> None:
        prompt = llm_service._build_prompt()
        assert "step1_identification" in prompt
        assert "step2_data_extraction" in prompt
        assert "step3_judgment" in prompt

    def test_includes_ng_conditions(self, llm_service: LLMService) -> None:
        prompt = llm_service._build_prompt()
        assert "NG conditions" in prompt
        assert "quantity >= 3000 is NG" in prompt
        assert "red or black background is NG" in prompt

    def test_includes_ok_conditions(self, llm_service: LLMService) -> None:
        prompt = llm_service._build_prompt()
        assert "OK conditions" in prompt
        assert "No NG conditions and all data extracted" in prompt

    def test_includes_unknown_conditions(self, llm_service: LLMService) -> None:
        prompt = llm_service._build_prompt()
        assert "UNKNOWN conditions" in prompt
        assert "Any equipment not identified" in prompt

    def test_includes_response_format(self, llm_service: LLMService) -> None:
        prompt = llm_service._build_prompt()
        assert "Response Format" in prompt
        assert "json" in prompt


# ---------------------------------------------------------------------------
# _parse_response() tests
# ---------------------------------------------------------------------------

class TestParseResponse:
    """Tests for LLMService._parse_response()."""

    def test_valid_ok_json(self, llm_service: LLMService) -> None:
        raw = json.dumps({
            "status": "OK",
            "reason": "All equipment normal.",
            "equipment_data": {"S520": {"identified": True}},
        })
        result = llm_service._parse_response(raw)
        assert isinstance(result, LLMResponse)
        assert result.status == JudgmentStatus.OK
        assert result.reason == "All equipment normal."
        assert result.equipment_data is not None
        assert result.equipment_data["S520"]["identified"] is True

    def test_valid_ng_json(self, llm_service: LLMService) -> None:
        raw = json.dumps({
            "status": "NG",
            "reason": "S520 Curing Oven 1#=3017 (>= 3000)",
            "equipment_data": {"S520": {"ng_items": ["1#: 3017"]}},
        })
        result = llm_service._parse_response(raw)
        assert result.status == JudgmentStatus.NG
        assert "3017" in result.reason

    def test_valid_unknown_json(self, llm_service: LLMService) -> None:
        raw = json.dumps({
            "status": "UNKNOWN",
            "reason": "Could not identify all 4 panels.",
        })
        result = llm_service._parse_response(raw)
        assert result.status == JudgmentStatus.UNKNOWN
        assert result.equipment_data is None

    def test_invalid_json_returns_unknown(self, llm_service: LLMService) -> None:
        raw = "This is not valid JSON at all!"
        result = llm_service._parse_response(raw)
        assert result.status == JudgmentStatus.UNKNOWN
        assert "Failed to parse" in result.reason
        assert result.raw_response == raw

    def test_empty_string_returns_unknown(self, llm_service: LLMService) -> None:
        result = llm_service._parse_response("")
        assert result.status == JudgmentStatus.UNKNOWN

    def test_markdown_fenced_json(self, llm_service: LLMService) -> None:
        raw = '```json\n{"status": "OK", "reason": "Normal."}\n```'
        result = llm_service._parse_response(raw)
        assert result.status == JudgmentStatus.OK
        assert result.reason == "Normal."

    def test_invalid_status_value_defaults_to_unknown(self, llm_service: LLMService) -> None:
        raw = json.dumps({"status": "INVALID_STATUS", "reason": "test"})
        result = llm_service._parse_response(raw)
        assert result.status == JudgmentStatus.UNKNOWN

    def test_missing_status_defaults_to_unknown(self, llm_service: LLMService) -> None:
        raw = json.dumps({"reason": "no status field"})
        result = llm_service._parse_response(raw)
        assert result.status == JudgmentStatus.UNKNOWN

    def test_raw_response_preserved(self, llm_service: LLMService) -> None:
        raw = json.dumps({"status": "OK", "reason": "Fine."})
        result = llm_service._parse_response(raw)
        assert result.raw_response == raw


# ---------------------------------------------------------------------------
# analyze_image() tests
# ---------------------------------------------------------------------------

class TestAnalyzeImage:
    """Tests for LLMService.analyze_image()."""

    def test_constructs_correct_human_message(self, llm_service: LLMService) -> None:
        """Verify that analyze_image builds a HumanMessage with text + image_url."""
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        expected_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "status": "OK",
            "reason": "All normal.",
        })
        llm_service.llm.predict_messages = MagicMock(return_value=mock_response)

        result, elapsed_ms = llm_service.analyze_image(image_bytes, "png")

        # Verify predict_messages was called once
        llm_service.llm.predict_messages.assert_called_once()

        # Get the messages argument
        call_args = llm_service.llm.predict_messages.call_args
        messages = call_args[0][0]

        # Should be a list with one HumanMessage
        assert len(messages) == 1
        msg = messages[0]

        # Content should be a list with text and image_url parts
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2

        # First part: text prompt
        text_part = msg.content[0]
        assert text_part["type"] == "text"
        assert "You are an AI expert" in text_part["text"]

        # Second part: image_url with base64 data
        image_part = msg.content[1]
        assert image_part["type"] == "image_url"
        assert image_part["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"

    def test_returns_llm_response_and_elapsed_time(self, llm_service: LLMService) -> None:
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "status": "NG",
            "reason": "S520 value exceeded threshold.",
        })
        llm_service.llm.predict_messages = MagicMock(return_value=mock_response)

        result, elapsed_ms = llm_service.analyze_image(b"\xff\xd8\xff\xe0", "jpeg")

        assert isinstance(result, LLMResponse)
        assert result.status == JudgmentStatus.NG
        assert elapsed_ms >= 0

    def test_jpeg_mime_type(self, llm_service: LLMService) -> None:
        """Verify JPEG images use the correct MIME type."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({"status": "OK", "reason": "Fine."})
        llm_service.llm.predict_messages = MagicMock(return_value=mock_response)

        llm_service.analyze_image(b"\xff\xd8\xff\xe0", "jpeg")

        call_args = llm_service.llm.predict_messages.call_args
        messages = call_args[0][0]
        image_part = messages[0].content[1]
        assert "data:image/jpeg;base64," in image_part["image_url"]["url"]

    def test_timeout_returns_timeout_status(self, llm_service: LLMService) -> None:
        """Verify TimeoutError produces TIMEOUT status."""
        llm_service.llm.predict_messages = MagicMock(side_effect=TimeoutError("timed out"))

        result, elapsed_ms = llm_service.analyze_image(b"\x00" * 10, "png")

        assert result.status == JudgmentStatus.TIMEOUT
        assert "timeout" in result.reason.lower()
