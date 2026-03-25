"""Unit tests for client.gui module.

Tests the AlarmTestGUI class logic without requiring a live server.
Uses a headless Tk root where possible; skips if display is unavailable.
"""

import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Skip entire module when no display is available (CI / headless)
_DISPLAY_AVAILABLE = True
try:
    _test_root = tk.Tk()
    _test_root.withdraw()
    _test_root.destroy()
except tk.TclError:
    _DISPLAY_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DISPLAY_AVAILABLE, reason="No display available for tkinter"
)

from client.gui import AlarmTestGUI, _EXPECTED_FOLDERS, _IMAGE_EXTENSIONS
from server.models import JudgmentResult, JudgmentStatus


@pytest.fixture()
def gui():
    """Create an AlarmTestGUI instance with a hidden Tk root."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tkinter Tcl not available")
    root.withdraw()
    app = AlarmTestGUI(root)
    yield app
    root.destroy()


class TestTagFor:
    """Tests for AlarmTestGUI._tag_for static method."""

    def test_timeout_always_returns_timeout(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.TIMEOUT, True) == "timeout"
        assert AlarmTestGUI._tag_for(JudgmentStatus.TIMEOUT, False) == "timeout"

    def test_mismatch_when_not_matching(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.OK, False) == "mismatch"

    def test_ok_match(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.OK, True) == "ok_match"

    def test_ng_match(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.NG, True) == "ng_match"

    def test_unknown_match(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.UNKNOWN, True) == "unknown_match"


class TestScanImages:
    """Tests for folder scanning."""

    def test_scan_populates_image_list(self, gui, tmp_path):
        ok_dir = tmp_path / "ok"
        ng_dir = tmp_path / "ng"
        ok_dir.mkdir()
        ng_dir.mkdir()
        (ok_dir / "img1.png").write_bytes(b"fake")
        (ng_dir / "img2.jpg").write_bytes(b"fake")

        gui._test_root = tmp_path
        gui._scan_images()

        names = [p.name for p, _ in gui._image_list]
        assert "img1.png" in names
        assert "img2.jpg" in names

    def test_scan_ignores_non_image_files(self, gui, tmp_path):
        ok_dir = tmp_path / "ok"
        ok_dir.mkdir()
        (ok_dir / "readme.txt").write_bytes(b"text")
        (ok_dir / "valid.png").write_bytes(b"fake")

        gui._test_root = tmp_path
        gui._scan_images()

        assert len(gui._image_list) == 1

    def test_scan_empty_folder(self, gui, tmp_path):
        (tmp_path / "ok").mkdir()
        gui._test_root = tmp_path
        gui._scan_images()
        assert gui._image_list == []


class TestHistory:
    """Tests for the history table."""

    def test_add_history_inserts_row(self, gui):
        result = JudgmentResult(
            request_id="req_001", status=JudgmentStatus.OK,
            reason="Normal", timestamp="2024-01-01T00:00:00Z",
            processing_time_ms=100,
        )
        gui._add_history("img.png", "ok", result, None)
        children = gui._history_tree.get_children()
        assert len(children) == 1

    def test_history_bounded_at_100(self, gui):
        result = JudgmentResult(
            request_id="req_001", status=JudgmentStatus.OK,
            reason="Normal", timestamp="2024-01-01T00:00:00Z",
            processing_time_ms=100,
        )
        for i in range(105):
            gui._add_history(f"img_{i}.png", "ok", result, None)
        children = gui._history_tree.get_children()
        assert len(children) == 100
