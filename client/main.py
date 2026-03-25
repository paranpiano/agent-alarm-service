"""Entry point for the AI Alarm System Mock Tester GUI.

Usage:
    python -m client.main
"""

import logging
import tkinter as tk

from client.gui import AlarmTestGUI


def main() -> None:
    """Launch the Mock Tester GUI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    root = tk.Tk()
    AlarmTestGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
