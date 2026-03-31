"""Cloud Log Viewer 진입점.

실행:
    python main.py                  (log_viewer 폴더 안에서)
    python -m log_viewer.main       (프로젝트 루트에서)
"""

import logging
import sys
import os
import tkinter as tk

# log_viewer 폴더 안에서 직접 실행 시 경로 보정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui import CloudLogViewerGUI


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    root = tk.Tk()
    CloudLogViewerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
