"""Unit tests for client.api_client module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from client.api_client import AlarmApiClient, _generate_request_id
from server.models import JudgmentStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Return an AlarmApiClient pointed at a fake server."""
    return AlarmApiClient(base_url="http://localhost:8000", request_timeout=5.0)


@pytest.fixture
def ok_response_json():
    """Sample OK analysis response payload."""
    return {
        "request_id": "req_20240101_120000_0001",
        "status": "OK",
        "reason": "All equipment normal.",
        "timestamp": "2024-01-01T12:00:00Z",
        "processing_time_ms": 1500,
        "image_name": "test.png",
    }


@pytest.fixture
def tmp_image(tmp_path):
    """Create a tiny temporary PNG file and return its path."""
    img = tmp_path / "test.png"
    # Minimal valid PNG header (not a real image, but enough for the client)
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return img


# ---------------------------------------------------------------------------
# _generate_request_id
# ---------------------------------------------------------------------------

class TestGenerateRequestId:
    def test_format(self):
        rid = _generate_request_id()
        assert rid.startswith("req_")
        parts = rid.split("_")
        # req, YYYYMMDD, HHMMSS, XXXX
        assert len(parts) == 4
        assert len(parts[1]) == 8  # date
        assert len(parts[2]) == 6  # time
        assert len(parts[3]) == 4  # random suffix

    def test_uniqueness(self):
        ids = {_generate_request_id() for _ in range(50)}
        # With 10000 possible suffixes, 50 calls should be unique
        assert len(ids) == 50


# ---------------------------------------------------------------------------
# AlarmApiClient.__init__
# ---------------------------------------------------------------------------

class TestAlarmApiClientInit:
    def test_default_timeout(self):
        c = AlarmApiClient(base_url="http://localhost:8000")
        assert c.request_timeout == 35.0

    def test_custom_timeout(self):
        c = AlarmApiClient(base_url="http://localhost:8000", request_timeout=10.0)
        assert c.request_timeout == 10.0

    def test_trailing_slash_stripped(self):
        c = AlarmApiClient(base_url="http://localhost:8000/")
        assert c.base_url == "http://localhost:8000"


# ---------------------------------------------------------------------------
# AlarmApiClient.analyze_single
# ---------------------------------------------------------------------------

class TestAnalyzeSingle:
    @patch("client.api_client.requests.post")
    def test_success(self, mock_post, client, ok_response_json, tmp_image):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ok_response_json
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = client.analyze_single(tmp_image)

        assert result.status == JudgmentStatus.OK
        assert result.reason == "All equipment normal."
        assert result.processing_time_ms == 1500

        # Verify the POST was called with correct URL
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8000/api/v1/analyze"
        # Verify timeout was passed
        assert call_args[1]["timeout"] == 5.0

    @patch("client.api_client.requests.post")
    def test_sends_request_id(self, mock_post, client, ok_response_json, tmp_image):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ok_response_json
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client.analyze_single(tmp_image)

        call_args = mock_post.call_args
        data = call_args[1]["data"]
        assert "request_id" in data
        assert data["request_id"].startswith("req_")

    @patch("client.api_client.requests.post")
    def test_sends_multipart_form_data(self, mock_post, client, ok_response_json, tmp_image):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ok_response_json
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client.analyze_single(tmp_image)

        call_args = mock_post.call_args
        files = call_args[1]["files"]
        assert "image" in files
        filename, content = files["image"]
        assert filename == "test.png"
        assert isinstance(content, bytes)

    def test_file_not_found(self, client):
        with pytest.raises(FileNotFoundError):
            client.analyze_single(Path("/nonexistent/image.png"))

    @patch("client.api_client.requests.post")
    def test_connection_error(self, mock_post, client, tmp_image):
        mock_post.side_effect = requests.ConnectionError("refused")

        with pytest.raises(requests.ConnectionError):
            client.analyze_single(tmp_image)
        # Should have retried 3 times
        assert mock_post.call_count == 3

    @patch("client.api_client.requests.post")
    def test_timeout_error(self, mock_post, client, tmp_image):
        mock_post.side_effect = requests.Timeout("timed out")

        with pytest.raises(requests.Timeout):
            client.analyze_single(tmp_image)
        # Should have retried 3 times
        assert mock_post.call_count == 3

    @patch("client.api_client.requests.post")
    def test_retry_succeeds_on_second_attempt(self, mock_post, client, ok_response_json, tmp_image):
        """First attempt fails, second succeeds."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ok_response_json
        mock_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [
            requests.ConnectionError("refused"),
            mock_resp,
        ]

        result = client.analyze_single(tmp_image)
        assert result.status == JudgmentStatus.OK
        assert mock_post.call_count == 2

    @patch("client.api_client.requests.post")
    def test_invalid_json_response(self, mock_post, client, tmp_image):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"unexpected": "data"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with pytest.raises(ValueError, match="Invalid server response"):
            client.analyze_single(tmp_image)

    @patch("client.api_client.requests.post")
    def test_timeout_status_response(self, mock_post, client, tmp_image):
        """Server returns a TIMEOUT judgment (HTTP 200 with TIMEOUT status)."""
        timeout_json = {
            "request_id": "req_20240101_120030_0002",
            "status": "TIMEOUT",
            "reason": "LLM response timeout (exceeded 30s)",
            "timestamp": "2024-01-01T12:00:30Z",
            "processing_time_ms": 30000,
            "image_name": "test.png",
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = timeout_json
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = client.analyze_single(tmp_image)

        assert result.status == JudgmentStatus.TIMEOUT
        assert result.processing_time_ms == 30000


# ---------------------------------------------------------------------------
# AlarmApiClient.health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    @patch("client.api_client.requests.get")
    def test_healthy(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        assert client.health_check() is True
        mock_get.assert_called_once_with(
            "http://localhost:8000/api/v1/health",
            timeout=5.0,
        )

    @patch("client.api_client.requests.get")
    def test_unhealthy_status(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_get.return_value = mock_resp

        assert client.health_check() is False

    @patch("client.api_client.requests.get")
    def test_connection_error_returns_false(self, mock_get, client):
        mock_get.side_effect = requests.ConnectionError("refused")

        assert client.health_check() is False

    @patch("client.api_client.requests.get")
    def test_timeout_returns_false(self, mock_get, client):
        mock_get.side_effect = requests.Timeout("timed out")

        assert client.health_check() is False
