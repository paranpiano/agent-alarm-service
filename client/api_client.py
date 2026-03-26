"""HTTP client for communicating with the AI Alarm System server.

Provides:
- AlarmApiClient: Synchronous client for image analysis and health check endpoints.
"""

import logging
import random
from datetime import datetime
from pathlib import Path

import requests

from server.models import JudgmentResult, JudgmentStatus

logger = logging.getLogger(__name__)


def _generate_request_id() -> str:
    """Generate a unique request ID in the format req_YYYYMMDD_HHMMSS_XXXX."""
    now = datetime.now()
    suffix = f"{random.randint(0, 9999):04d}"
    return f"req_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"


class AlarmApiClient:
    """Synchronous HTTP client for the AI Alarm System server.

    Args:
        base_url: Base URL of the server (e.g. ``http://localhost:8000``).
        request_timeout: HTTP request timeout in seconds.  Defaults to 35.0,
            which is slightly longer than the server's 30-second LLM timeout
            so the server has time to return a TIMEOUT response.
    """

    _MAX_RETRIES = 3

    def __init__(self, base_url: str, request_timeout: float = 35.0) -> None:
        # Strip trailing slash for consistent URL construction
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout

    def analyze_single(self, image_path: Path) -> JudgmentResult:
        """Send a single image for analysis with up to 3 retries.

        The server automatically detects whether the image is a single panel
        or a full 4-panel composite based on aspect ratio.

        Args:
            image_path: Path to the image file (PNG or JPEG).
        """
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        request_id = _generate_request_id()
        url = f"{self.base_url}/api/v1/analyze"

        image_bytes = image_path.read_bytes()
        filename = image_path.name

        last_exc: Exception | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            files = {"image": (filename, image_bytes)}
            data: dict = {"request_id": request_id}

            try:
                response = requests.post(
                    url,
                    files=files,
                    data=data,
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                json_data = response.json()
                return JudgmentResult.from_dict(json_data)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                logger.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt, self._MAX_RETRIES, url, exc,
                )
                continue
            except (ValueError, KeyError) as exc:
                logger.error("Failed to parse server response: %s", exc)
                raise ValueError(f"Invalid server response: {exc}") from exc

        # All retries exhausted
        logger.error(
            "All %d attempts failed for %s", self._MAX_RETRIES, url
        )
        raise last_exc  # type: ignore[misc]

    def health_check(self) -> bool:
        """Check whether the server is healthy.

        Sends ``GET /api/v1/health`` and returns ``True`` when the server
        responds with HTTP 200, ``False`` otherwise.
        """
        url = f"{self.base_url}/api/v1/health"
        try:
            response = requests.get(url, timeout=self.request_timeout)
            return response.status_code == 200
        except requests.RequestException:
            logger.warning("Health check failed for %s", url)
            return False
