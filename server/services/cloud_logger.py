"""Cloud log uploader for AI Alarm System.

Sends judgment results to AWS via API Gateway (POST /logs) asynchronously.
Uses fire-and-forget threading so it never blocks the main response.
"""

import logging
import threading
import requests
from server.models import JudgmentResult

logger = logging.getLogger(__name__)


class CloudLogger:
    """Uploads judgment log entries to cloud (DynamoDB via API Gateway)."""

    def __init__(self, api_url: str) -> None:
        self._url = api_url
        self._headers = {"Content-Type": "application/json"}

    def log_async(self, result: JudgmentResult) -> None:
        """Fire-and-forget: upload in background thread."""
        t = threading.Thread(target=self._send, args=(result,), daemon=False)
        t.start()

    def _send(self, result: JudgmentResult) -> None:
        try:
            resp = requests.post(self._url, json=result.to_dict(), headers=self._headers, timeout=15)
            resp.raise_for_status()
            logger.debug("Cloud log uploaded: %s", result.request_id)
        except Exception as exc:
            logger.warning("Cloud log upload failed for %s: %s", result.request_id, exc)
