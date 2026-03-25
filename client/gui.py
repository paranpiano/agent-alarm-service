"""tkinter GUI for the AI Alarm System Mock Tester.

Provides:
- AlarmTestGUI: Main application window for testing image analysis
  against the AI Alarm System server.
"""

import logging
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Optional

from client.api_client import AlarmApiClient
from client.models import JudgmentResult, JudgmentStatus
from client.periodic_runner import PeriodicRunner

logger = logging.getLogger(__name__)

# Image file extensions supported by the server
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# Expected result folder names
_EXPECTED_FOLDERS = {"ok", "ng", "unknown"}


class AlarmTestGUI:
    """Main tkinter GUI for the AI Alarm System POC Mock Tester.

    The window layout:
    - Top bar: server URL entry, health-check button, status indicator
    - Left panel: folder browser tree (test_images/ subfolders)
    - Right panel: results Treeview table
    - Bottom bar: Analyze button, periodic start/stop, interval dropdown
    """

    _DEFAULT_URL = "http://localhost:8000"
    _INTERVAL_OPTIONS = ["5s", "10s"]

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AI Alarm System - Mock Tester")
        self.root.geometry("1100x700")
        self.root.minsize(900, 500)

        # State
        self._api_client: Optional[AlarmApiClient] = None
        self._periodic_runner: Optional[PeriodicRunner] = None
        self._test_root: Optional[Path] = None
        # list of (image_path, expected_status_str)
        self._image_list: list[tuple[Path, str]] = []
        self._history: list[dict] = []

        self._build_ui()
        self._apply_tags()

        # Initialise API client with default URL
        self._update_api_client()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct all widgets."""
        self._build_top_bar()
        self._build_main_area()
        self._build_bottom_bar()

    def _build_top_bar(self) -> None:
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Server URL:").pack(side=tk.LEFT)
        self._url_var = tk.StringVar(value=self._DEFAULT_URL)
        url_entry = ttk.Entry(top, textvariable=self._url_var, width=35)
        url_entry.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Button(top, text="Health Check", command=self._on_health_check).pack(
            side=tk.LEFT
        )
        self._health_label = ttk.Label(top, text="  --  ", width=12)
        self._health_label.pack(side=tk.LEFT, padx=4)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(top, text="Browse Folder...", command=self._on_browse_folder).pack(
            side=tk.LEFT
        )
        self._folder_label = ttk.Label(top, text="(no folder selected)")
        self._folder_label.pack(side=tk.LEFT, padx=4)

    def _build_main_area(self) -> None:
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Left panel: image tree ---
        left_frame = ttk.LabelFrame(paned, text="Test Images", padding=4)
        self._image_tree = ttk.Treeview(
            left_frame, columns=("expected",), show="tree headings", height=20
        )
        self._image_tree.heading("#0", text="Image")
        self._image_tree.heading("expected", text="Expected")
        self._image_tree.column("#0", width=180)
        self._image_tree.column("expected", width=70, anchor=tk.CENTER)

        img_scroll = ttk.Scrollbar(
            left_frame, orient=tk.VERTICAL, command=self._image_tree.yview
        )
        self._image_tree.configure(yscrollcommand=img_scroll.set)
        self._image_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        img_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        paned.add(left_frame, weight=1)

        # --- Right panel: results table + history ---
        right_frame = ttk.Frame(paned, padding=4)

        # Results table
        res_label = ttk.LabelFrame(right_frame, text="Results", padding=4)
        res_label.pack(fill=tk.BOTH, expand=True)

        result_cols = ("expected", "actual", "match", "reason", "time_ms")
        self._result_tree = ttk.Treeview(
            res_label, columns=result_cols, show="headings", height=12
        )
        self._result_tree.heading("expected", text="Expected")
        self._result_tree.heading("actual", text="Actual")
        self._result_tree.heading("match", text="Match")
        self._result_tree.heading("reason", text="Reason")
        self._result_tree.heading("time_ms", text="Time(ms)")

        self._result_tree.column("expected", width=70, anchor=tk.CENTER)
        self._result_tree.column("actual", width=70, anchor=tk.CENTER)
        self._result_tree.column("match", width=50, anchor=tk.CENTER)
        self._result_tree.column("reason", width=300)
        self._result_tree.column("time_ms", width=70, anchor=tk.E)

        res_scroll = ttk.Scrollbar(
            res_label, orient=tk.VERTICAL, command=self._result_tree.yview
        )
        self._result_tree.configure(yscrollcommand=res_scroll.set)
        self._result_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        res_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # History table
        hist_label = ttk.LabelFrame(right_frame, text="Recent History", padding=4)
        hist_label.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        hist_cols = ("time", "image", "status", "time_ms")
        self._history_tree = ttk.Treeview(
            hist_label, columns=hist_cols, show="headings", height=6
        )
        self._history_tree.heading("time", text="Time")
        self._history_tree.heading("image", text="Image")
        self._history_tree.heading("status", text="Status")
        self._history_tree.heading("time_ms", text="Time(ms)")

        self._history_tree.column("time", width=140)
        self._history_tree.column("image", width=160)
        self._history_tree.column("status", width=80, anchor=tk.CENTER)
        self._history_tree.column("time_ms", width=70, anchor=tk.E)

        hist_scroll = ttk.Scrollbar(
            hist_label, orient=tk.VERTICAL, command=self._history_tree.yview
        )
        self._history_tree.configure(yscrollcommand=hist_scroll.set)
        self._history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hist_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        paned.add(right_frame, weight=3)

    def _build_bottom_bar(self) -> None:
        bottom = ttk.Frame(self.root, padding=5)
        bottom.pack(fill=tk.X)

        self._analyze_btn = ttk.Button(
            bottom, text="Analyze All", command=self._on_analyze_all
        )
        self._analyze_btn.pack(side=tk.LEFT)

        ttk.Separator(bottom, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=10
        )

        ttk.Label(bottom, text="Periodic:").pack(side=tk.LEFT)
        self._interval_var = tk.StringVar(value=self._INTERVAL_OPTIONS[0])
        interval_combo = ttk.Combobox(
            bottom,
            textvariable=self._interval_var,
            values=self._INTERVAL_OPTIONS,
            state="readonly",
            width=5,
        )
        interval_combo.pack(side=tk.LEFT, padx=4)

        self._periodic_btn = ttk.Button(
            bottom, text="Start Periodic", command=self._on_toggle_periodic
        )
        self._periodic_btn.pack(side=tk.LEFT, padx=4)

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self._status_var).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Treeview colour tags
    # ------------------------------------------------------------------

    def _apply_tags(self) -> None:
        """Configure colour tags on the results Treeview."""
        self._result_tree.tag_configure("ok_match", background="#c8f7c8")
        self._result_tree.tag_configure("ng_match", background="#f7c8c8")
        self._result_tree.tag_configure("unknown_match", background="#f7f0c8")
        self._result_tree.tag_configure("timeout", background="#d0d0d0")
        self._result_tree.tag_configure("mismatch", foreground="#cc0000")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _update_api_client(self) -> None:
        url = self._url_var.get().strip()
        if not url:
            url = self._DEFAULT_URL
        self._api_client = AlarmApiClient(base_url=url)

    def _on_health_check(self) -> None:
        self._update_api_client()
        assert self._api_client is not None

        def _check() -> None:
            try:
                ok = self._api_client.health_check()
                text = "OK" if ok else "FAIL"
            except Exception:
                text = "ERROR"
            self.root.after(0, lambda: self._health_label.configure(text=f"  {text}  "))

        threading.Thread(target=_check, daemon=True).start()

    def _on_browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select test_images root folder")
        if not folder:
            return
        self._test_root = Path(folder)
        self._folder_label.configure(text=str(self._test_root))
        self._scan_images()

    def _scan_images(self) -> None:
        """Scan test_images/ subfolders and populate the image tree."""
        self._image_tree.delete(*self._image_tree.get_children())
        self._image_list.clear()

        if self._test_root is None or not self._test_root.is_dir():
            return

        for subfolder_name in sorted(_EXPECTED_FOLDERS):
            subfolder = self._test_root / subfolder_name
            if not subfolder.is_dir():
                continue
            parent_id = self._image_tree.insert(
                "", tk.END, text=subfolder_name, values=(subfolder_name,), open=True
            )
            for img_path in sorted(subfolder.iterdir()):
                if img_path.suffix.lower() in _IMAGE_EXTENSIONS:
                    self._image_tree.insert(
                        parent_id,
                        tk.END,
                        text=img_path.name,
                        values=(subfolder_name,),
                    )
                    self._image_list.append((img_path, subfolder_name))

    def _on_analyze_all(self) -> None:
        if not self._image_list:
            self._status_var.set("No images loaded")
            return
        self._update_api_client()
        self._status_var.set("Analyzing...")
        self._analyze_btn.configure(state=tk.DISABLED)
        threading.Thread(target=self._run_analyze_all, daemon=True).start()

    def _run_analyze_all(self) -> None:
        """Run analysis for every loaded image (background thread)."""
        assert self._api_client is not None
        results: list[tuple[str, str, JudgmentResult | None, str | None]] = []

        for image_path, expected in self._image_list:
            try:
                result = self._api_client.analyze_single(image_path)
                results.append((image_path.name, expected, result, None))
            except Exception as exc:
                results.append((image_path.name, expected, None, str(exc)))

        self.root.after(0, lambda: self._display_results(results))

    def _display_results(
        self,
        results: list[tuple[str, str, JudgmentResult | None, str | None]],
    ) -> None:
        """Populate the results Treeview from analysis results (main thread)."""
        self._result_tree.delete(*self._result_tree.get_children())

        for image_name, expected, result, error in results:
            if result is not None:
                actual = result.status.value
                match_ok = actual.upper() == expected.upper()
                match_str = "\u2713" if match_ok else "\u2717"
                reason = result.reason
                time_ms = str(result.processing_time_ms)
                tag = self._tag_for(result.status, match_ok)
            else:
                actual = "ERROR"
                match_str = "\u2717"
                reason = error or "Unknown error"
                time_ms = "--"
                tag = "mismatch"

            self._result_tree.insert(
                "",
                tk.END,
                text=image_name,
                values=(expected, actual, match_str, reason, time_ms),
                tags=(tag,),
            )

            # Add to history
            self._add_history(image_name, actual, time_ms)

        self._status_var.set(f"Done - {len(results)} images analyzed")
        self._analyze_btn.configure(state=tk.NORMAL)

    # ------------------------------------------------------------------
    # Periodic mode
    # ------------------------------------------------------------------

    def _on_toggle_periodic(self) -> None:
        if self._periodic_runner and self._periodic_runner.is_running:
            self._stop_periodic()
        else:
            self._start_periodic()

    def _start_periodic(self) -> None:
        if not self._image_list:
            self._status_var.set("No images loaded")
            return

        self._update_api_client()
        assert self._api_client is not None

        interval_str = self._interval_var.get()
        interval = int(interval_str.replace("s", ""))

        self._periodic_runner = PeriodicRunner(
            api_client=self._api_client, interval_seconds=interval
        )

        # Use the first image for periodic analysis
        image_path = self._image_list[0][0]
        self._periodic_runner.start(image_path, self._periodic_callback)

        self._periodic_btn.configure(text="Stop Periodic")
        self._status_var.set(f"Periodic running ({interval}s)")

    def _stop_periodic(self) -> None:
        if self._periodic_runner:
            self._periodic_runner.stop()
        self._periodic_btn.configure(text="Start Periodic")
        self._status_var.set("Periodic stopped")

    def _periodic_callback(self, result: JudgmentResult) -> None:
        """Called from the PeriodicRunner background thread."""
        self.root.after(0, lambda: self._handle_periodic_result(result))

    def _handle_periodic_result(self, result: JudgmentResult) -> None:
        """Display a single periodic result (main thread)."""
        image_name = result.image_name or "periodic"
        actual = result.status.value
        time_ms = str(result.processing_time_ms)
        self._add_history(image_name, actual, time_ms)
        self._status_var.set(
            f"Periodic: {actual} ({result.processing_time_ms}ms)"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tag_for(status: JudgmentStatus, match_ok: bool) -> str:
        """Return the Treeview tag name for a given status and match result."""
        if status == JudgmentStatus.TIMEOUT:
            return "timeout"
        if not match_ok:
            return "mismatch"
        if status == JudgmentStatus.OK:
            return "ok_match"
        if status == JudgmentStatus.NG:
            return "ng_match"
        # UNKNOWN
        return "unknown_match"

    def _add_history(self, image_name: str, status: str, time_ms: str) -> None:
        """Insert a row at the top of the history table (max 50 rows)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._history_tree.insert(
            "", 0, values=(now, image_name, status, time_ms)
        )
        # Keep history bounded
        children = self._history_tree.get_children()
        if len(children) > 50:
            self._history_tree.delete(children[-1])
