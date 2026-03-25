"""Unit tests for the EmailNotifier module.

Tests cover:
- Successful email sending
- Email body contains required fields (reason, timestamp, request_id)
- Subject line format
- Retry logic on SMTP failures
- Return value after all retries exhausted
"""

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from server.config import EmailSettings
from server.models import JudgmentResult, JudgmentStatus
from server.services.email_notifier import EmailNotifier


@pytest.fixture
def email_config() -> EmailSettings:
    return EmailSettings(
        smtp_host="smtp.example.com",
        smtp_port=587,
        sender="sender@example.com",
        password="secret",
        recipients=["admin@example.com", "ops@example.com"],
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
def notifier(email_config: EmailSettings) -> EmailNotifier:
    return EmailNotifier(email_config)


class TestEmailNotifierInit:
    def test_stores_config(self, notifier: EmailNotifier, email_config: EmailSettings) -> None:
        assert notifier.config is email_config

    def test_config_fields_accessible(self, notifier: EmailNotifier) -> None:
        assert notifier.config.smtp_host == "smtp.example.com"
        assert notifier.config.smtp_port == 587
        assert notifier.config.sender == "sender@example.com"
        assert notifier.config.recipients == ["admin@example.com", "ops@example.com"]


class TestBuildSubject:
    def test_subject_contains_request_id(
        self, notifier: EmailNotifier, unknown_judgment: JudgmentResult
    ) -> None:
        subject = notifier._build_subject(unknown_judgment)
        assert "[AI Alarm] Unknown Status Detected - req_20240101_001" == subject

    def test_subject_format_with_different_id(self, notifier: EmailNotifier) -> None:
        judgment = JudgmentResult(
            request_id="req_xyz_999",
            status=JudgmentStatus.UNKNOWN,
            reason="test",
            timestamp="2024-06-15T08:30:00Z",
        )
        subject = notifier._build_subject(judgment)
        assert subject == "[AI Alarm] Unknown Status Detected - req_xyz_999"


class TestBuildBody:
    def test_body_contains_request_id(
        self, notifier: EmailNotifier, unknown_judgment: JudgmentResult
    ) -> None:
        body = notifier._build_body(unknown_judgment)
        assert "req_20240101_001" in body

    def test_body_contains_timestamp(
        self, notifier: EmailNotifier, unknown_judgment: JudgmentResult
    ) -> None:
        body = notifier._build_body(unknown_judgment)
        assert "2024-01-01T12:00:00Z" in body

    def test_body_contains_reason(
        self, notifier: EmailNotifier, unknown_judgment: JudgmentResult
    ) -> None:
        body = notifier._build_body(unknown_judgment)
        assert "4 equipment panels could not be identified" in body


class TestSendAlert:
    @patch("server.services.email_notifier.smtplib.SMTP")
    def test_send_success_returns_true(
        self,
        mock_smtp_cls: MagicMock,
        notifier: EmailNotifier,
        unknown_judgment: JudgmentResult,
    ) -> None:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = notifier.send_alert(unknown_judgment)

        assert result is True

    @patch("server.services.email_notifier.smtplib.SMTP")
    def test_send_calls_starttls_and_login(
        self,
        mock_smtp_cls: MagicMock,
        notifier: EmailNotifier,
        unknown_judgment: JudgmentResult,
    ) -> None:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        notifier.send_alert(unknown_judgment)

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@example.com", "secret")

    @patch("server.services.email_notifier.smtplib.SMTP")
    def test_send_calls_sendmail_with_correct_args(
        self,
        mock_smtp_cls: MagicMock,
        notifier: EmailNotifier,
        unknown_judgment: JudgmentResult,
    ) -> None:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        notifier.send_alert(unknown_judgment)

        mock_server.sendmail.assert_called_once()
        call_args = mock_server.sendmail.call_args
        assert call_args[0][0] == "sender@example.com"
        assert call_args[0][1] == ["admin@example.com", "ops@example.com"]
        # The third arg is the MIME message string (body is base64-encoded)
        msg_str = call_args[0][2]
        # Subject is in plaintext headers
        assert "req_20240101_001" in msg_str
        assert "[AI Alarm] Unknown Status Detected" in msg_str

    @patch("server.services.email_notifier.smtplib.SMTP")
    def test_smtp_connects_to_configured_host_port(
        self,
        mock_smtp_cls: MagicMock,
        notifier: EmailNotifier,
        unknown_judgment: JudgmentResult,
    ) -> None:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        notifier.send_alert(unknown_judgment)

        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)

    @patch("server.services.email_notifier.smtplib.SMTP")
    def test_retry_on_failure_returns_false_after_3_attempts(
        self,
        mock_smtp_cls: MagicMock,
        notifier: EmailNotifier,
        unknown_judgment: JudgmentResult,
    ) -> None:
        mock_smtp_cls.return_value.__enter__ = MagicMock(
            side_effect=smtplib.SMTPException("connection failed")
        )
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=True)

        result = notifier.send_alert(unknown_judgment)

        assert result is False
        assert mock_smtp_cls.return_value.__enter__.call_count == 3

    @patch("server.services.email_notifier.smtplib.SMTP")
    def test_retry_succeeds_on_second_attempt(
        self,
        mock_smtp_cls: MagicMock,
        notifier: EmailNotifier,
        unknown_judgment: JudgmentResult,
    ) -> None:
        mock_server = MagicMock()
        # First call raises, second call succeeds
        mock_smtp_cls.return_value.__enter__ = MagicMock(
            side_effect=[smtplib.SMTPException("temp failure"), mock_server]
        )
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = notifier.send_alert(unknown_judgment)

        assert result is True
        assert mock_smtp_cls.return_value.__enter__.call_count == 2
