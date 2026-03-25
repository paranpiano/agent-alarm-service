"""LLM Service module for the AI Alarm System.

Provides Azure OpenAI Vision API integration via LangChain AzureChatOpenAI.
Handles image analysis with base64 encoding, prompt construction from
PromptConfig, JSON response parsing, and timeout management.
"""

import base64
import json
import logging
import time
from typing import Any

import yaml
from langchain.schema import HumanMessage
from langchain_openai import AzureChatOpenAI

from server.config import AppConfig, PromptConfig
from server.models import JudgmentStatus, LLMResponse

logger = logging.getLogger(__name__)


def get_azure_vision_llm(config: AppConfig) -> AzureChatOpenAI:
    """Factory function to create an AzureChatOpenAI client.

    Args:
        config: Application configuration containing Azure credentials.

    Returns:
        Configured AzureChatOpenAI instance for vision tasks.
    """
    return AzureChatOpenAI(
        azure_endpoint=config.azure_endpoint,
        api_key=config.azure_api_key,
        api_version=config.api_version,
        azure_deployment=config.vision_model,
        timeout=config.server.llm_timeout_seconds,
    )


class LLMService:
    """Service for analyzing HMI panel images using Azure OpenAI Vision API.

    Attributes:
        config: Prompt configuration for building analysis prompts.
        timeout_seconds: Maximum seconds to wait for LLM response.
        llm: AzureChatOpenAI client instance.
    """

    def __init__(self, app_config: AppConfig) -> None:
        """Initialize LLMService with application configuration.

        Args:
            app_config: Application configuration containing prompt settings,
                Azure credentials, and timeout configuration.
        """
        self.config: PromptConfig = app_config.prompt
        self.timeout_seconds: int = app_config.server.llm_timeout_seconds
        self.llm: AzureChatOpenAI = get_azure_vision_llm(app_config)

    def analyze_image(self, image_bytes: bytes, image_format: str) -> tuple[LLMResponse, int]:
        """Analyze an HMI panel image using Azure OpenAI Vision API.

        Encodes the image as base64, constructs a LangChain HumanMessage with
        multimodal content (text prompt + image), and calls the LLM.

        Args:
            image_bytes: Raw image bytes.
            image_format: Image format string (e.g. "png", "jpeg").

        Returns:
            Tuple of (LLMResponse, processing_time_ms).
            On timeout, returns LLMResponse with status=TIMEOUT.
        """
        start_time = time.monotonic()

        # 1. Base64 encode the image
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = f"image/{image_format}"

        # 2. Build prompt and construct LangChain HumanMessage
        prompt_text = self._build_prompt()
        messages = [
            HumanMessage(content=[
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                },
            ])
        ]

        try:
            # 3. Call LLM with timeout
            response = self.llm.predict_messages(messages)
            answer = response.content
            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            # 4. Parse JSON response into LLMResponse
            return self._parse_response(answer), elapsed_ms

        except (TimeoutError, Exception) as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            if elapsed_ms >= self.timeout_seconds * 1000 or isinstance(exc, TimeoutError):
                logger.warning("LLM call timed out after %d ms", elapsed_ms)
                return LLMResponse(
                    status=JudgmentStatus.TIMEOUT,
                    reason=f"LLM response timeout ({self.timeout_seconds}s exceeded)",
                    raw_response="",
                ), elapsed_ms
            logger.error("LLM call failed: %s", exc)
            raise

    def _build_prompt(self) -> str:
        """Build the analysis prompt from PromptConfig.

        Combines system_prompt, equipment_definitions, judgment_criteria,
        and response_format into a single prompt string. Includes ALL
        judgment conditions (OK/NG/Unknown) from the config.

        Returns:
            Complete prompt string for the LLM.
        """
        parts: list[str] = []

        # System prompt
        parts.append(self.config.system_prompt.strip())
        parts.append("")

        # Equipment definitions
        parts.append("=== Equipment Definitions ===")
        equipment_str = yaml.dump(
            self.config.equipment_definitions,
            allow_unicode=True,
            default_flow_style=False,
        )
        parts.append(equipment_str.strip())
        parts.append("")

        # Judgment criteria (includes OK/NG/Unknown conditions)
        parts.append("=== Judgment Criteria ===")
        for step_name, step_content in self.config.judgment_criteria.items():
            parts.append(f"[{step_name}]")
            parts.append(str(step_content).strip())
            parts.append("")

        # Response format
        parts.append("=== Response Format ===")
        response_format_str = yaml.dump(
            self.config.response_format,
            allow_unicode=True,
            default_flow_style=False,
        )
        parts.append(response_format_str.strip())

        return "\n".join(parts)

    def _parse_response(self, raw_response: str) -> LLMResponse:
        """Parse LLM response string into an LLMResponse object.

        Attempts to extract JSON from the response. If the response contains
        markdown code fences, strips them first. On parse failure, returns
        LLMResponse with status=UNKNOWN.

        Args:
            raw_response: Raw string response from the LLM.

        Returns:
            Parsed LLMResponse with status, reason, and equipment_data.
        """
        cleaned = raw_response.strip()

        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json or ```) and last line (```)
            if len(lines) >= 2:
                start_idx = 1
                end_idx = len(lines)
                if lines[-1].strip() == "```":
                    end_idx = -1
                cleaned = "\n".join(lines[start_idx:end_idx]).strip()

        try:
            data: dict[str, Any] = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to parse LLM response as JSON: %s", exc)
            return LLMResponse(
                status=JudgmentStatus.UNKNOWN,
                reason=f"Failed to parse LLM response: {exc}",
                raw_response=raw_response,
            )

        # Extract status
        raw_status = str(data.get("status", "UNKNOWN")).upper().strip()
        try:
            status = JudgmentStatus(raw_status)
        except ValueError:
            status = JudgmentStatus.UNKNOWN

        reason = str(data.get("reason", ""))
        equipment_data = data.get("equipment_data")

        return LLMResponse(
            status=status,
            reason=reason,
            raw_response=raw_response,
            equipment_data=equipment_data,
        )
