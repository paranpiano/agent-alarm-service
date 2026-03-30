"""Logging and storage module for the AI Alarm System.

Provides:
- ResultStorage: Saves judgment results as JSON files and unknown images to disk.
- JudgmentLogger: Appends judgment entries to daily log files.

All file paths are handled via pathlib.Path for cross-platform compatibility.
All file I/O uses encoding='utf-8' explicitly.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from server.models import JudgmentResult

logger = logging.getLogger(__name__)


class ResultStorage:
    """Persists judgment results as JSON files and stores unknown images.

    Results are saved to ``results_dir/{request_id}.json``.
    Unknown images are saved to ``unknown_images_dir/{request_id}_{filename}``.

    Directories are created automatically on first write.
    """

    def __init__(self, results_dir: str, unknown_images_dir: str) -> None:
        self._results_dir = Path(results_dir)
        self._unknown_images_dir = Path(unknown_images_dir)

    def save_result(self, result: JudgmentResult) -> None:
        """Save a judgment result as a JSON file.

        The file is written to ``results_dir/{request_id}.json``.
        """
        self._results_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._results_dir / f"{result.request_id}.json"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError:
            logger.exception("Failed to save result for request_id=%s", result.request_id)

    def save_unknown_image(self, request_id: str, image_bytes: bytes, filename: str) -> None:
        """Save an image associated with an UNKNOWN judgment.

        The file is written to ``unknown_images_dir/{request_id}_{filename}``.
        """
        self._unknown_images_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._unknown_images_dir / f"{request_id}_{filename}"
        try:
            with open(filepath, "wb") as f:
                f.write(image_bytes)
        except OSError:
            logger.exception(
                "Failed to save unknown image for request_id=%s", request_id
            )

    def get_result(self, request_id: str) -> JudgmentResult | None:
        """Load a previously saved judgment result by request_id.

        Returns ``None`` if the file does not exist or cannot be parsed.
        """
        filepath = self._results_dir / f"{request_id}.json"
        if not filepath.is_file():
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return JudgmentResult.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            logger.exception("Failed to load result for request_id=%s", request_id)
            return None


class JudgmentLogger:
    """Appends judgment log entries to daily log files.

    Each day gets its own file: ``logs_dir/YYYY-MM-DD.log``.
    Each entry is a single pipe-delimited line::

        timestamp | request_id | status | reason
    """

    def __init__(self, logs_dir: str) -> None:
        self._logs_dir = Path(logs_dir)

    def log_judgment(self, result: JudgmentResult) -> None:
        """Append a log entry for the given judgment result.

        Uses the result's own timestamp to determine the log file date.
        Falls back to the current UTC date if parsing fails.
        """
        self._logs_dir.mkdir(parents=True, exist_ok=True)

        log_date = self._extract_date(result.timestamp)
        filepath = self._logs_dir / f"{log_date}.log"

        entry = f"{result.timestamp} | {result.request_id} | {result.image_name} | {result.status.value} | {result.reason}\n"

        # Append DI extracted values for traceability
        if result.equipment_data:
            for eq_id, eq_data in result.equipment_data.items():
                for field_name, vals in eq_data.items():
                    if isinstance(vals, list) and vals and field_name not in ("ng_items", "stations"):
                        entry += f"  [{eq_id}.{field_name}] ({len(vals)}개): {vals}\n"

        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(entry)
        except OSError:
            logger.exception(
                "Failed to write log entry for request_id=%s", result.request_id
            )

    @staticmethod
    def _extract_date(timestamp: str) -> str:
        """Extract YYYY-MM-DD from an ISO 8601 timestamp string.

        Returns today's UTC date as fallback on parse failure.
        """
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return datetime.now().strftime("%Y-%m-%d")
