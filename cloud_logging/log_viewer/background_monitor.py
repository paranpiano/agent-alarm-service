"""백그라운드 NG 모니터 - GUI 없이 실행, NG 발생 시 경고창만 표시.

실행:
    python background_monitor.py                  (log_viewer 폴더 안에서)
    python -m log_viewer.background_monitor       (프로젝트 루트에서)

config 파일: monitor_config.json
    - api_url        : API Gateway URL
    - interval_sec   : 폴링 주기 (기본 30초)
    - alert_position : 경고창 위치 (우측/좌측/상단/하단)
    - alert_size_ratio: 경고창 크기 비율 (0.1 ~ 0.9)
    - days           : 조회 일수 (기본 1)
"""

import json
import logging
import os
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timezone

import requests

# log_viewer 폴더 안에서 직접 실행 시 경로 보정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import LogApiClient, DEFAULT_API_URL
from gui import NgAlertWindow

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_config.json")


def load_config() -> dict:
    """monitor_config.json 로드. 파일 없으면 기본값 반환."""
    defaults = {
        "api_url": DEFAULT_API_URL,
        "interval_sec": 30,
        "alert_position": "우측",
        "alert_size_ratio": 0.25,
        "days": 1,
        "no_update_alert_minutes": 60,
        "no_update_alert_enabled": True,
        "sns_enabled": True,
        "sns_api_url": "",
        "sns_topic_arn": "",
        "sns_protocol": "email",
    }
    if not os.path.exists(_CONFIG_PATH):
        logger.warning("config 파일 없음, 기본값 사용: %s", _CONFIG_PATH)
        return defaults
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        defaults.update(data)
        return defaults
    except Exception as exc:
        logger.warning("config 로드 실패 (%s), 기본값 사용", exc)
        return defaults


class BackgroundMonitor:
    """백그라운드 폴링 + NG 경고창 관리."""

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._alert_win: NgAlertWindow | None = None
        self._last_seen_timestamp: str = ""
        self._last_update_time: datetime | None = None   # 마지막으로 새 데이터가 온 시각
        self._no_update_alert_sent: bool = False          # 무업데이트 알림 중복 방지
        self._poll_job = None

        # 최초 폴링 시작
        self._root.after(500, self._poll)

    # ------------------------------------------------------------------
    # 폴링
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """config를 매번 다시 읽어 설정 변경을 즉시 반영."""
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
                logger.error("로그 조회 실패: %s", exc)
                self._root.after(0, lambda: self._schedule_next(cfg))

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_loaded(self, logs: list[dict], cfg: dict) -> None:
        logs = sorted(logs, key=lambda l: str(l.get("timestamp", "")), reverse=True)
        self._check_ng_alert(logs, cfg)
        self._check_no_update_alert(logs, cfg)
        self._schedule_next(cfg)

    def _schedule_next(self, cfg: dict) -> None:
        interval = max(5, int(cfg.get("interval_sec", 30))) * 1000  # ms
        self._poll_job = self._root.after(interval, self._poll)

    # ------------------------------------------------------------------
    # NG 알림 창
    # ------------------------------------------------------------------

    def _check_ng_alert(self, logs: list[dict], cfg: dict) -> None:
        if not logs:
            self._close_alert()
            self._last_seen_timestamp = ""
            return

        # 새로 갱신된 항목만 추출
        if self._last_seen_timestamp:
            new_logs = [l for l in logs if str(l.get("timestamp", "")) > self._last_seen_timestamp]
        else:
            new_logs = logs  # 최초 로드 시 전체 대상

        self._last_seen_timestamp = str(logs[0].get("timestamp", ""))

        if not new_logs:
            return

        # 새 데이터가 있으면 마지막 업데이트 시각 갱신 + 무업데이트 알림 플래그 초기화
        self._last_update_time = datetime.now(timezone.utc)
        self._no_update_alert_sent = False

        ng_logs = [l for l in new_logs if l.get("status") == "NG"]

        if ng_logs:
            eq_names: list[str] = []
            for l in ng_logs:
                eq_data = l.get("equipment_data") or {}
                if eq_data:
                    eq_names.extend(eq_data.keys())
                else:
                    eq_names.append(l.get("reason", "NG 발생"))

            # 중복 제거, 순서 유지
            seen: set[str] = set()
            ng_equipments = [x for x in eq_names if not (x in seen or seen.add(x))]

            position = cfg.get("alert_position", "우측")
            try:
                ratio = float(cfg.get("alert_size_ratio", 0.25))
                ratio = max(0.1, min(0.9, ratio))
            except (ValueError, TypeError):
                ratio = 0.25

            if self._alert_win is None or self._alert_win._closed:
                self._alert_win = NgAlertWindow(self._root, ng_equipments, position, ratio)
            else:
                self._alert_win.update_message(ng_equipments)
        else:
            self._close_alert()

    def _close_alert(self) -> None:
        if self._alert_win is not None:
            self._alert_win.close()
            self._alert_win = None

    # ------------------------------------------------------------------
    # 무업데이트 감지 및 SNS 알림
    # ------------------------------------------------------------------

    def _check_no_update_alert(self, logs: list[dict], cfg: dict) -> None:
        """마지막 데이터 수신 후 설정 시간(기본 60분) 이상 업데이트 없으면 SNS 알림 발송."""
        if not cfg.get("no_update_alert_enabled", True):
            return

        threshold_minutes = int(cfg.get("no_update_alert_minutes", 60))

        # 아직 한 번도 데이터를 받지 못한 경우 (최초 기동 직후) 는 스킵
        if self._last_update_time is None:
            # 로그가 있으면 지금을 기준으로 초기화
            if logs:
                self._last_update_time = datetime.now(timezone.utc)
            return

        elapsed_minutes = (datetime.now(timezone.utc) - self._last_update_time).total_seconds() / 60

        if elapsed_minutes >= threshold_minutes and not self._no_update_alert_sent:
            logger.warning("%.1f분 동안 새 데이터 없음 - SNS 알림 발송 시도", elapsed_minutes)
            sent = self._send_no_update_sns(cfg, elapsed_minutes)
            if sent:
                self._no_update_alert_sent = True

    def _send_no_update_sns(self, cfg: dict, elapsed_minutes: float) -> bool:
        """SNS API Gateway를 통해 무업데이트 알림 이메일 발송."""
        sns_enabled = cfg.get("sns_enabled", True)
        api_url = cfg.get("sns_api_url", "")
        topic_arn = cfg.get("sns_topic_arn", "")
        protocol = cfg.get("sns_protocol", "email")

        if not sns_enabled:
            logger.info("SNS 비활성화 상태 - 무업데이트 알림 스킵")
            return False

        if not api_url or not topic_arn:
            logger.warning("SNS 설정 누락 (sns_api_url / sns_topic_arn) - 알림 스킵")
            return False

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        last_str = (
            self._last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            if self._last_update_time
            else "N/A"
        )

        subject = f"[AI Alarm Service Off] No Data Update for {int(elapsed_minutes)} Minutes"
        message = (
            f"AI Alarm Service has not received any new data for over {int(elapsed_minutes)} minutes.\n"
            f"\n"
            f"Last Update   : {last_str}\n"
            f"Detected At   : {now_str}\n"
            f"Elapsed Time  : {int(elapsed_minutes)} minutes\n"
            f"\n"
            f"Please check the AI Alarm Server and ensure it is running properly.\n"
            f"If the server has stopped, restart it immediately to resume monitoring.\n"
        )

        payload = {
            "topicArn": topic_arn,
            "subject": subject,
            "message": message,
            "protocol": protocol,
        }
        url = f"{api_url.rstrip('/')}?action=publishMessage"

        _MAX_RETRIES = 3
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                logger.info(
                    "무업데이트 SNS 알림 발송 성공 (attempt %d, messageId=%s)",
                    attempt,
                    data.get("messageId", "unknown"),
                )
                return True
            except requests.RequestException as exc:
                logger.warning("SNS 알림 발송 실패 (attempt %d/%d): %s", attempt, _MAX_RETRIES, exc)

        logger.error("SNS 알림 발송 %d회 모두 실패", _MAX_RETRIES)
        return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = load_config()
    logger.info("백그라운드 모니터 시작 (주기: %s초)", cfg["interval_sec"])

    # 메인 윈도우는 숨김 - 경고창(Toplevel)만 표시됨
    root = tk.Tk()
    root.withdraw()

    BackgroundMonitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
