"""Unit tests for server.logger module (ResultStorage and JudgmentLogger)."""

import json
from pathlib import Path

import pytest

from server.logger import JudgmentLogger, ResultStorage
from server.models import JudgmentResult, JudgmentStatus


def _make_result(
    request_id: str = "req_001",
    status: JudgmentStatus = JudgmentStatus.OK,
    reason: str = "All equipment normal",
    timestamp: str = "2024-06-15T10:30:00+09:00",
    processing_time_ms: int = 1500,
    image_name: str = "test.png",
) -> JudgmentResult:
    """Helper to create a JudgmentResult with sensible defaults."""
    return JudgmentResult(
        request_id=request_id,
        status=status,
        reason=reason,
        timestamp=timestamp,
        processing_time_ms=processing_time_ms,
        image_name=image_name,
    )


# ---------------------------------------------------------------------------
# ResultStorage tests
# ---------------------------------------------------------------------------


class TestResultStorage:
    """Tests for ResultStorage."""

    def test_save_and_get_result(self, tmp_path: Path) -> None:
        """Saved result can be retrieved by request_id."""
        storage = ResultStorage(
            results_dir=str(tmp_path / "results"),
            unknown_images_dir=str(tmp_path / "unknown"),
        )
        result = _make_result()
        storage.save_result(result)
        loaded = storage.get_result("req_001")

        assert loaded is not None
        assert loaded.request_id == result.request_id
        assert loaded.status == result.status
        assert loaded.reason == result.reason
        assert loaded.timestamp == result.timestamp
        assert loaded.processing_time_ms == result.processing_time_ms
        assert loaded.image_name == result.image_name

    def test_get_result_nonexistent(self, tmp_path: Path) -> None:
        """get_result returns None for a missing request_id."""
        storage = ResultStorage(
            results_dir=str(tmp_path / "results"),
            unknown_images_dir=str(tmp_path / "unknown"),
        )
        assert storage.get_result("does_not_exist") is None

    def test_save_result_creates_directory(self, tmp_path: Path) -> None:
        """Directories are created automatically on save."""
        results_dir = tmp_path / "nested" / "results"
        storage = ResultStorage(
            results_dir=str(results_dir),
            unknown_images_dir=str(tmp_path / "unknown"),
        )
        storage.save_result(_make_result())
        assert results_dir.is_dir()

    def test_save_result_json_content(self, tmp_path: Path) -> None:
        """Saved JSON file contains expected fields."""
        storage = ResultStorage(
            results_dir=str(tmp_path / "results"),
            unknown_images_dir=str(tmp_path / "unknown"),
        )
        result = _make_result(request_id="req_json")
        storage.save_result(result)

        filepath = tmp_path / "results" / "req_json.json"
        assert filepath.is_file()
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["request_id"] == "req_json"
        assert data["status"] == "OK"

    def test_save_unknown_image(self, tmp_path: Path) -> None:
        """Unknown images are saved with request_id prefix."""
        storage = ResultStorage(
            results_dir=str(tmp_path / "results"),
            unknown_images_dir=str(tmp_path / "unknown"),
        )
        image_bytes = b"\x89PNG\r\n\x1a\nfake_image_data"
        storage.save_unknown_image("req_unk_001", image_bytes, "screen.png")

        filepath = tmp_path / "unknown" / "req_unk_001_screen.png"
        assert filepath.is_file()
        assert filepath.read_bytes() == image_bytes

    def test_save_unknown_image_creates_directory(self, tmp_path: Path) -> None:
        """Unknown images directory is created automatically."""
        unknown_dir = tmp_path / "deep" / "unknown"
        storage = ResultStorage(
            results_dir=str(tmp_path / "results"),
            unknown_images_dir=str(unknown_dir),
        )
        storage.save_unknown_image("req_002", b"data", "img.png")
        assert unknown_dir.is_dir()

    def test_save_and_get_with_equipment_data(self, tmp_path: Path) -> None:
        """Results with equipment_data round-trip correctly."""
        storage = ResultStorage(
            results_dir=str(tmp_path / "results"),
            unknown_images_dir=str(tmp_path / "unknown"),
        )
        result = _make_result(request_id="req_equip")
        result.equipment_data = {"S520": {"identified": True}}
        storage.save_result(result)

        loaded = storage.get_result("req_equip")
        assert loaded is not None
        assert loaded.equipment_data == {"S520": {"identified": True}}

    def test_get_result_corrupted_json(self, tmp_path: Path) -> None:
        """get_result returns None when JSON file is corrupted."""
        results_dir = tmp_path / "results"
        results_dir.mkdir(parents=True)
        filepath = results_dir / "req_bad.json"
        filepath.write_text("not valid json {{{", encoding="utf-8")

        storage = ResultStorage(
            results_dir=str(results_dir),
            unknown_images_dir=str(tmp_path / "unknown"),
        )
        assert storage.get_result("req_bad") is None


# ---------------------------------------------------------------------------
# JudgmentLogger tests
# ---------------------------------------------------------------------------


class TestJudgmentLogger:
    """Tests for JudgmentLogger."""

    def test_log_creates_daily_file(self, tmp_path: Path) -> None:
        """A log file named YYYY-MM-DD.log is created."""
        logger = JudgmentLogger(logs_dir=str(tmp_path / "logs"))
        result = _make_result(timestamp="2024-06-15T10:30:00+09:00")
        logger.log_judgment(result)

        log_file = tmp_path / "logs" / "2024-06-15.log"
        assert log_file.is_file()

    def test_log_entry_format(self, tmp_path: Path) -> None:
        """Each log entry contains timestamp | request_id | status | reason."""
        logger = JudgmentLogger(logs_dir=str(tmp_path / "logs"))
        result = _make_result(
            request_id="req_fmt",
            status=JudgmentStatus.NG,
            reason="S520 value exceeded 3000",
            timestamp="2024-06-15T10:30:00+09:00",
        )
        logger.log_judgment(result)

        log_file = tmp_path / "logs" / "2024-06-15.log"
        content = log_file.read_text(encoding="utf-8")
        assert "2024-06-15T10:30:00+09:00" in content
        assert "req_fmt" in content
        assert "NG" in content
        assert "S520 value exceeded 3000" in content

    def test_log_appends_multiple_entries(self, tmp_path: Path) -> None:
        """Multiple log entries are appended to the same daily file."""
        logger = JudgmentLogger(logs_dir=str(tmp_path / "logs"))
        for i in range(3):
            result = _make_result(
                request_id=f"req_{i:03d}",
                timestamp="2024-06-15T10:30:00+09:00",
            )
            logger.log_judgment(result)

        log_file = tmp_path / "logs" / "2024-06-15.log"
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_log_different_dates_separate_files(self, tmp_path: Path) -> None:
        """Entries with different dates go to separate log files."""
        logger = JudgmentLogger(logs_dir=str(tmp_path / "logs"))
        logger.log_judgment(_make_result(timestamp="2024-06-15T10:00:00Z"))
        logger.log_judgment(_make_result(timestamp="2024-06-16T10:00:00Z"))

        assert (tmp_path / "logs" / "2024-06-15.log").is_file()
        assert (tmp_path / "logs" / "2024-06-16.log").is_file()

    def test_log_creates_directory(self, tmp_path: Path) -> None:
        """Logs directory is created automatically."""
        logs_dir = tmp_path / "nested" / "logs"
        logger = JudgmentLogger(logs_dir=str(logs_dir))
        logger.log_judgment(_make_result())
        assert logs_dir.is_dir()

    def test_log_entry_contains_pipe_delimiters(self, tmp_path: Path) -> None:
        """Log entries use pipe delimiters."""
        logger = JudgmentLogger(logs_dir=str(tmp_path / "logs"))
        logger.log_judgment(_make_result(timestamp="2024-06-15T10:30:00Z"))

        log_file = tmp_path / "logs" / "2024-06-15.log"
        content = log_file.read_text(encoding="utf-8").strip()
        parts = content.split(" | ")
        assert len(parts) == 4

    def test_log_all_statuses(self, tmp_path: Path) -> None:
        """All judgment statuses can be logged."""
        logger = JudgmentLogger(logs_dir=str(tmp_path / "logs"))
        for status in JudgmentStatus:
            logger.log_judgment(
                _make_result(
                    request_id=f"req_{status.value}",
                    status=status,
                    timestamp="2024-06-15T10:30:00Z",
                )
            )

        log_file = tmp_path / "logs" / "2024-06-15.log"
        content = log_file.read_text(encoding="utf-8")
        for status in JudgmentStatus:
            assert status.value in content
