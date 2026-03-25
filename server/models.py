"""Shared data models for the AI Alarm System.

Defines core data structures used across server components:
- JudgmentStatus: Enum for analysis result states
- JudgmentResult: Main result dataclass with serialization support
- ValidationResult: Image validation outcome
- LLMResponse: Raw LLM analysis response
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class JudgmentStatus(str, Enum):
    """Status of an image analysis judgment."""

    OK = "OK"
    NG = "NG"
    UNKNOWN = "UNKNOWN"
    TIMEOUT = "TIMEOUT"


@dataclass
class JudgmentResult:
    """Result of an image analysis judgment.

    Attributes:
        request_id: Unique identifier for the analysis request.
        status: Judgment status (OK, NG, UNKNOWN, TIMEOUT).
        reason: Human-readable explanation of the judgment.
        timestamp: ISO 8601 formatted timestamp.
        processing_time_ms: Processing time in milliseconds.
        image_name: Name of the analyzed image file.
        equipment_data: Optional dict with per-equipment analysis details.
    """

    request_id: str
    status: JudgmentStatus
    reason: str
    timestamp: str  # ISO 8601 format
    processing_time_ms: int = 0
    image_name: str = ""
    equipment_data: Optional[dict[str, Any]] = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        result: dict[str, Any] = {
            "request_id": self.request_id,
            "status": self.status.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "processing_time_ms": self.processing_time_ms,
            "image_name": self.image_name,
        }
        if self.equipment_data is not None:
            result["equipment_data"] = self.equipment_data
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JudgmentResult":
        """Deserialize from a plain dictionary."""
        return cls(
            request_id=data["request_id"],
            status=JudgmentStatus(data["status"]),
            reason=data["reason"],
            timestamp=data["timestamp"],
            processing_time_ms=data.get("processing_time_ms", 0),
            image_name=data.get("image_name", ""),
            equipment_data=data.get("equipment_data"),
        )


@dataclass
class ValidationResult:
    """Result of image validation.

    Attributes:
        is_valid: Whether the image passed validation.
        error_message: Description of the validation failure (empty if valid).
    """

    is_valid: bool
    error_message: str = ""


@dataclass
class LLMResponse:
    """Parsed response from the LLM service.

    Attributes:
        status: Judgment status derived from LLM output.
        reason: Explanation text from the LLM.
        raw_response: Original unparsed LLM response string.
        equipment_data: Optional per-equipment detail dict from LLM JSON.
    """

    status: JudgmentStatus
    reason: str
    raw_response: str = ""
    equipment_data: Optional[dict[str, Any]] = field(default=None)
