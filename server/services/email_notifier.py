"""SNS notification module for the AI Alarm System.

Sends alert notifications via AWS SNS API Gateway when an UNKNOWN
judgment status is detected. Replaces the previous SMTP-based approach.
Supports up to 3 retries on failure.
"""

import logging

import requests

from server.config import SnsSettings
from server.models import JudgmentResult

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class EmailNotifier:
    """Sends alert notifications for UNKNOWN judgment results via SNS API.

    Despite the class name (kept for backward compatibility), this now
    uses an AWS SNS API Gateway endpoint instead of SMTP.

    Attributes:
        config: SNS settings (api_url, topic_arn, protocol).
    """

    def __init__(self, config: SnsSettings) -> None:
        """Initialize with SNS configuration.

        Args:
            config: SnsSettings with api_url, topic_arn, and protocol.
        """
        self.config = config

    def _build_subject(self, judgment: JudgmentResult) -> str:
        """Build the notification subject line."""
        return f"[AI Alarm] Unknown Status Detected - {judgment.request_id}"

    def _build_message(self, judgment: JudgmentResult) -> str:
        """Build the notification message body."""
        return (
            f"An unknown status has been detected.\n"
            f"\n"
            f"Request ID : {judgment.request_id}\n"
            f"Timestamp  : {judgment.timestamp}\n"
            f"Reason     : {judgment.reason}\n"
        )

    def send_alert(self, judgment: JudgmentResult) -> bool:
        """Send an alert notification for an UNKNOWN judgment result.

        Posts to the SNS API Gateway endpoint. Retries up to 3 times
        on failure. Each failure is logged.

        Args:
            judgment: The JudgmentResult that triggered the alert.

        Returns:
            True if the notification was sent successfully,
            False after all retries fail.
        """
        if not self.config.api_url or not self.config.topic_arn:
            logger.warning(
                "SNS not configured (missing api_url or topic_arn); "
                "skipping alert for request_id=%s",
                judgment.request_id,
            )
            return False

        subject = self._build_subject(judgment)
        message = self._build_message(judgment)

        payload = {
            "topicArn": self.config.topic_arn,
            "subject": subject,
            "message": message,
            "protocol": self.config.protocol,
        }

        url = f"{self.config.api_url.rstrip('/')}?action=publishMessage"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                data = response.json()
                logger.info(
                    "SNS alert sent for request_id=%s (attempt %d, messageId=%s)",
                    judgment.request_id,
                    attempt,
                    data.get("messageId", "unknown"),
                )
                return True
            except requests.RequestException as exc:
                logger.warning(
                    "Failed to send SNS alert for request_id=%s (attempt %d/%d): %s",
                    judgment.request_id,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )

        logger.error(
            "All %d SNS alert attempts failed for request_id=%s",
            _MAX_RETRIES,
            judgment.request_id,
        )
        return False
