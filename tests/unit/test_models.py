"""Unit tests for server.models data structures."""

import pytest

from server.models import (
    JudgmentResult,
    JudgmentStatus,
    LLMResponse,
    ValidationResult,
)


class TestJudgmentStatus:
    """Tests for JudgmentStatus enum."""

    def test_all_values_exist(self):
        assert JudgmentStatus.OK == "OK"
        assert JudgmentStatus.NG == "NG"
        assert JudgmentStatus.UNKNOWN == "UNKNOWN"
        assert JudgmentStatus.TIMEOUT == "TIMEOUT"

    def test_is_str_subclass(self):
        assert isinstance(JudgmentStatus.OK, str)

    def test_from_string(self):
        assert JudgmentStatus("OK") is JudgmentStatus.OK
        assert JudgmentStatus("TIMEOUT") is JudgmentStatus.TIMEOUT

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            JudgmentStatus("INVALID")


class TestJudgmentResult:
    """Tests for JudgmentResult dataclass."""

    def _make_result(self, **overrides):
        defaults = {
            "request_id": "req_001",
            "status": JudgmentStatus.OK,
            "reason": "All equipment normal",
            "timestamp": "2024-01-01T12:00:00Z",
        }
        defaults.update(overrides)
        return JudgmentResult(**defaults)

    def test_defaults(self):
        r = self._make_result()
        assert r.processing_time_ms == 0
        assert r.image_name == ""
        assert r.equipment_data is None

    def test_to_dict_without_equipment_data(self):
        r = self._make_result(processing_time_ms=150)
        d = r.to_dict()
        assert d == {
            "request_id": "req_001",
            "status": "OK",
            "reason": "All equipment normal",
            "timestamp": "2024-01-01T12:00:00Z",
            "processing_time_ms": 150,
            "image_name": "",
        }
        assert "equipment_data" not in d

    def test_to_dict_with_equipment_data(self):
        eq = {"S520": {"identified": True}}
        r = self._make_result(equipment_data=eq)
        d = r.to_dict()
        assert d["equipment_data"] == eq

    def test_from_dict_minimal(self):
        data = {
            "request_id": "req_002",
            "status": "NG",
            "reason": "S520 value exceeded",
            "timestamp": "2024-06-01T00:00:00Z",
        }
        r = JudgmentResult.from_dict(data)
        assert r.status is JudgmentStatus.NG
        assert r.processing_time_ms == 0
        assert r.image_name == ""
        assert r.equipment_data is None

    def test_from_dict_full(self):
        eq = {"S540": {"identified": True, "stations": {}}}
        data = {
            "request_id": "req_003",
            "status": "UNKNOWN",
            "reason": "Cannot identify panels",
            "timestamp": "2024-06-01T01:00:00Z",
            "processing_time_ms": 2500,
            "image_name": "panel.png",
            "equipment_data": eq,
        }
        r = JudgmentResult.from_dict(data)
        assert r.processing_time_ms == 2500
        assert r.image_name == "panel.png"
        assert r.equipment_data == eq

    def test_roundtrip(self):
        eq = {"S810": {"identified": False}}
        original = self._make_result(
            status=JudgmentStatus.TIMEOUT,
            processing_time_ms=30000,
            image_name="test.png",
            equipment_data=eq,
        )
        restored = JudgmentResult.from_dict(original.to_dict())
        assert restored == original

    def test_roundtrip_without_equipment_data(self):
        original = self._make_result(processing_time_ms=500)
        restored = JudgmentResult.from_dict(original.to_dict())
        assert restored == original


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid(self):
        v = ValidationResult(is_valid=True)
        assert v.is_valid is True
        assert v.error_message == ""

    def test_invalid(self):
        v = ValidationResult(is_valid=False, error_message="Unsupported format")
        assert v.is_valid is False
        assert v.error_message == "Unsupported format"


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_defaults(self):
        r = LLMResponse(status=JudgmentStatus.OK, reason="Normal")
        assert r.raw_response == ""
        assert r.equipment_data is None

    def test_with_all_fields(self):
        eq = {"S520": {"identified": True}}
        r = LLMResponse(
            status=JudgmentStatus.NG,
            reason="Threshold exceeded",
            raw_response='{"status":"NG"}',
            equipment_data=eq,
        )
        assert r.status is JudgmentStatus.NG
        assert r.equipment_data == eq
