"""Unit tests for client.gui module.

Tests the AlarmTestGUI class logic without requiring a live server.
Uses a headless Tk root where possible; skips if display is unavailable.
"""

import os
import sys
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# ------------------------------------------------------------------
# Tag selection logic
# ------------------------------------------------------------------

class TestTagFor:
    """Tests for AlarmTestGUI._tag_for static method."""

    def test_timeout_always_returns_timeout(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.TIMEOUT, True) == "timeout"
        assert AlarmTestGUI._tag_for(JudgmentStatus.TIMEOUT, False) == "timeout"

    def test_mismatch_when_not_matching(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.OK, False) == "mismatch"
        assert AlarmTestGUI._tag_for(JudgmentStatus.NG, False) == "mismatch"

    def test_ok_match(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.OK, True) == "ok_match"

    def test_ng_match(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.NG, True) == "ng_match"

    def test_unknown_match(self):
        assert AlarmTestGUI._tag_for(JudgmentStatus.UNKNOWN, True) == "unknown_match"


# ------------------------------------------------------------------
# Folder scanning
# ------------------------------------------------------------------

class TestScanImages:
    """Tests for folder scanning and image list population."""

    def test_scan_populates_image_list(self, gui, tmp_path):
        """Scanning a valid test_images folder populates _image_list."""
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
        assert len(gui._image_list) == 2

    def test_scan_ignores_non_image_files(self, gui, tmp_path):
        """Non-image files (.txt, .gitkeep) are excluded."""
        ok_dir = tmp_path / "ok"
        ok_dir.mkdir()
        (ok_dir / "readme.txt").write_bytes(b"text")
        (ok_dir / ".gitkeep").write_bytes(b"")
        (ok_dir / "valid.png").write_bytes(b"fake")

        gui._test_root = tmp_path
        gui._scan_images()

        assert len(gui._image_list) == 1
        assert gui._image_list[0][0].name == "valid.png"

    def test_scan_expected_from_folder_name(self, gui, tmp_path):
        """Expected status is derived from the subfolder name."""
        ng_dir = tmp_path / "ng"
        ng_dir.mkdir()
        (ng_dir / "alarm.png").write_bytes(b"fake")

        gui._test_root = tmp_path
        gui._scan_images()

        assert gui._image_list[0][1] == "ng"

    def test_scan_empty_folder(self, gui, tmp_path):
        """Empty subfolders produce no entries."""
        (tmp_path / "ok").mkdir()
        (tmp_path / "ng").mkdir()

        gui._test_root = tmp_path
        gui._scan_images()

        assert gui._image_list == []

    def test_scan_missing_root(self, gui, tmp_path):
        """Non-existent root folder produces no entries."""
        gui._test_root = tmp_path / "nonexistent"
        gui._scan_images()
        assert gui._image_list == []


# ------------------------------------------------------------------
# Results display
# ------------------------------------------------------------------

class TestDisplayResults:
    """Tests for _display_results populating the results Treeview."""

    def test_display_successful_result(self, gui):
        result = JudgmentResult(
            request_id="req_001",
            status=JudgmentStatus.OK,
            reason="All equipment normal",
            timestamp="2024-01-01T00:00:00Z",
            processing_time_ms=1500,
            image_name="test.png",
        )
        gui._display_results([("test.png", "ok", result, None)])

        children = gui._result_tree.get_children()
        assert len(children) == 1
        values = gui._result_tree.item(children[0], "values")
        assert values[0] == "ok"       # expected
        assert values[1] == "OK"       # actual
        assert values[2] == "\u2713"   # match checkmark
        assert values[4] == "1500"     # time_ms

    def test_display_mismatch_result(self, gui):
        result = JudgmentResult(
            request_id="req_002",
            status=JudgmentStatus.NG,
            reason="S520 over threshold",
            timestamp="2024-01-01T00:00:00Z",
            processing_time_ms=2000,
        )
        gui._display_results([("test.png", "ok", result, None)])

        children = gui._result_tree.get_children()
        values = gui._result_tree.item(children[0], "values")
        assert values[2] == "\u2717"  # mismatch cross
        tags = gui._result_tree.item(children[0], "tags")
        assert "mismatch" in tags

    def test_display_error_result(self, gui):
        gui._display_results([("test.png", "ok", None, "Connection refused")])

        children = gui._result_tree.get_children()
        values = gui._result_tree.item(children[0], "values")
        assert values[1] == "ERROR"
        assert "Connection refused" in values[3]

    def test_display_timeout_result(self, gui):
        result = JudgmentResult(
            request_id="req_003",
            status=JudgmentStatus.TIMEOUT,
            reason="LLM timeout",
            timestamp="2024-01-01T00:00:00Z",
            processing_time_ms=30000,
        )
        gui._display_results([("test.png", "ok", result, None)])

        children = gui._result_tree.get_children()
        tags = gui._result_tree.item(children[0], "tags")
        assert "timeout" in tags


# ------------------------------------------------------------------
# History
# ------------------------------------------------------------------

class TestHistory:
    """Tests for the recent history table."""

    def test_add_history_inserts_row(self, gui):
        gui._add_history("img.png", "OK", "1200")
        children = gui._history_tree.get_children()
        assert len(children) == 1

    def test_history_bounded_at_50(self, gui):
        for i in range(55):
            gui._add_history(f"img_{i}.png", "OK", "100")
        children = gui._history_tree.get_children()
        assert len(children) == 50


# ------------------------------------------------------------------
# API client update
# ------------------------------------------------------------------

class TestApiClientUpdate:
    """Tests for _update_api_client."""

    def test_default_url(self, gui):
        gui._update_api_client()
        assert gui._api_client is not None
        assert gui._api_client.base_url == "http://localhost:8000"

    def test_custom_url(self, gui):
        gui._url_var.set("http://myserver:9000/")
        gui._update_api_client()
        assert gui._api_client.base_url == "http://myserver:9000"
