"""Background NG Monitor - runs without a GUI; shows an alert window only when NG occurs.

Usage:
    python background_monitor.py                  (inside the log_viewer folder)
    python -m log_viewer.background_monitor       (from the project root)

config file: monitor_config.json
    - api_url        : API Gateway URL
    - interval_sec   : polling interval in seconds (default 30)
    - alert_position : alert window position (right/left/top/bottom)
    - alert_size_ratio: alert window size ratio (0.1 ~ 0.9)
    - days           : number of days to query (default 1)
"""

import json
import logging
import os
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

import requests

# Path correction when running directly inside the log_viewer folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import LogApiClient, DEFAULT_API_URL
from gui import NgAlertWindow

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_config.json")


def load_config() -> dict:
    """Load monitor_config.json. Returns defaults if the file is missing."""
    defaults = {
        "api_url": DEFAULT_API_URL,
        "interval_sec": 30,
        "alert_position": "right",
        "alert_size_ratio": 0.25,
        "days": 1,
        "no_update_alert_minutes": 60,
        "no_update_alert_enabled": True,
        "sns_api_url": "",
        "email_alert_enabled": True,
        "email_topic_arn": "",
        "sms_alert_enabled": False,
        "sms_topic_arn": "",
    }
    if not os.path.exists(_CONFIG_PATH):
        logger.warning("config file not found, using defaults: %s", _CONFIG_PATH)
        return defaults
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        defaults.update(data)
        return defaults
    except Exception as exc:
        logger.warning("config load failed (%s), using defaults", exc)
        return defaults


class BackgroundMonitor:
    """Background polling and NG alert window management."""

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._alert_win: NgAlertWindow | None = None
        self._last_seen_timestamp: str = ""
        self._active_ng_equipments: set[str] = set()     # equipment names currently in NG state
        self._last_update_time: datetime | None = None   # timestamp of the last received data
        self._no_update_alert_sent: bool = False          # deduplicates the no-update alert
        self._poll_job = None

        cfg = load_config()
        if cfg.get("test_mode", False):
            # test_mode: show alert window immediately with configured test equipments
            self._root.after(300, lambda: self._run_test_mode(cfg))
        else:
            # Start the first poll
            self._root.after(500, self._poll)

    def _run_test_mode(self, cfg: dict) -> None:
        """Show the alert window immediately using test_mode_ng_equipments from config."""
        ng_equipments = cfg.get("test_mode_ng_equipments", ["TEST-EQ-01", "TEST-EQ-02"])
        position = cfg.get("alert_position", "right")
        try:
            ratio = float(cfg.get("alert_size_ratio", 0.25))
            ratio = max(0.1, min(0.9, ratio))
        except (ValueError, TypeError):
            ratio = 0.25

        logger.info("[TEST MODE] Showing alert window with: %s", ng_equipments)
        self._active_ng_equipments = set(ng_equipments)
        if self._alert_win is None or self._alert_win._closed:
            self._alert_win = NgAlertWindow(self._root, sorted(ng_equipments), position, ratio, cfg=cfg)
        else:
            self._alert_win.update_message(sorted(ng_equipments))

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Reload config on every cycle so config changes take effect immediately."""
        cfg = load_config()
        client = LogApiClient(api_url=cfg["api_url"])
        days = max(1, int(cfg.get("days", 1)))
        today = date.today().strftime("%Y-%m-%d")

        def _fetch() -> None:
            try:
                if days == 1:
                    logs = client.get_logs(log_date=today)
                else:
                    logs = client.get_logs_range(days=days)
                self._root.after(0, lambda: self._on_loaded(logs, cfg))
            except Exception as exc:
                logger.error("Failed to fetch logs: %s", exc)
                self._root.after(0, lambda: self._schedule_next(cfg))

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_loaded(self, logs: list[dict], cfg: dict) -> None:
        logs = sorted(logs, key=lambda l: str(l.get("timestamp", "")), reverse=True)
        self._check_ng_alert(logs, cfg)
        self._check_no_update_alert(logs, cfg)
        self._schedule_next(cfg)

    def _schedule_next(self, cfg: dict) -> None:
        interval = max(5, int(cfg.get("interval_sec", 30))) * 1000  # milliseconds
        self._poll_job = self._root.after(interval, self._poll)

    # ------------------------------------------------------------------
    # NG alert window
    # ------------------------------------------------------------------

    def _check_ng_alert(self, logs: list[dict], cfg: dict) -> None:
        if not logs:
            self._close_alert()
            self._last_seen_timestamp = ""
            self._active_ng_equipments.clear()
            return

        # Extract only newly added entries
        if self._last_seen_timestamp:
            new_logs = [l for l in logs if str(l.get("timestamp", "")) > self._last_seen_timestamp]
        else:
            new_logs = logs  # first load: treat all entries as new

        self._last_seen_timestamp = str(logs[0].get("timestamp", ""))

        if not new_logs:
            return

        # New data arrived: update last-seen time and reset the no-update flag
        self._last_update_time = datetime.now(timezone.utc)
        self._no_update_alert_sent = False

        # Process oldest-first so the latest status per equipment wins
        for log in reversed(new_logs):
            status = log.get("status", "")
            eq_data = log.get("equipment_data") or {}
            eq_names = (
                list(eq_data.keys()) if eq_data
                else [log.get("image_name") or log.get("reason", "Unknown")]
            )
            if status == "NG":
                self._active_ng_equipments.update(eq_names)
            else:
                # OK / UNKNOWN / TIMEOUT: clear NG state for this equipment
                for name in eq_names:
                    self._active_ng_equipments.discard(name)

        if self._active_ng_equipments:
            position = cfg.get("alert_position", "right")
            try:
                ratio = float(cfg.get("alert_size_ratio", 0.25))
                ratio = max(0.1, min(0.9, ratio))
            except (ValueError, TypeError):
                ratio = 0.25

            ng_equipments = sorted(self._active_ng_equipments)
            if self._alert_win is None or self._alert_win._closed:
                self._alert_win = NgAlertWindow(self._root, ng_equipments, position, ratio, cfg=cfg)
            else:
                self._alert_win.update_message(ng_equipments)
        else:
            self._close_alert()

    def _close_alert(self) -> None:
        if self._alert_win is not None:
            self._alert_win.close()
            self._alert_win = None

    # ------------------------------------------------------------------
    # No-update detection and SNS notification
    # ------------------------------------------------------------------

    def _check_no_update_alert(self, logs: list[dict], cfg: dict) -> None:
        """Send an SNS alert when no new data has arrived for the configured threshold (default 60 min)."""
        if not cfg.get("no_update_alert_enabled", True):
            return

        threshold_minutes = int(cfg.get("no_update_alert_minutes", 60))

        # Skip if no data has been received yet (right after startup)
        if self._last_update_time is None:
            # Initialise the baseline if logs are already available
            if logs:
                self._last_update_time = datetime.now(timezone.utc)
            return

        elapsed_minutes = (datetime.now(timezone.utc) - self._last_update_time).total_seconds() / 60

        if elapsed_minutes >= threshold_minutes and not self._no_update_alert_sent:
            logger.warning("No new data for %.1f minutes - attempting SNS alert", elapsed_minutes)
            sent = self._send_no_update_sns(cfg, elapsed_minutes)
            if sent:
                self._no_update_alert_sent = True

    def _send_no_update_sns(self, cfg: dict, elapsed_minutes: float) -> bool:
        """Send a no-update alert via SNS API Gateway (email and SMS handled independently)."""
        api_url = cfg.get("sns_api_url", "")
        if not api_url:
            logger.warning("sns_api_url not configured - skipping alert")
            return False

        email_enabled = cfg.get("email_alert_enabled", True)
        sms_enabled   = cfg.get("sms_alert_enabled", False)

        if not email_enabled and not sms_enabled:
            logger.info("both email and SMS alerts disabled - skipping")
            return False

        now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
        last_str = (
            self._last_update_time.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
            if self._last_update_time else "N/A"
        )
        elapsed_int = int(elapsed_minutes)

        subject = f"[AI Alarm Service Off] No Data Update for {elapsed_int} Minutes"
        message = (
            f"AI Alarm Service has not received any new data for over {elapsed_int} minutes.\n"
            f"\n"
            f"Last Update   : {last_str}\n"
            f"Detected At   : {now_str}\n"
            f"Elapsed Time  : {elapsed_int} minutes\n"
            f"\n"
            f"Please check the AI Alarm Server and ensure it is running properly.\n"
            f"If the server has stopped, restart it immediately to resume monitoring.\n"
        )

        url = f"{api_url.rstrip('/')}?action=publishMessage"
        any_success = False

        # ── Email ──────────────────────────────────────────────
        if email_enabled:
            email_arn = cfg.get("email_topic_arn", "")
            if not email_arn:
                logger.warning("email_topic_arn not configured - skipping email alert")
            else:
                payload = {
                    "topicArn": email_arn,
                    "subject": subject,
                    "message": message,
                    "protocol": "email",
                }
                any_success = self._post_sns(url, payload, "email") or any_success

        # ── SMS ────────────────────────────────────────────────
        if sms_enabled:
            sms_arn = cfg.get("sms_topic_arn", "")
            if not sms_arn:
                logger.warning("sms_topic_arn not configured - skipping SMS alert")
            else:
                # SMS carries only the message body (no subject)
                sms_message = (
                    f"[AI Alarm Off] No data for {elapsed_int}min. "
                    f"Last: {last_str}. Check server immediately."
                )
                payload = {
                    "topicArn": sms_arn,
                    "message": sms_message,
                    "protocol": "sms",
                }
                any_success = self._post_sns(url, payload, "sms") or any_success

        return any_success

    def _post_sns(self, url: str, payload: dict, label: str) -> bool:
        """POST to the SNS API. Retries up to 3 times."""
        _MAX_RETRIES = 3
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                logger.info(
                    "[%s] SNS alert sent (attempt %d, messageId=%s)",
                    label, attempt, data.get("messageId", "unknown"),
                )
                return True
            except requests.RequestException as exc:
                logger.warning("[%s] SNS alert failed (attempt %d/%d): %s", label, attempt, _MAX_RETRIES, exc)
        logger.error("[%s] All %d SNS alert attempts failed", label, _MAX_RETRIES)
        return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = load_config()
    logger.info("Background monitor started (interval: %s sec)", cfg["interval_sec"])

    # Hide the main window - only the alert Toplevel is shown
    root = tk.Tk()
    root.withdraw()

    BackgroundMonitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
