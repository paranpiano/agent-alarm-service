"""Client data models for the AI Alarm System.

Re-exports shared models from server.models so that client code can
import from ``client.models`` without depending on server internals.
"""

from server.models import (  # noqa: F401
    JudgmentResult,
    JudgmentStatus,
    LLMResponse,
    ValidationResult,
)
