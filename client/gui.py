"""tkinter GUI for the AI Alarm System Mock Tester.

Layout:
- Top bar: Server URL, auto health-check indicator, status
- Tab 1 (Analysis): Left=image list, Center=image preview, Right=result detail
- Tab 2 (History): Full-width recent history table
- Bottom bar: Analyze All, Periodic controls
"""

import logging
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Optional

from PIL import Image, ImageTk  # type: ignore[import-untyped]

from client.api_client import AlarmApiClient
from client.history_logger import HistoryLogger
from client.models import JudgmentResult, JudgmentStatus
from client.periodic_runner import PeriodicRunner

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_EXPECTED_FOLDERS = {"ok", "ng", "unknown"}

# Default test_images path relative to workspace root
_DEFAULT_TEST_IMAGES = Path(__file__).resolve().parent.parent / "test_images"


class AlarmTestGUI:
    """Main tkinter GUI for the AI Alarm System POC Mock Tester."""

    _DEFAULT_URL = "http://localhost:8000"
    _INTERVAL_OPTIONS = ["5s", "10s"]

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AI Alarm System - Mock Tester")
        self.root.geometry("1200x750")
        self.root.minsize(1000, 600)

        # State
        self._api_client: Optional[AlarmApiClient] = None
        self._periodic_runner: Optional[PeriodicRunner] = None
        self._test_root: Optional[Path] = None
        self._image_list: list[tuple[Path, str]] = []
        self._current_photo: Optional[ImageTk.PhotoImage] = None
        self._results: list[tuple[str, str, JudgmentResult | None, str | None]] = []

        self._history_logger = HistoryLogger()

        self._build_ui()
        self._apply_tags()
        self._update_api_client()

        # Auto-load test_images folder if it exists
        if _DEFAULT_TEST_IMAGES.is_dir():
            self._test_root = _DEFAULT_TEST_IMAGES
            self._scan_images()

        # Auto health check on startup
        self.root.after(500, self._on_health_check)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_top_bar()
        self._build_notebook()
        self._build_bottom_bar()

    def _build_top_bar(self) -> None:
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Server URL:").pack(side=tk.LEFT)
        self._url_var = tk.StringVar(value=self._DEFAULT_URL)
        ttk.Entry(top, textvariable=self._url_var, width=30).pack(side=tk.LEFT, padx=(4, 8))

        ttk.Button(top, text="Health Check", command=self._on_health_check).pack(side=tk.LEFT)
        self._health_label = ttk.Label(top, text="  --  ", width=10)
        self._health_label.pack(side=tk.LEFT, padx=4)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(top, text="Browse Folder...", command=self._on_browse_folder).pack(side=tk.LEFT)
        self._folder_label = ttk.Label(top, text=str(_DEFAULT_TEST_IMAGES) if _DEFAULT_TEST_IMAGES.is_dir() else "(no folder)")
        self._folder_label.pack(side=tk.LEFT, padx=4)

    def _build_notebook(self) -> None:
        self._notebook = ttk.Notebook(self.root)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab 1: Analysis
        self._analysis_frame = ttk.Frame(self._notebook)
        self._notebook.add(self._analysis_frame, text="  Analysis  ")
        self._build_analysis_tab()

        # Tab 2: History
        self._history_frame = ttk.Frame(self._notebook)
        self._notebook.add(self._history_frame, text="  History  ")
        self._build_history_tab()

    def _build_analysis_tab(self) -> None:
        paned = ttk.PanedWindow(self._analysis_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: image list
        left = ttk.LabelFrame(paned, text="Test Images", padding=4)
        self._image_tree = ttk.Treeview(left, columns=("expected",), show="tree headings", height=20)
        self._image_tree.heading("#0", text="Image")
        self._image_tree.heading("expected", text="Expected")
        self._image_tree.column("#0", width=160)
        self._image_tree.column("expected", width=65, anchor=tk.CENTER)
        self._image_tree.bind("<<TreeviewSelect>>", self._on_image_select)

        img_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self._image_tree.yview)
        self._image_tree.configure(yscrollcommand=img_scroll.set)
        self._image_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        img_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        paned.add(left, weight=1)

        # Center + Right: image preview + result detail
        right = ttk.Frame(paned, padding=4)

        # Image preview area
        preview_frame = ttk.LabelFrame(right, text="Image Preview", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self._preview_canvas = tk.Canvas(preview_frame, bg="#2b2b2b", highlightthickness=0)
        self._preview_canvas.pack(fill=tk.BOTH, expand=True)

        # Result detail area
        result_frame = ttk.LabelFrame(right, text="Analysis Result", padding=4)
        result_frame.pack(fill=tk.X, pady=(4, 0))

        detail_grid = ttk.Frame(result_frame)
        detail_grid.pack(fill=tk.X)

        labels = ["Image:", "Expected:", "Actual:", "Match:", "Time(ms):", "Reason:"]
        self._detail_vars = {}
        for i, label_text in enumerate(labels):
            ttk.Label(detail_grid, text=label_text, font=("", 9, "bold")).grid(row=i, column=0, sticky=tk.W, padx=(0, 8), pady=1)
            var = tk.StringVar(value="--")
            lbl = ttk.Label(detail_grid, textvariable=var, wraplength=500, anchor=tk.W)
            lbl.grid(row=i, column=1, sticky=tk.W, pady=1)
            self._detail_vars[label_text] = (var, lbl)

        # Status indicator for the selected result
        self._result_status_var = tk.StringVar(value="")
        self._result_status_label = ttk.Label(result_frame, textvariable=self._result_status_var, font=("", 11, "bold"))
        self._result_status_label.pack(anchor=tk.W, pady=(4, 0))

        paned.add(right, weight=3)

    def _build_history_tab(self) -> None:
        hist_cols = ("time", "image", "expected", "actual", "match", "reason", "time_ms")
        self._history_tree = ttk.Treeview(self._history_frame, columns=hist_cols, show="headings", height=25)
        self._history_tree.heading("time", text="Time")
        self._history_tree.heading("image", text="Image")
        self._history_tree.heading("expected", text="Expected")
        self._history_tree.heading("actual", text="Actual")
        self._history_tree.heading("match", text="Match")
        self._history_tree.heading("reason", text="Reason")
        self._history_tree.heading("time_ms", text="Time(ms)")

        self._history_tree.column("time", width=140)
        self._history_tree.column("image", width=140)
        self._history_tree.column("expected", width=70, anchor=tk.CENTER)
        self._history_tree.column("actual", width=70, anchor=tk.CENTER)
        self._history_tree.column("match", width=50, anchor=tk.CENTER)
        self._history_tree.column("reason", width=400)
        self._history_tree.column("time_ms", width=70, anchor=tk.E)

        hist_scroll = ttk.Scrollbar(self._history_frame, orient=tk.VERTICAL, command=self._history_tree.yview)
        self._history_tree.configure(yscrollcommand=hist_scroll.set)
        self._history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hist_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._apply_history_tags()

    def _build_bottom_bar(self) -> None:
        bottom = ttk.Frame(self.root, padding=5)
        bottom.pack(fill=tk.X)

        self._analyze_btn = ttk.Button(bottom, text="Analyze All", command=self._on_analyze_all)
        self._analyze_btn.pack(side=tk.LEFT)

        ttk.Separator(bottom, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(bottom, text="Periodic:").pack(side=tk.LEFT)
        self._interval_var = tk.StringVar(value=self._INTERVAL_OPTIONS[0])
        ttk.Combobox(bottom, textvariable=self._interval_var, values=self._INTERVAL_OPTIONS, state="readonly", width=5).pack(side=tk.LEFT, padx=4)

        self._periodic_btn = ttk.Button(bottom, text="Start Periodic", command=self._on_toggle_periodic)
        self._periodic_btn.pack(side=tk.LEFT, padx=4)

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self._status_var).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def _apply_tags(self) -> None:
        pass  # Image tree doesn't need color tags

    def _apply_history_tags(self) -> None:
        self._history_tree.tag_configure("ok_match", background="#c8f7c8")
        self._history_tree.tag_configure("ng_match", background="#f7c8c8")
        self._history_tree.tag_configure("unknown_match", background="#f7f0c8")
        self._history_tree.tag_configure("timeout", background="#d0d0d0")
        self._history_tree.tag_configure("mismatch", foreground="#cc0000")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _update_api_client(self) -> None:
        url = self._url_var.get().strip() or self._DEFAULT_URL
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
        self._image_tree.delete(*self._image_tree.get_children())
        self._image_list.clear()
        self._results.clear()

        if self._test_root is None or not self._test_root.is_dir():
            return

        for subfolder_name in sorted(_EXPECTED_FOLDERS):
            subfolder = self._test_root / subfolder_name
            if not subfolder.is_dir():
                continue
            parent_id = self._image_tree.insert("", tk.END, text=subfolder_name, values=(subfolder_name,), open=True)
            for img_path in sorted(subfolder.iterdir()):
                if img_path.suffix.lower() in _IMAGE_EXTENSIONS:
                    self._image_tree.insert(parent_id, tk.END, text=img_path.name, values=(subfolder_name,))
                    self._image_list.append((img_path, subfolder_name))

    def _on_image_select(self, event=None) -> None:
        selection = self._image_tree.selection()
        if not selection:
            return

        item = selection[0]
        item_text = self._image_tree.item(item, "text")
        parent = self._image_tree.parent(item)

        if not parent:
            return  # Clicked on folder node, not image

        expected = self._image_tree.item(item, "values")[0]

        # Find the image path
        image_path = None
        for path, exp in self._image_list:
            if path.name == item_text and exp == expected:
                image_path = path
                break

        if image_path is None:
            return

        # Show image preview
        self._show_image_preview(image_path)

        # Show result detail if available
        self._show_result_detail(item_text, expected)

    def _show_image_preview(self, image_path: Path) -> None:
        try:
            img = Image.open(image_path)
            canvas_w = self._preview_canvas.winfo_width()
            canvas_h = self._preview_canvas.winfo_height()

            if canvas_w < 10 or canvas_h < 10:
                canvas_w, canvas_h = 600, 400

            ratio = min(canvas_w / img.width, canvas_h / img.height)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)

            self._current_photo = ImageTk.PhotoImage(img)
            self._preview_canvas.delete("all")
            self._preview_canvas.create_image(canvas_w // 2, canvas_h // 2, image=self._current_photo, anchor=tk.CENTER)
        except Exception as exc:
            logger.warning("Failed to load image preview: %s", exc)
            self._preview_canvas.delete("all")
            self._preview_canvas.create_text(300, 200, text=f"Cannot load image:\n{exc}", fill="white")

    def _show_result_detail(self, image_name: str, expected: str) -> None:
        # Find matching result
        result_entry = None
        for name, exp, res, err in self._results:
            if name == image_name and exp == expected:
                result_entry = (name, exp, res, err)
                break

        if result_entry is None:
            for key, (var, _) in self._detail_vars.items():
                var.set("--")
            self._result_status_var.set("Not analyzed yet")
            return

        name, exp, result, error = result_entry
        self._detail_vars["Image:"][0].set(name)
        self._detail_vars["Expected:"][0].set(exp.upper())

        if result is not None:
            actual = result.status.value
            match_ok = actual.upper() == exp.upper()
            self._detail_vars["Actual:"][0].set(actual)
            self._detail_vars["Match:"][0].set("\u2713 Match" if match_ok else "\u2717 Mismatch")
            self._detail_vars["Time(ms):"][0].set(str(result.processing_time_ms))
            self._detail_vars["Reason:"][0].set(result.reason)

            if result.status == JudgmentStatus.TIMEOUT:
                self._result_status_var.set("\u23f1 TIMEOUT")
            elif match_ok:
                status_text = {"OK": "\u2705 OK", "NG": "\ud83d\udea8 NG", "UNKNOWN": "\u2753 UNKNOWN"}.get(actual, actual)
                self._result_status_var.set(status_text)
            else:
                self._result_status_var.set(f"\u274c MISMATCH (expected {exp.upper()}, got {actual})")
        else:
            self._detail_vars["Actual:"][0].set("ERROR")
            self._detail_vars["Match:"][0].set("\u2717")
            self._detail_vars["Time(ms):"][0].set("--")
            self._detail_vars["Reason:"][0].set(error or "Unknown error")
            self._result_status_var.set("\u274c ERROR")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _on_analyze_all(self) -> None:
        if not self._image_list:
            self._status_var.set("No images loaded")
            return
        self._update_api_client()
        self._status_var.set("Analyzing...")
        self._analyze_btn.configure(state=tk.DISABLED)
        threading.Thread(target=self._run_analyze_all, daemon=True).start()

    def _run_analyze_all(self) -> None:
        assert self._api_client is not None
        results: list[tuple[str, str, JudgmentResult | None, str | None]] = []

        for image_path, expected in self._image_list:
            try:
                result = self._api_client.analyze_single(image_path)
                results.append((image_path.name, expected, result, None))
            except Exception as exc:
                results.append((image_path.name, expected, None, str(exc)))

        self.root.after(0, lambda: self._on_analysis_complete(results))

    def _on_analysis_complete(self, results: list[tuple[str, str, JudgmentResult | None, str | None]]) -> None:
        self._results = results

        # Add to history
        for name, expected, result, error in results:
            self._add_history(name, expected, result, error)

        self._status_var.set(f"Done - {len(results)} images analyzed")
        self._analyze_btn.configure(state=tk.NORMAL)

        # Auto-select first image to show result
        children = self._image_tree.get_children()
        if children:
            first_child_children = self._image_tree.get_children(children[0])
            if first_child_children:
                self._image_tree.selection_set(first_child_children[0])
                self._on_image_select()

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

        interval = int(self._interval_var.get().replace("s", ""))
        self._periodic_runner = PeriodicRunner(api_client=self._api_client, interval_seconds=interval)

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
        self.root.after(0, lambda: self._handle_periodic_result(result))

    def _handle_periodic_result(self, result: JudgmentResult) -> None:
        image_name = result.image_name or "periodic"
        # Look up expected value from the image list by matching image name
        expected = "?"
        for path, exp in self._image_list:
            if path.name == image_name:
                expected = exp
                break
        self._add_history(image_name, expected, result, None)
        self._status_var.set(f"Periodic: {result.status.value} ({result.processing_time_ms}ms)")

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _add_history(self, image_name: str, expected: str, result: JudgmentResult | None, error: str | None) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

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

        self._history_tree.insert(
            "", 0,
            values=(now, image_name, expected.upper(), actual, match_str, reason, time_ms),
            tags=(tag,),
        )

        # Keep bounded at 100
        children = self._history_tree.get_children()
        if len(children) > 100:
            self._history_tree.delete(children[-1])

        # Log to CSV
        self._history_logger.log_result(
            image_name=image_name,
            expected=expected.upper(),
            actual=actual,
            match=match_str == "\u2713",
            reason=reason,
            time_ms=time_ms,
        )

    @staticmethod
    def _tag_for(status: JudgmentStatus, match_ok: bool) -> str:
        if status == JudgmentStatus.TIMEOUT:
            return "timeout"
        if not match_ok:
            return "mismatch"
        if status == JudgmentStatus.OK:
            return "ok_match"
        if status == JudgmentStatus.NG:
            return "ng_match"
        return "unknown_match"
