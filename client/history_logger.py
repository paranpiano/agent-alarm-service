"""CSV history logger for the AI Alarm System client.

Appends each analysis result as a row to ``data/client_history.csv``.
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_CSV_COLUMNS = ["timestamp", "image_name", "expected", "actual", "match", "reason", "time_ms"]


class HistoryLogger:
    """Append-only CSV logger for analysis results.

    Args:
        log_dir: Directory where ``client_history.csv`` is written.
            Created automatically if it does not exist.
    """

    def __init__(self, log_dir: str = "data") -> None:
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "client_history.csv"

        # Write header if the file does not exist yet
        if not self._path.exists():
            with open(self._path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(_CSV_COLUMNS)

    def log_result(
        self,
        image_name: str,
        expected: str,
        actual: str,
        match: bool,
        reason: str,
        time_ms: str,
    ) -> None:
        """Append a single result row to the CSV file.

        Args:
            image_name: Name of the analyzed image file.
            expected: Expected judgment (e.g. ``OK``, ``NG``).
            actual: Actual judgment returned by the server.
            match: Whether expected and actual agree.
            reason: Judgment reason text.
            time_ms: Processing time in milliseconds (as string).
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self._path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, image_name, expected, actual, match, reason, time_ms])
        except Exception:
            logger.exception("Failed to write history CSV row")
