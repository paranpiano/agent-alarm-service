"""Cloud Log Viewer entry point.

Usage:
    python main.py                  (inside the log_viewer folder)
    python -m log_viewer.main       (from the project root)
"""

import json
import logging
import os
import sys
import tkinter as tk

# log_viewer 폴더 안에서 직접 실행 시 경로 보정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui import CloudLogViewerGUI, NgAlertWindow

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_config.json")


def load_config() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = load_config()
    root = tk.Tk()

    if cfg.get("test_mode", False):
        # test_mode: show alert window immediately, skip full GUI
        root.withdraw()
        ng_equipments = cfg.get("test_mode_ng_equipments", ["TEST-EQ-01", "TEST-EQ-02"])
        position = cfg.get("alert_position", "right")
        try:
            ratio = float(cfg.get("alert_size_ratio", 0.25))
            ratio = max(0.1, min(0.9, ratio))
        except (ValueError, TypeError):
            ratio = 0.25
        logging.getLogger(__name__).info("[TEST MODE] ng_equipments=%s", ng_equipments)
        NgAlertWindow(root, ng_equipments, position, ratio, cfg=cfg)
    else:
        CloudLogViewerGUI(root)

    root.mainloop()


if __name__ == "__main__":
    main()
