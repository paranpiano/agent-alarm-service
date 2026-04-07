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
from datetime import date

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
