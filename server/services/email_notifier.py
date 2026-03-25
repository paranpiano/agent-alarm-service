"""Email notification module for the AI Alarm System.

Sends alert emails when an UNKNOWN judgment status is detected.
Uses smtplib (standard library) with MIMEText for email construction.
Supports configurable SMTP settings and up to 3 retries on failure.
"""

import logging
import smtplib
from email.mime.text import MIMEText

from server.config import EmailSettings
from server.models import JudgmentResult

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class EmailNotifier:
    """Sends alert emails for UNKNOWN judgment results.

    Attributes:
        config: SMTP and recipient settings loaded from EmailSettings.
    """

    def __init__(self, config: EmailSettings) -> None:
        """Initialize with SMTP configuration.

        Args:
            config: EmailSettings dataclass containing smtp_host, smtp_port,
                    sender, password, and recipients.
        """
        self.config = config

    def _build_subject(self, judgment: JudgmentResult) -> str:
        """Build the email subject line."""
        return f"[AI Alarm] Unknown Status Detected - {judgment.request_id}"

    def _build_body(self, judgment: JudgmentResult) -> str:
        """Build the email body including reason, timestamp, and request_id."""
        return (
            f"An unknown status has been detected.\n"
            f"\n"
            f"Request ID : {judgment.request_id}\n"
            f"Timestamp  : {judgment.timestamp}\n"
            f"Reason     : {judgment.reason}\n"
        )

    def send_alert(self, judgment: JudgmentResult) -> bool:
        """Send an alert email for an UNKNOWN judgment result.

        Retries up to 3 times on SMTP failures. Each failure is logged.

        Args:
            judgment: The JudgmentResult that triggered the alert.

        Returns:
            True if the email was sent successfully, False after all retries fail.
        """
        subject = self._build_subject(judgment)
        body = self._build_body(judgment)

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.config.sender
        msg["To"] = ", ".join(self.config.recipients)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                    server.starttls()
                    server.login(self.config.sender, self.config.password)
                    server.sendmail(
                        self.config.sender,
                        self.config.recipients,
                        msg.as_string(),
                    )
                logger.info(
                    "Alert email sent for request_id=%s (attempt %d)",
                    judgment.request_id,
                    attempt,
                )
                return True
            except smtplib.SMTPException:
                logger.exception(
                    "Failed to send alert email for request_id=%s (attempt %d/%d)",
                    judgment.request_id,
                    attempt,
                    _MAX_RETRIES,
                )

        logger.error(
            "All %d email send attempts failed for request_id=%s",
            _MAX_RETRIES,
            judgment.request_id,
        )
        return False
