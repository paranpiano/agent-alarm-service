"""Unit tests for the EmailNotifier module (SNS API version).

Tests cover:
- Successful SNS API call
- Subject and message body contain required fields
- Retry logic on request failures
- Skips when SNS not configured
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from server.config import SnsSettings
from server.models import JudgmentResult, JudgmentStatus
from server.services.email_notifier import EmailNotifier


@pytest.fixture
def sns_config() -> SnsSettings:
    return SnsSettings(
        api_url="https://example.execute-api.eu-central-1.amazonaws.com/prod",
        topic_arn="arn:aws:sns:eu-central-1:123456789:TestTopic",
        protocol="email",
    )


@pytest.fixture
def unknown_judgment() -> JudgmentResult:
    return JudgmentResult(
        request_id="req_20240101_001",
        status=JudgmentStatus.UNKNOWN,
        reason="4 equipment panels could not be identified",
        timestamp="2024-01-01T12:00:00Z",
        processing_time_ms=1500,
        image_name="test.png",
    )


@pytest.fixture
def notifier(sns_config: SnsSettings) -> EmailNotifier:
    return EmailNotifier(sns_config)


class TestBuildSubjectAndMessage:
    def test_subject_contains_request_id(self, notifier, unknown_judgment):
        subject = notifier._build_subject(unknown_judgment)
        assert "req_20240101_001" in subject

    def test_message_contains_required_fields(self, notifier, unknown_judgment):
        msg = notifier._build_message(unknown_judgment)
        assert "req_20240101_001" in msg
        assert "2024-01-01T12:00:00Z" in msg
        assert "4 equipment panels could not be identified" in msg


class TestSendAlert:
    @patch("server.services.email_notifier.requests.post")
    def test_success_returns_true(self, mock_post, notifier, unknown_judgment):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messageId": "abc123"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        assert notifier.send_alert(unknown_judgment) is True
        mock_post.assert_called_once()

    @patch("server.services.email_notifier.requests.post")
    def test_sends_correct_payload(self, mock_post, notifier, unknown_judgment):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messageId": "abc123"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        notifier.send_alert(unknown_judgment)

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["topicArn"] == "arn:aws:sns:eu-central-1:123456789:TestTopic"
        assert payload["protocol"] == "email"
        assert "req_20240101_001" in payload["subject"]

    @patch("server.services.email_notifier.requests.post")
    def test_retry_3_times_on_failure(self, mock_post, notifier, unknown_judgment):
        mock_post.side_effect = requests.ConnectionError("failed")

        result = notifier.send_alert(unknown_judgment)

        assert result is False
        assert mock_post.call_count == 3

    @patch("server.services.email_notifier.requests.post")
    def test_retry_succeeds_on_second_attempt(self, mock_post, notifier, unknown_judgment):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messageId": "abc123"}
        mock_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [requests.ConnectionError("temp"), mock_resp]

        assert notifier.send_alert(unknown_judgment) is True
        assert mock_post.call_count == 2

    def test_skips_when_not_configured(self, unknown_judgment):
        empty_config = SnsSettings(api_url="", topic_arn="", protocol="email")
        notifier = EmailNotifier(empty_config)

        assert notifier.send_alert(unknown_judgment) is False
