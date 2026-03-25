"""Periodic analysis runner for the AI Alarm System client.

Provides:
- PeriodicRunner: Runs image analysis at configurable intervals in a
  background daemon thread, delivering results via a callback.
"""

import logging
import threading
from pathlib import Path
from typing import Callable

from client.api_client import AlarmApiClient
from server.models import JudgmentResult

logger = logging.getLogger(__name__)


class PeriodicRunner:
    """Execute periodic image analysis requests in a background thread.

    Args:
        api_client: An :class:`AlarmApiClient` used to send analysis requests.
        interval_seconds: Seconds between consecutive requests (5 or 10).
    """

    _ALLOWED_INTERVALS = (5, 10)

    def __init__(self, api_client: AlarmApiClient, interval_seconds: int = 5) -> None:
        self._api_client = api_client
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        image_path: Path,
        callback: Callable[[JudgmentResult], None],
    ) -> None:
        """Start periodic analysis in a daemon thread.

        If the runner is already active the call is silently ignored.

        Args:
            image_path: Path to the image file to analyze each cycle.
            callback: Invoked with a :class:`JudgmentResult` after every
                successful analysis.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("PeriodicRunner is already running; ignoring start()")
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(image_path, callback),
                daemon=True,
                name="periodic-runner",
            )
            self._thread.start()
            logger.info(
                "PeriodicRunner started (interval=%ds, image=%s)",
                self._interval_seconds,
                image_path,
            )

    def stop(self) -> None:
        """Signal the background thread to stop.

        The method returns immediately; the thread will finish its current
        sleep/request cycle and then exit.
        """
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=self._interval_seconds + 5)
            logger.info("PeriodicRunner stopped")

    def set_interval(self, seconds: int) -> None:
        """Change the request interval.

        Args:
            seconds: New interval in seconds (5 or 10).

        Raises:
            ValueError: If *seconds* is not 5 or 10.
        """
        if seconds not in self._ALLOWED_INTERVALS:
            raise ValueError(
                f"Interval must be one of {self._ALLOWED_INTERVALS}, got {seconds}"
            )
        self._interval_seconds = seconds
        logger.info("PeriodicRunner interval changed to %ds", seconds)

    @property
    def is_running(self) -> bool:
        """Return ``True`` if the background thread is alive."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(
        self,
        image_path: Path,
        callback: Callable[[JudgmentResult], None],
    ) -> None:
        """Main loop executed inside the daemon thread."""
        while not self._stop_event.is_set():
            try:
                result = self._api_client.analyze_single(image_path)
                callback(result)
            except Exception:
                logger.exception(
                    "Error during periodic analysis of %s; will retry next cycle",
                    image_path,
                )

            # Wait for the configured interval, but wake up early if stopped
            self._stop_event.wait(timeout=self._interval_seconds)
