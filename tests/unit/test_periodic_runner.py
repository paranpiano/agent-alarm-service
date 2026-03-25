"""Unit tests for client.periodic_runner module."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from client.periodic_runner import PeriodicRunner
from server.models import JudgmentResult, JudgmentStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(**overrides) -> JudgmentResult:
    """Create a minimal JudgmentResult for testing."""
    defaults = {
        "request_id": "req_test_001",
        "status": JudgmentStatus.OK,
        "reason": "All normal",
        "timestamp": "2024-01-01T00:00:00Z",
        "processing_time_ms": 100,
        "image_name": "test.png",
    }
    defaults.update(overrides)
    return JudgmentResult(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_api_client():
    """Return a mock AlarmApiClient."""
    client = MagicMock()
    client.analyze_single.return_value = _make_result()
    return client


@pytest.fixture
def tmp_image(tmp_path):
    """Create a tiny temporary PNG file."""
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return img


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestPeriodicRunnerInit:
    def test_default_interval(self, mock_api_client):
        runner = PeriodicRunner(mock_api_client)
        assert runner._interval_seconds == 5

    def test_custom_interval(self, mock_api_client):
        runner = PeriodicRunner(mock_api_client, interval_seconds=10)
        assert runner._interval_seconds == 10

    def test_not_running_initially(self, mock_api_client):
        runner = PeriodicRunner(mock_api_client)
        assert runner.is_running is False


# ---------------------------------------------------------------------------
# set_interval
# ---------------------------------------------------------------------------

class TestSetInterval:
    def test_set_valid_interval_5(self, mock_api_client):
        runner = PeriodicRunner(mock_api_client, interval_seconds=10)
        runner.set_interval(5)
        assert runner._interval_seconds == 5

    def test_set_valid_interval_10(self, mock_api_client):
        runner = PeriodicRunner(mock_api_client, interval_seconds=5)
        runner.set_interval(10)
        assert runner._interval_seconds == 10

    def test_invalid_interval_raises(self, mock_api_client):
        runner = PeriodicRunner(mock_api_client)
        with pytest.raises(ValueError, match="Interval must be one of"):
            runner.set_interval(3)

    def test_invalid_interval_zero(self, mock_api_client):
        runner = PeriodicRunner(mock_api_client)
        with pytest.raises(ValueError):
            runner.set_interval(0)


# ---------------------------------------------------------------------------
# start / stop / is_running
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_sets_running(self, mock_api_client, tmp_image):
        runner = PeriodicRunner(mock_api_client, interval_seconds=5)
        callback = MagicMock()

        runner.start(tmp_image, callback)
        try:
            assert runner.is_running is True
        finally:
            runner.stop()

    def test_stop_clears_running(self, mock_api_client, tmp_image):
        runner = PeriodicRunner(mock_api_client, interval_seconds=5)
        callback = MagicMock()

        runner.start(tmp_image, callback)
        runner.stop()
        assert runner.is_running is False

    def test_start_creates_daemon_thread(self, mock_api_client, tmp_image):
        runner = PeriodicRunner(mock_api_client, interval_seconds=5)
        callback = MagicMock()

        runner.start(tmp_image, callback)
        try:
            assert runner._thread is not None
            assert runner._thread.daemon is True
            assert runner._thread.name == "periodic-runner"
        finally:
            runner.stop()

    def test_double_start_ignored(self, mock_api_client, tmp_image):
        """Calling start() twice should not create a second thread."""
        runner = PeriodicRunner(mock_api_client, interval_seconds=5)
        callback = MagicMock()

        runner.start(tmp_image, callback)
        first_thread = runner._thread
        runner.start(tmp_image, callback)
        try:
            assert runner._thread is first_thread
        finally:
            runner.stop()

    def test_stop_when_not_running(self, mock_api_client):
        """Calling stop() when not running should not raise."""
        runner = PeriodicRunner(mock_api_client)
        runner.stop()  # Should not raise


# ---------------------------------------------------------------------------
# Callback delivery
# ---------------------------------------------------------------------------

class TestCallbackDelivery:
    def test_callback_receives_result(self, mock_api_client, tmp_image):
        """The callback should be invoked with a JudgmentResult."""
        received = []
        runner = PeriodicRunner(mock_api_client, interval_seconds=5)

        def on_result(result):
            received.append(result)
            # Stop after first result to avoid waiting
            runner.stop()

        runner.start(tmp_image, on_result)
        # Wait enough time for at least one cycle
        runner._thread.join(timeout=3)

        assert len(received) >= 1
        assert isinstance(received[0], JudgmentResult)
        assert received[0].status == JudgmentStatus.OK

    def test_multiple_callbacks(self, mock_api_client, tmp_image):
        """With a very short wait the loop should invoke callback multiple times."""
        received = []
        # Use a short interval by patching _stop_event.wait to return quickly
        runner = PeriodicRunner(mock_api_client, interval_seconds=5)

        call_count = 0

        def on_result(result):
            nonlocal call_count
            received.append(result)
            call_count += 1
            if call_count >= 2:
                runner.stop()

        # Patch the interval to be very short for testing
        runner._interval_seconds = 5
        # Override the stop_event wait to return immediately for fast cycling
        original_wait = runner._stop_event.wait

        def fast_wait(timeout=None):
            return original_wait(timeout=0.05)

        runner._stop_event.wait = fast_wait

        runner.start(tmp_image, on_result)
        runner._thread.join(timeout=3)

        assert len(received) >= 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_analysis_error_does_not_crash(self, mock_api_client, tmp_image):
        """If analyze_single raises, the loop should continue."""
        call_count = 0
        received = []

        def side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("server down")
            return _make_result()

        mock_api_client.analyze_single.side_effect = side_effect

        runner = PeriodicRunner(mock_api_client, interval_seconds=5)

        def on_result(result):
            received.append(result)
            runner.stop()

        # Speed up the loop
        original_wait = runner._stop_event.wait

        def fast_wait(timeout=None):
            return original_wait(timeout=0.05)

        runner._stop_event.wait = fast_wait

        runner.start(tmp_image, on_result)
        runner._thread.join(timeout=3)

        # First call raised, second succeeded
        assert len(received) >= 1
        assert received[0].status == JudgmentStatus.OK

    def test_callback_not_called_on_error(self, mock_api_client, tmp_image):
        """Callback should NOT be invoked when analysis raises."""
        mock_api_client.analyze_single.side_effect = ConnectionError("fail")
        callback = MagicMock()

        runner = PeriodicRunner(mock_api_client, interval_seconds=5)

        # Speed up and limit iterations
        original_wait = runner._stop_event.wait
        iteration = 0

        def fast_wait(timeout=None):
            nonlocal iteration
            iteration += 1
            if iteration >= 3:
                runner._stop_event.set()
                return True
            return original_wait(timeout=0.05)

        runner._stop_event.wait = fast_wait

        runner.start(tmp_image, callback)
        runner._thread.join(timeout=3)

        callback.assert_not_called()
