"""CSV history logger for the AI Alarm System client."""

import csv
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_CSV_COLUMNS = ["timestamp", "image_name", "status", "reason", "time_ms"]


class HistoryLogger:
    def __init__(self, log_dir: str = "data") -> None:
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "client_history.csv"
        if not self._path.exists():
            with open(self._path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(_CSV_COLUMNS)

    def log_result(self, image_name: str, status: str, reason: str, time_ms: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self._path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([timestamp, image_name, status, reason, time_ms])
        except Exception:
            logger.exception("Failed to write history CSV row")
