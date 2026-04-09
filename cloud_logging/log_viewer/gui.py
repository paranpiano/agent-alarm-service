"""Cloud Log Viewer GUI - standalone tkinter app.

Usage:
    python -m log_viewer.main
    python log_viewer/main.py
"""

import json
import logging
import threading
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

try:
    from log_viewer.api_client import LogApiClient, DEFAULT_API_URL
except ImportError:
    from api_client import LogApiClient, DEFAULT_API_URL

logger = logging.getLogger(__name__)

_TAG_MAP = {"OK": "ok", "NG": "ng", "UNKNOWN": "unknown", "TIMEOUT": "timeout"}
_COLS = ("timestamp", "image_name", "status", "reason", "processing_time_ms")
_COL_CFG = [
    ("timestamp",          "Time",           160, tk.W),
    ("image_name",         "Image",           180, tk.W),
    ("status",             "Status",           70, tk.CENTER),
    ("reason",             "Judgment Reason", 420, tk.W),
    ("processing_time_ms", "Time(ms)",         80, tk.E),
]

_POSITIONS = ["right", "left", "top", "bottom"]
_DEFAULT_INTERVAL_SEC = 30


class NgAlertWindow:
    """Alert window displayed when an NG event occurs."""

    def __init__(self, parent: tk.Tk, ng_equipments: list[str],
                 position: str, size_ratio: float) -> None:
        self._win = tk.Toplevel(parent)
        self._win.title("⚠ Circulation Error Alert")
        self._win.attributes("-topmost", True)
        self._win.resizable(True, True)
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._closed = False
        self._win.configure(bg="#FFD700")
        self._resize_job = None  # debounce handle

        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()

        if position in ("right", "left"):
            win_w = int(sw * size_ratio)
            win_h = sh
        else:
            win_w = sw
            win_h = int(sh * size_ratio)

        # Title frame - dynamic font size fitted to window dimensions
        self._title_frame = tk.Frame(self._win, bg="#FFD700")
        self._title_frame.pack(fill=tk.X, pady=(10, 4))

        # Equipment name area
        self._eq_frame = tk.Frame(self._win, bg="#FFD700")
        self._eq_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._ng_equipments: list[str] = []

        # Render after geometry is finalised
        self._win.geometry(f"{win_w}x{win_h}")
        self._win.update_idletasks()
        self._place(parent, position, win_w, win_h)
        self._render_all(ng_equipments)

        # Bind resize with debounce to prevent infinite loops
        self._win.bind("<Configure>", self._on_resize_debounce)

    def _render_all(self, ng_equipments: list[str]) -> None:
        """Re-render title and equipment names scaled to the current window size."""
        self._ng_equipments = ng_equipments
        win_w = self._win.winfo_width() or 400
        win_h = self._win.winfo_height() or 400

        # 4 title rows + N equipment rows = (4 + N) total rows dividing the screen
        title_lines = ["⚠", "순환", "에러"]
        eq_count = max(len(ng_equipments), 1)
        total_rows = len(title_lines) + eq_count
        row_h = max(30, win_h // total_rows)

        # Font size: based on row height, capped by window width
        longest_eq = max((len(eq) for eq in ng_equipments), default=1)
        fsize_by_h = int(row_h * 0.7)
        fsize_by_w = max(1, int((win_w - 20) / (longest_eq * 0.65)))
        fsize = max(20, min(fsize_by_h, fsize_by_w, 300))

        # Render title labels
        for w in self._title_frame.winfo_children():
            w.destroy()
        for line in title_lines:
            tk.Label(
                self._title_frame, text=line,
                font=("Arial", fsize, "bold"),
                fg="#cc0000", bg="#FFD700",
                anchor=tk.CENTER,
            ).pack(fill=tk.X)

        # Render equipment names
        for w in self._eq_frame.winfo_children():
            w.destroy()
        for eq in ng_equipments:
            tk.Label(
                self._eq_frame, text=eq,
                font=("Arial", fsize, "bold"),
                fg="#cc0000", bg="#FFD700",
                wraplength=win_w * 10,  # effectively disable line-wrapping
                justify=tk.CENTER,
                anchor=tk.CENTER,
            ).pack(fill=tk.BOTH, expand=True)

    def _render_equipments(self, ng_equipments: list[str]) -> None:
        """Full re-render on resize."""
        self._render_all(ng_equipments)

    def _on_resize_debounce(self, _event=None) -> None:
        """Debounce resize events - fires only once after 200 ms."""
        if self._resize_job is not None:
            self._win.after_cancel(self._resize_job)
        self._resize_job = self._win.after(200, self._on_resize_done)

    def _on_resize_done(self) -> None:
        self._resize_job = None
        if self._ng_equipments and not self._closed:
            self._render_all(self._ng_equipments)

    def _place(self, parent: tk.Tk, position: str, win_w: int, win_h: int) -> None:
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()

        # Position the window at a screen edge
        if position == "right":
            x, y = sw - win_w, 0
        elif position == "left":
            x, y = 0, 0
        elif position == "top":
            x, y = 0, 0
        else:  # bottom
            x, y = 0, sh - win_h

        self._win.geometry(f"{win_w}x{win_h}+{x}+{y}")

    def _on_close(self) -> None:
        self._closed = True
        self._win.destroy()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._win.destroy()
            except Exception:
                pass

    def update_message(self, ng_equipments: list[str]) -> None:
        if self._closed:
            return
        self._render_all(ng_equipments)


class CloudLogViewerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AI Alarm - Cloud Log Viewer")
        self.root.geometry("1100x680")
        self.root.minsize(900, 500)

        self._client = LogApiClient()
        self._all_logs: list[dict] = []
        self._last_seen_timestamp: str = ""  # latest timestamp seen so far
        self._active_ng_equipments: set[str] = set()  # equipment names currently in NG state
        self._alert_win: NgAlertWindow | None = None
        self._auto_refresh_job = None
        self._countdown_remaining = 0

        self._build_ui()
        self._apply_tags()

        # Auto-refresh on by default
        self._auto_refresh_var.set(True)
        self.root.after(300, lambda: self._load_logs())
        self.root.after(600, self._on_auto_refresh_toggle)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_auto_refresh_bar()
        self._build_table()
        self._build_detail_panel()
        self._build_statusbar()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.pack(fill=tk.X)

        ttk.Label(bar, text="API URL:").pack(side=tk.LEFT)
        self._url_var = tk.StringVar(value=DEFAULT_API_URL)
        ttk.Entry(bar, textvariable=self._url_var, width=55).pack(side=tk.LEFT, padx=(4, 8))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(bar, text="Date:").pack(side=tk.LEFT)
        self._date_var = tk.StringVar(value=date.today().strftime("%Y-%m-%d"))
        ttk.Entry(bar, textvariable=self._date_var, width=12).pack(side=tk.LEFT, padx=(4, 4))

        ttk.Label(bar, text="Last").pack(side=tk.LEFT, padx=(8, 2))
        self._days_var = tk.StringVar(value="1")
        ttk.Spinbox(bar, textvariable=self._days_var, from_=1, to=30, width=4).pack(side=tk.LEFT)
        ttk.Label(bar, text="days").pack(side=tk.LEFT, padx=(2, 8))

        ttk.Button(bar, text="Search", command=self._load_logs).pack(side=tk.LEFT)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(bar, text="Filter:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(bar, textvariable=self._filter_var, width=16).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(bar, text="✕", width=2, command=lambda: self._filter_var.set("")).pack(side=tk.LEFT)

    def _build_auto_refresh_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(6, 2))
        bar.pack(fill=tk.X)

        self._auto_refresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Auto Refresh",
            variable=self._auto_refresh_var,
            command=self._on_auto_refresh_toggle,
        ).pack(side=tk.LEFT)

        ttk.Label(bar, text="Interval (sec):").pack(side=tk.LEFT, padx=(8, 2))
        self._interval_var = tk.StringVar(value=str(_DEFAULT_INTERVAL_SEC))
        ttk.Spinbox(bar, textvariable=self._interval_var, from_=5, to=3600, width=6).pack(side=tk.LEFT)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(bar, text="Alert Position:").pack(side=tk.LEFT)
        self._position_var = tk.StringVar(value="right")
        ttk.Combobox(
            bar, textvariable=self._position_var,
            values=_POSITIONS, width=6, state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(bar, text="Alert Size (ratio):").pack(side=tk.LEFT)
        self._size_ratio_var = tk.StringVar(value="0.25")
        ttk.Spinbox(
            bar, textvariable=self._size_ratio_var,
            from_=0.1, to=0.9, increment=0.05, width=5, format="%.2f",
        ).pack(side=tk.LEFT, padx=(4, 0))

        self._countdown_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._countdown_var, foreground="gray").pack(side=tk.RIGHT, padx=8)

    def _build_table(self) -> None:
        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 0))

        self._tree = ttk.Treeview(frame, columns=_COLS, show="headings", height=20)
        for col, text, width, anchor in _COL_CFG:
            self._tree.heading(col, text=text, command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=width, anchor=anchor)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

    def _build_detail_panel(self) -> None:
        panel = ttk.LabelFrame(self.root, text="Detail (equipment_data)", padding=6)
        panel.pack(fill=tk.X, padx=6, pady=4)

        self._detail_text = tk.Text(panel, height=6, wrap=tk.WORD, state=tk.DISABLED,
                                    font=("Consolas", 9))
        sb = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=self._detail_text.yview)
        self._detail_text.configure(yscrollcommand=sb.set)
        self._detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_statusbar(self) -> None:
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self._status_var, anchor=tk.W,
                  relief=tk.SUNKEN).pack(fill=tk.X, side=tk.BOTTOM)

    def _apply_tags(self) -> None:
        self._tree.tag_configure("ok",      background="#c8f7c8")
        self._tree.tag_configure("ng",      background="#f7c8c8")
        self._tree.tag_configure("unknown", background="#f7f0c8")
        self._tree.tag_configure("timeout", background="#d0d0d0")

    # ------------------------------------------------------------------
    # 자동 갱신
    # ------------------------------------------------------------------

    def _on_auto_refresh_toggle(self) -> None:
        if self._auto_refresh_var.get():
            self._schedule_next_refresh()
        else:
            self._cancel_auto_refresh()
            self._countdown_var.set("")

    def _schedule_next_refresh(self) -> None:
        if not self._auto_refresh_var.get():
            return
        try:
            interval = max(5, int(self._interval_var.get()))
        except ValueError:
            interval = _DEFAULT_INTERVAL_SEC
        self._countdown_remaining = interval
        self._tick_countdown()

    def _tick_countdown(self) -> None:
        if not self._auto_refresh_var.get():
            return
        if self._countdown_remaining <= 0:
            self._countdown_var.set("Refreshing...")
            self._load_logs(auto=True)
        else:
            self._countdown_var.set(f"Next refresh: {self._countdown_remaining}s")
            self._countdown_remaining -= 1
            self._auto_refresh_job = self.root.after(1000, self._tick_countdown)

    def _cancel_auto_refresh(self) -> None:
        if self._auto_refresh_job is not None:
            self.root.after_cancel(self._auto_refresh_job)
            self._auto_refresh_job = None

    # ------------------------------------------------------------------
    # 데이터 로드
    # ------------------------------------------------------------------

    def _load_logs(self, auto: bool = False) -> None:
        url = self._url_var.get().strip() or DEFAULT_API_URL
        self._client = LogApiClient(api_url=url)
        try:
            days = max(1, int(self._days_var.get()))
        except ValueError:
            days = 1

        # 자동 갱신 시에는 항상 현재 날짜 기준으로 조회
        today = date.today().strftime("%Y-%m-%d")
        if auto:
            # 날짜가 바뀌었으면 UI 필드도 갱신하고 last_seen_timestamp 초기화
            if self._date_var.get().strip() != today:
                self._date_var.set(today)
                self._last_seen_timestamp = ""
                self._active_ng_equipments.clear()
            query_date = today
        else:
            query_date = self._date_var.get().strip()

        self._status_var.set("Loading...")

        def _fetch() -> None:
            try:
                if days == 1:
                    logs = self._client.get_logs(log_date=query_date)
                else:
                    logs = self._client.get_logs_range(days=days)
                self.root.after(0, lambda: self._on_loaded(logs, auto=auto))
            except Exception as exc:
                self.root.after(0, lambda: self._on_error(str(exc), auto=auto))

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_loaded(self, logs: list[dict], auto: bool = False) -> None:
        self._all_logs = sorted(logs, key=lambda l: str(l.get("timestamp", "")), reverse=True)
        self._render_logs(self._all_logs)
        self._status_var.set(f"Total {len(self._all_logs)} records")
        self._check_ng_alert(self._all_logs)
        if auto:
            self._schedule_next_refresh()

    def _on_error(self, msg: str, auto: bool = False) -> None:
        self._status_var.set(f"Error: {msg}")
        if not auto:
            messagebox.showerror("Load Failed", msg)
        if auto:
            self._schedule_next_refresh()

    # ------------------------------------------------------------------
    # NG 알림 창
    # ------------------------------------------------------------------

    def _check_ng_alert(self, logs: list[dict]) -> None:
        if not logs:
            self._close_alert()
            self._last_seen_timestamp = ""
            self._active_ng_equipments.clear()
            return

        # Extract only newly added entries (after the previously seen timestamp)
        if self._last_seen_timestamp:
            new_logs = [l for l in logs if str(l.get("timestamp", "")) > self._last_seen_timestamp]
        else:
            new_logs = logs  # first load: treat all entries as new

        # Save the current latest timestamp for the next refresh
        self._last_seen_timestamp = str(logs[0].get("timestamp", ""))

        # If no new data, keep the current alert state
        if not new_logs:
            return

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
            position = self._position_var.get()
            try:
                ratio = float(self._size_ratio_var.get())
                ratio = max(0.1, min(0.9, ratio))
            except ValueError:
                ratio = 0.25

            ng_equipments = sorted(self._active_ng_equipments)
            if self._alert_win is None or self._alert_win._closed:
                self._alert_win = NgAlertWindow(self.root, ng_equipments, position, ratio)
            else:
                self._alert_win.update_message(ng_equipments)
        else:
            self._close_alert()

    def _close_alert(self) -> None:
        if self._alert_win is not None:
            self._alert_win.close()
            self._alert_win = None

    # ------------------------------------------------------------------
    # 렌더링
    # ------------------------------------------------------------------

    def _render_logs(self, logs: list[dict]) -> None:
        # timestamp 역순(최신 먼저) 고정 정렬
        logs = sorted(logs, key=lambda l: str(l.get("timestamp", "")), reverse=True)
        self._tree.delete(*self._tree.get_children())
        for log in logs:
            status = log.get("status", "")
            tag = _TAG_MAP.get(status, "")
            self._tree.insert("", tk.END, iid=log.get("request_id", ""),
                values=(
                    log.get("timestamp", ""),
                    log.get("image_name", ""),
                    status,
                    log.get("reason", ""),
                    log.get("processing_time_ms", ""),
                ),
                tags=(tag,),
            )

    # ------------------------------------------------------------------
    # 이벤트
    # ------------------------------------------------------------------

    def _on_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        request_id = sel[0]
        log = next((l for l in self._all_logs if l.get("request_id") == request_id), None)
        if not log:
            return
        eq_data = log.get("equipment_data", {})
        text = json.dumps(eq_data, ensure_ascii=False, indent=2) if eq_data else "(none)"
        self._detail_text.configure(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.insert(tk.END, text)
        self._detail_text.configure(state=tk.DISABLED)

    def _apply_filter(self) -> None:
        keyword = self._filter_var.get().strip().lower()
        if not keyword:
            self._render_logs(self._all_logs)
            return
        filtered = [
            l for l in self._all_logs
            if keyword in l.get("image_name", "").lower()
            or keyword in l.get("status", "").lower()
            or keyword in l.get("reason", "").lower()
        ]
        self._render_logs(filtered)
        self._status_var.set(f"Filter results: {len(filtered)}")

    def _sort_by(self, col: str) -> None:
        logs = sorted(self._all_logs, key=lambda l: str(l.get(col, "")),
                      reverse=getattr(self, f"_sort_rev_{col}", False))
        setattr(self, f"_sort_rev_{col}", not getattr(self, f"_sort_rev_{col}", False))
        self._render_logs(logs)
