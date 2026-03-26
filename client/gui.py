"""tkinter GUI for the AI Alarm System Mock Tester."""

import logging
import shutil
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageTk  # type: ignore[import-untyped]

from client.api_client import AlarmApiClient
from client.models import JudgmentResult, JudgmentStatus

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_DEFAULT_TEST_IMAGES = Path(__file__).resolve().parent.parent / "test_images"


def _format_di_values(equipment_data: dict | None) -> str:
    """equipment_data에서 DI 수치 값을 한 줄 요약 문자열로 반환."""
    if not equipment_data:
        return ""
    parts = []
    for eq_id in ("S520", "S530", "S810"):
        eq = equipment_data.get(eq_id, {})
        for field, vals in eq.items():
            if isinstance(vals, list) and vals:
                parts.append(f"{eq_id}.{field}({len(vals)})")
    return " | ".join(parts)


class AlarmTestGUI:
    _DEFAULT_URL = "http://localhost:8000"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AI Alarm System - Mock Tester")
        self.root.geometry("1400x800")
        self.root.minsize(1100, 600)

        self._api_client: Optional[AlarmApiClient] = None
        self._test_root: Optional[Path] = None
        self._image_list: list[tuple[Path, str]] = []
        self._current_photo: Optional[ImageTk.PhotoImage] = None
        # (image_name, result | None, error | None)
        self._results: list[tuple[str, JudgmentResult | None, str | None]] = []

        self._build_ui()
        self._apply_history_tags()
        self._update_api_client()

        if _DEFAULT_TEST_IMAGES.is_dir():
            self._test_root = _DEFAULT_TEST_IMAGES
            self._scan_images()

        self.root.after(500, self._on_health_check)
        self.root.after(200, self._load_history_from_log)

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
        self._folder_label = ttk.Label(
            top,
            text=str(_DEFAULT_TEST_IMAGES) if _DEFAULT_TEST_IMAGES.is_dir() else "(no folder)",
        )
        self._folder_label.pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="⟳ Refresh", command=self._scan_images).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(top, text="History days:").pack(side=tk.LEFT)
        self._history_days_var = tk.StringVar(value="3")
        ttk.Spinbox(top, textvariable=self._history_days_var, from_=1, to=30, width=4).pack(side=tk.LEFT, padx=(2, 4))
        ttk.Button(top, text="Load History", command=self._reload_history).pack(side=tk.LEFT)

    def _build_notebook(self) -> None:
        self._notebook = ttk.Notebook(self.root)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self._analysis_frame = ttk.Frame(self._notebook)
        self._notebook.add(self._analysis_frame, text="  Analysis  ")
        self._build_analysis_tab()

        self._history_frame = ttk.Frame(self._notebook)
        self._notebook.add(self._history_frame, text="  History  ")
        self._build_history_tab()

    def _build_analysis_tab(self) -> None:
        paned = ttk.PanedWindow(self._analysis_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(paned, text="Test Images", padding=4)

        # Filter bar
        filter_bar = ttk.Frame(left)
        filter_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(filter_bar, text="Filter:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        self._filter_trace_id = self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(filter_bar, textvariable=self._filter_var, width=18).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Button(filter_bar, text="✕", width=2, command=self._clear_filter).pack(side=tk.LEFT)

        self._image_tree = ttk.Treeview(left, columns=(), show="tree", height=20)
        self._image_tree.column("#0", width=200)
        self._image_tree.bind("<<TreeviewSelect>>", self._on_image_select)
        self._image_tree.bind("<Double-1>", self._on_image_double_click)

        img_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self._image_tree.yview)
        self._image_tree.configure(yscrollcommand=img_scroll.set)
        self._image_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        img_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        paned.add(left, weight=1)

        right = ttk.Frame(paned, padding=4)

        preview_frame = ttk.LabelFrame(right, text="Image Preview", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True)
        self._preview_canvas = tk.Canvas(preview_frame, bg="#2b2b2b", highlightthickness=0)
        self._preview_canvas.pack(fill=tk.BOTH, expand=True)

        result_frame = ttk.LabelFrame(right, text="Analysis Result", padding=4)
        result_frame.pack(fill=tk.X, pady=(4, 0))

        detail_grid = ttk.Frame(result_frame)
        detail_grid.pack(fill=tk.X)
        self._detail_vars: dict = {}
        for i, label_text in enumerate(["Image:", "Status:", "Time(ms):", "Reason:", "DI Values:"]):
            ttk.Label(detail_grid, text=label_text, font=("", 9, "bold")).grid(
                row=i, column=0, sticky=tk.W, padx=(0, 8), pady=1
            )
            var = tk.StringVar(value="--")
            lbl = ttk.Label(detail_grid, textvariable=var, wraplength=600, anchor=tk.W)
            lbl.grid(row=i, column=1, sticky=tk.W, pady=1)
            self._detail_vars[label_text] = (var, lbl)

        paned.add(right, weight=3)

    def _build_history_tab(self) -> None:
        # columns: time | image | status | reason | di_values | time_ms
        hist_cols = ("time", "image", "status", "reason", "di_values", "time_ms")
        self._history_tree = ttk.Treeview(self._history_frame, columns=hist_cols, show="headings", height=25)
        for col, text, width, anchor in [
            ("time",      "Time",      140, tk.W),
            ("image",     "Image",     160, tk.W),
            ("status",    "Status",     70, tk.CENTER),
            ("reason",    "Reason",    380, tk.W),
            ("di_values", "DI Values", 320, tk.W),
            ("time_ms",   "Time(ms)",   70, tk.E),
        ]:
            self._history_tree.heading(col, text=text)
            self._history_tree.column(col, width=width, anchor=anchor)

        hist_scroll = ttk.Scrollbar(self._history_frame, orient=tk.VERTICAL, command=self._history_tree.yview)
        self._history_tree.configure(yscrollcommand=hist_scroll.set)
        self._history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hist_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_bottom_bar(self) -> None:
        bottom = ttk.Frame(self.root, padding=5)
        bottom.pack(fill=tk.X)

        self._analyze_selected_btn = ttk.Button(
            bottom, text="Analyze Selected", command=self._on_analyze_selected
        )
        self._analyze_selected_btn.pack(side=tk.LEFT)

        ttk.Separator(bottom, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self._analyze_btn = ttk.Button(bottom, text="Analyze All", command=self._on_analyze_all)
        self._analyze_btn.pack(side=tk.LEFT)

        ttk.Separator(bottom, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self._batch_random_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text="Random", variable=self._batch_random_var).pack(side=tk.LEFT, padx=(0, 2))
        self._batch_random_n_var = tk.StringVar(value="100")
        ttk.Entry(bottom, textvariable=self._batch_random_n_var, width=5).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self._status_var).pack(side=tk.RIGHT)

    def _apply_history_tags(self) -> None:
        self._history_tree.tag_configure("ok",      background="#c8f7c8")
        self._history_tree.tag_configure("ng",      background="#f7c8c8")
        self._history_tree.tag_configure("unknown", background="#f7f0c8")
        self._history_tree.tag_configure("timeout", background="#d0d0d0")

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
        self._image_list.clear()
        self._results.clear()
        self._image_tree.delete(*self._image_tree.get_children())
        # Reset filter without triggering _apply_filter callback
        if hasattr(self, "_filter_var"):
            self._filter_var.trace_remove("write", self._filter_trace_id)
            self._filter_var.set("")
            self._filter_trace_id = self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        if self._test_root is None or not self._test_root.is_dir():
            return
        self._scan_folder_recursive(self._test_root, "")

    def _scan_folder_recursive(self, folder: Path, parent_id: str) -> None:
        for item in sorted(folder.iterdir()):
            if item.name.startswith(".") or item.name == "__pycache__":
                continue
            if item.is_dir():
                img_count = sum(
                    1 for p in item.rglob("*")
                    if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
                )
                if img_count == 0:
                    continue
                node_id = self._image_tree.insert(
                    parent_id, tk.END,
                    text=f"{item.name} ({img_count})",
                    open=(parent_id == ""),
                )
                self._scan_folder_recursive(item, node_id)
            elif item.is_file() and item.suffix.lower() in _IMAGE_EXTENSIONS:
                self._image_tree.insert(parent_id, tk.END, text=item.name)
                self._image_list.append((item, folder.name))

    def _clear_filter(self) -> None:
        self._filter_var.trace_remove("write", self._filter_trace_id)
        self._filter_var.set("")
        self._filter_trace_id = self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        self._image_tree.delete(*self._image_tree.get_children())
        if self._test_root:
            self._scan_folder_recursive(self._test_root, "")

    def _apply_filter(self) -> None:
        keyword = self._filter_var.get().strip().lower()
        self._image_tree.delete(*self._image_tree.get_children())
        if not keyword:
            # restore full tree
            self._scan_folder_recursive(self._test_root, "") if self._test_root else None
            return
        # flat list of matching images
        for path, folder_name in self._image_list:
            if keyword in path.name.lower():
                self._image_tree.insert("", tk.END, text=path.name)

    def _on_image_select(self, event=None) -> None:
        selection = self._image_tree.selection()
        if not selection:
            return
        item = selection[0]
        item_text = self._image_tree.item(item, "text")
        # folder node: has children and no image extension
        if self._image_tree.get_children(item) or not any(item_text.endswith(ext) for ext in _IMAGE_EXTENSIONS):
            if not self._filter_var.get().strip():
                return
        for path, _ in self._image_list:
            if path.name == item_text:
                self._show_image_preview(path)
                break
        self._show_result_detail(item_text)

    def _on_image_double_click(self, event=None) -> None:
        self._on_analyze_selected()

    def _show_image_preview(self, image_path: Path) -> None:
        try:
            img = Image.open(image_path)
            canvas_w = self._preview_canvas.winfo_width() or 600
            canvas_h = self._preview_canvas.winfo_height() or 400
            if canvas_w < 10:
                canvas_w = 600
            if canvas_h < 10:
                canvas_h = 400
            ratio = min(canvas_w / img.width, canvas_h / img.height)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
            self._current_photo = ImageTk.PhotoImage(img)
            self._preview_canvas.delete("all")
            self._preview_canvas.create_image(
                canvas_w // 2, canvas_h // 2, image=self._current_photo, anchor=tk.CENTER
            )
        except Exception as exc:
            logger.warning("Failed to load image preview: %s", exc)
            self._preview_canvas.delete("all")
            self._preview_canvas.create_text(300, 200, text=f"Cannot load image:\n{exc}", fill="white")

    def _show_result_detail(self, image_name: str) -> None:
        entry = next((e for e in self._results if e[0] == image_name), None)
        if entry is None:
            for var, _ in self._detail_vars.values():
                var.set("--")
            return

        name, result, error = entry
        self._detail_vars["Image:"][0].set(name)

        if result is not None:
            self._detail_vars["Status:"][0].set(result.status.value)
            self._detail_vars["Time(ms):"][0].set(str(result.processing_time_ms))
            self._detail_vars["Reason:"][0].set(result.reason)
            self._detail_vars["DI Values:"][0].set(_format_di_values(result.equipment_data))
        else:
            self._detail_vars["Status:"][0].set("ERROR")
            self._detail_vars["Time(ms):"][0].set("--")
            self._detail_vars["Reason:"][0].set(error or "Unknown error")
            self._detail_vars["DI Values:"][0].set("")

    def _get_selected_image(self) -> tuple[Path, str] | None:
        selection = self._image_tree.selection()
        if not selection:
            return None
        item = selection[0]
        if not self._image_tree.parent(item):
            return None
        item_text = self._image_tree.item(item, "text")
        for path, folder_name in self._image_list:
            if path.name == item_text:
                return path, folder_name
        return None

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _on_analyze_selected(self) -> None:
        selection = self._image_tree.selection()
        if not selection:
            self._status_var.set("Select an image or folder first")
            return

        item = selection[0]
        self._update_api_client()

        if not self._image_tree.parent(item):
            images = self._get_images_under(item)
            if not images:
                self._status_var.set("No images in selected folder")
                return
            if self._batch_random_var.get():
                try:
                    n = max(1, int(self._batch_random_n_var.get()))
                except ValueError:
                    n = 100
                if n < len(images):
                    import random
                    images = random.sample(images, n)
                    images = sorted(images, key=lambda x: x[0].name)
            folder_path = self._get_folder_path(item)
            self._set_buttons_state(tk.DISABLED)
            self._status_var.set(f"Batch: 0 / {len(images)}")
            threading.Thread(
                target=self._run_batch,
                args=(folder_path, [p for p, _ in images]),
                daemon=True,
            ).start()
        else:
            entry = self._get_selected_image()
            if entry is None:
                return
            image_path, _ = entry
            self._set_buttons_state(tk.DISABLED)
            self._status_var.set(f"Analyzing {image_path.name}...")

            def _run() -> None:
                try:
                    assert self._api_client is not None
                    result = self._api_client.analyze_single(image_path)
                    res_entry = (image_path.name, result, None)
                except Exception as exc:
                    res_entry = (image_path.name, None, str(exc))
                self.root.after(0, lambda: self._on_single_analysis_complete(res_entry))

            threading.Thread(target=_run, daemon=True).start()

    def _get_images_under(self, node_id: str) -> list[tuple[Path, str]]:
        result = []
        for child in self._image_tree.get_children(node_id):
            if self._image_tree.get_children(child):
                result.extend(self._get_images_under(child))
            else:
                item_text = self._image_tree.item(child, "text")
                for path, folder_name in self._image_list:
                    if path.name == item_text:
                        result.append((path, folder_name))
                        break
        return result

    def _get_folder_path(self, node_id: str) -> Path:
        parts = []
        current = node_id
        while current:
            name = self._image_tree.item(current, "text").split(" (")[0]
            parts.append(name)
            current = self._image_tree.parent(current)
        parts.reverse()
        path = self._test_root
        for part in parts:
            path = path / part
        return path

    def _set_buttons_state(self, state: str) -> None:
        self._analyze_selected_btn.configure(state=state)
        self._analyze_btn.configure(state=state)

    def _on_single_analysis_complete(
        self, entry: tuple[str, JudgmentResult | None, str | None]
    ) -> None:
        name, result, error = entry
        for i, (n, _, _) in enumerate(self._results):
            if n == name:
                self._results[i] = entry
                break
        else:
            self._results.append(entry)
        self._add_history(name, result, error)
        self._show_result_detail(name)
        self._status_var.set(f"Done: {name} → {result.status.value if result else 'ERROR'}")
        self._set_buttons_state(tk.NORMAL)

    def _on_analyze_all(self) -> None:
        if not self._image_list:
            self._status_var.set("No images loaded")
            return
        self._update_api_client()
        self._status_var.set("Analyzing...")
        self._set_buttons_state(tk.DISABLED)
        threading.Thread(target=self._run_analyze_all, daemon=True).start()

    def _run_analyze_all(self) -> None:
        assert self._api_client is not None
        results: list[tuple[str, JudgmentResult | None, str | None]] = []
        for image_path, _ in self._image_list:
            try:
                result = self._api_client.analyze_single(image_path)
                results.append((image_path.name, result, None))
            except Exception as exc:
                results.append((image_path.name, None, str(exc)))
        self.root.after(0, lambda: self._on_analysis_complete(results))

    def _on_analysis_complete(
        self, results: list[tuple[str, JudgmentResult | None, str | None]]
    ) -> None:
        self._results = results
        for name, result, error in results:
            self._add_history(name, result, error)
        self._status_var.set(f"Done - {len(results)} images analyzed")
        self._set_buttons_state(tk.NORMAL)
        children = self._image_tree.get_children()
        if children:
            first_children = self._image_tree.get_children(children[0])
            if first_children:
                self._image_tree.selection_set(first_children[0])
                self._on_image_select()

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _is_batch_folder(path: Path) -> bool:
        """폴더명이 정확히 'batch' 또는 's_batch'일 때만 True."""
        name = path.name.lower()
        return name in ("batch", "s_batch")

    def _run_batch(self, batch_path: Path, images: list[Path]) -> None:
        assert self._api_client is not None

        use_subfolders = self._is_batch_folder(batch_path)
        out_dirs: dict[str, Path] = {}
        if use_subfolders:
            out_dirs = {
                "ok": batch_path / "ok",
                "ng": batch_path / "ng",
                "unknown": batch_path / "unknown",
            }
            for d in out_dirs.values():
                d.mkdir(exist_ok=True)

        total = len(images)
        counts = {"ok": 0, "ng": 0, "unknown": 0, "error": 0}

        for i, img_path in enumerate(images, 1):
            self.root.after(0, lambda i=i: self._status_var.set(f"Batch: {i} / {total} — {img_path.name}"))
            try:
                result = self._api_client.analyze_single(img_path)
                status_key = result.status.value.lower()
                if status_key not in ("ok", "ng", "unknown"):
                    status_key = "unknown"
                if use_subfolders:
                    shutil.move(str(img_path), out_dirs[status_key] / img_path.name)
                counts[status_key] += 1
                self.root.after(0, lambda n=img_path.name, r=result: self._add_history(n, r, None))
                logger.info("Batch [%d/%d] %s → %s", i, total, img_path.name, status_key)
            except Exception as exc:
                counts["error"] += 1
                self.root.after(0, lambda n=img_path.name, e=str(exc): self._add_history(n, None, e))
                logger.error("Batch error for %s: %s", img_path.name, exc)

        summary = (
            f"Batch complete — {total} images\n"
            f"  OK: {counts['ok']}  NG: {counts['ng']}  "
            f"UNKNOWN: {counts['unknown']}  ERROR: {counts['error']}\n"
            f"Results saved to: {batch_path}"
        )
        self.root.after(0, lambda: self._on_batch_complete(summary))

    def _on_batch_complete(self, summary: str) -> None:
        self._status_var.set(summary.split("\n")[0])
        self._set_buttons_state(tk.NORMAL)
        self._scan_images()
        messagebox.showinfo("Analyze Batch Complete", summary)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _load_history_from_log(self) -> None:
        try:
            days = max(1, int(self._history_days_var.get()))
        except ValueError:
            days = 3
        self._reload_history(days=days)

    def _reload_history(self, days: int | None = None) -> None:
        if days is None:
            try:
                days = max(1, int(self._history_days_var.get()))
            except ValueError:
                days = 3

        from datetime import date, timedelta
        log_dir = Path(__file__).resolve().parent.parent / "data" / "logs"
        self._history_tree.delete(*self._history_tree.get_children())

        all_entries = []
        for i in range(days):
            log_file = log_dir / f"{(date.today() - timedelta(days=i)).strftime('%Y-%m-%d')}.log"
            if not log_file.is_file():
                continue
            try:
                with open(log_file, encoding="utf-8") as f:
                    current: dict | None = None
                    for line in f:
                        if line.startswith("  ["):
                            # DI values line — accumulate into current entry
                            if current is not None:
                                current["di"] += ("  " if current["di"] else "") + line.strip()
                        else:
                            if current is not None:
                                all_entries.append(current)
                            line = line.strip()
                            if not line:
                                current = None
                                continue
                            # new format: timestamp | req_id | image_name | status | reason
                            parts = line.split(" | ", 4)
                            if len(parts) == 5:
                                current = {
                                    "time": parts[0], "image": parts[2],
                                    "status": parts[3], "reason": parts[4], "di": "",
                                }
                            elif len(parts) == 4:
                                # old format without image_name
                                current = {
                                    "time": parts[0], "image": parts[1],
                                    "status": parts[2], "reason": parts[3], "di": "",
                                }
                            else:
                                current = None
                    if current is not None:
                        all_entries.append(current)
            except Exception as exc:
                logger.warning("Failed to load log %s: %s", log_file.name, exc)

        _TAG_MAP = {"OK": "ok", "NG": "ng", "UNKNOWN": "unknown", "TIMEOUT": "timeout"}
        for e in reversed(all_entries):
            self._history_tree.insert(
                "", tk.END,
                values=(e["time"], e["image"], e["status"], e["reason"], e["di"], ""),
                tags=(_TAG_MAP.get(e["status"], ""),),
            )

        self._status_var.set(f"History loaded: {len(all_entries)} entries ({days} days)")

    def _add_history(
        self, image_name: str, result: JudgmentResult | None, error: str | None
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if result is not None:
            status = result.status.value
            reason = result.reason
            time_ms = str(result.processing_time_ms)
            di_vals = _format_di_values(result.equipment_data)
            tag = status.lower()
        else:
            status, reason, time_ms, di_vals, tag = "ERROR", error or "Unknown error", "--", "", "unknown"

        self._history_tree.insert(
            "", 0,
            values=(now, image_name, status, reason, di_vals, time_ms),
            tags=(tag,),
        )
        children = self._history_tree.get_children()
        if len(children) > 500:
            self._history_tree.delete(children[-1])
