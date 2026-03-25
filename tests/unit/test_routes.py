"""Unit tests for server.api.routes module.

Tests cover:
- GET /api/v1/health returns healthy status
- POST /api/v1/analyze with valid image returns judgment result
- POST /api/v1/analyze with missing image returns MISSING_IMAGE error
- POST /api/v1/analyze with invalid format returns INVALID_IMAGE_FORMAT error
- POST /api/v1/analyze with oversized image returns IMAGE_TOO_LARGE error
- POST /api/v1/analyze with LLM failure returns LLM_SERVICE_ERROR error
- POST /api/v1/analyze with LLM timeout returns TIMEOUT status (200)
- POST /api/v1/analyze with custom request_id preserves it
- POST /api/v1/analyze auto-generates request_id when not provided
- processing_time_ms is included in successful responses
- Error response format matches spec
"""

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from server.api.routes import api_bp, init_routes
from server.models import JudgmentStatus, LLMResponse
from server.services.llm_service import LLMService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal valid PNG: 8-byte signature
_VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

# Minimal valid JPEG: starts with FF D8 FF
_VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100


def _create_app(llm_service: LLMService | None = None) -> Flask:
    """Create a minimal Flask app with the API blueprint registered."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api_bp)
    if llm_service is not None:
        init_routes(llm_service)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_llm_service() -> MagicMock:
    """Create a mock LLMService that returns an OK response by default."""
    service = MagicMock(spec=LLMService)
    service.analyze_image.return_value = (
        LLMResponse(
            status=JudgmentStatus.OK,
            reason="All equipment normal.",
            raw_response="{}",
            equipment_data={"S520": {"identified": True}},
        ),
        1234,  # processing_time_ms
    )
    return service


@pytest.fixture()
def client(mock_llm_service: MagicMock):
    """Flask test client with a mocked LLM service."""
    app = _create_app(mock_llm_service)
    with app.test_client() as c:
        yield c


@pytest.fixture()
def client_no_llm():
    """Flask test client without an LLM service (simulates uninitialised state)."""
    # Reset module-level _llm_service to None
    import server.api.routes as routes_mod
    original = routes_mod._llm_service
    routes_mod._llm_service = None
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api_bp)
    with app.test_client() as c:
        yield c
    routes_mod._llm_service = original


# ---------------------------------------------------------------------------
# GET /api/v1/health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    def test_returns_200(self, client) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_returns_healthy_status(self, client) -> None:
        resp = client.get("/api/v1/health")
        data = resp.get_json()
        assert data["status"] == "healthy"

    def test_includes_timestamp(self, client) -> None:
        resp = client.get("/api/v1/health")
        data = resp.get_json()
        assert "timestamp" in data
        assert len(data["timestamp"]) > 0


# ---------------------------------------------------------------------------
# POST /api/v1/analyze — success cases
# ---------------------------------------------------------------------------

class TestAnalyzeSuccess:
    """Tests for successful POST /api/v1/analyze requests."""

    def test_valid_png_returns_200(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200

    def test_valid_jpeg_returns_200(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(_VALID_JPEG_BYTES), "test.jpeg")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200

    def test_response_contains_required_fields(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        assert "request_id" in data
        assert "status" in data
        assert "reason" in data
        assert "timestamp" in data
        assert "processing_time_ms" in data

    def test_processing_time_ms_is_non_negative_int(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        assert isinstance(data["processing_time_ms"], int)
        assert data["processing_time_ms"] >= 0

    def test_equipment_data_included_when_present(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        assert "equipment_data" in data
        assert data["equipment_data"]["S520"]["identified"] is True

    def test_custom_request_id_preserved(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={
                "image": (io.BytesIO(_VALID_PNG_BYTES), "test.png"),
                "request_id": "my_custom_id_001",
            },
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        assert data["request_id"] == "my_custom_id_001"

    def test_auto_generated_request_id_format(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        assert data["request_id"].startswith("req_")


# ---------------------------------------------------------------------------
# POST /api/v1/analyze — error cases
# ---------------------------------------------------------------------------

class TestAnalyzeErrors:
    """Tests for error handling in POST /api/v1/analyze."""

    def test_missing_image_returns_400(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"]["code"] == "MISSING_IMAGE"

    def test_invalid_format_returns_400(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(b"not an image"), "test.bmp")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"]["code"] == "INVALID_IMAGE_FORMAT"

    def test_oversized_image_returns_400(self, client) -> None:
        # Create a PNG that exceeds 20MB
        oversized = _VALID_PNG_BYTES + b"\x00" * (21 * 1024 * 1024)
        resp = client.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(oversized), "big.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"]["code"] == "IMAGE_TOO_LARGE"

    def test_llm_service_not_initialised_returns_500(self, client_no_llm) -> None:
        resp = client_no_llm.post(
            "/api/v1/analyze",
            data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["error"]["code"] == "LLM_SERVICE_ERROR"

    def test_llm_exception_returns_500(self, mock_llm_service: MagicMock) -> None:
        mock_llm_service.analyze_image.side_effect = RuntimeError("LLM connection failed")
        app = _create_app(mock_llm_service)
        with app.test_client() as c:
            resp = c.post(
                "/api/v1/analyze",
                data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["error"]["code"] == "LLM_SERVICE_ERROR"
        assert "LLM connection failed" in data["error"]["message"]

    def test_error_response_format(self, client) -> None:
        """Verify error envelope matches the spec: {error: {code, message, request_id, timestamp}}."""
        resp = client.post(
            "/api/v1/analyze",
            data={},
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        error = data["error"]
        assert "code" in error
        assert "message" in error
        assert "request_id" in error
        assert "timestamp" in error

    def test_error_response_preserves_custom_request_id(self, client) -> None:
        resp = client.post(
            "/api/v1/analyze",
            data={"request_id": "err_req_001"},
            content_type="multipart/form-data",
        )
        data = resp.get_json()
        assert data["error"]["request_id"] == "err_req_001"


# ---------------------------------------------------------------------------
# POST /api/v1/analyze — TIMEOUT case
# ---------------------------------------------------------------------------

class TestAnalyzeTimeout:
    """Tests for TIMEOUT handling in POST /api/v1/analyze."""

    def test_timeout_returns_200_with_timeout_status(self) -> None:
        service = MagicMock(spec=LLMService)
        service.analyze_image.return_value = (
            LLMResponse(
                status=JudgmentStatus.TIMEOUT,
                reason="LLM response timeout (30s exceeded)",
                raw_response="",
            ),
            30000,
        )
        app = _create_app(service)
        with app.test_client() as c:
            resp = c.post(
                "/api/v1/analyze",
                data={"image": (io.BytesIO(_VALID_PNG_BYTES), "test.png")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "TIMEOUT"
        assert data["processing_time_ms"] >= 30000
        assert "timeout" in data["reason"].lower()
