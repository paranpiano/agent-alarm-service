"""Cloud Log Viewer GUI - standalone tkinter app.

Usage:
    python -m log_viewer.main
    python log_viewer/main.py
"""

import json
import logging
import os
import threading
import tkinter as tk
from datetime import date
from tkinter import colorchooser, messagebox, ttk

try:
    from PIL import Image, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

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

# Default alert appearance  (차분한 네이비/슬레이트 계열)
_DEFAULT_BG        = "#1E2A3A"   # 다크 네이비
_DEFAULT_TITLE_FG  = "#E8C84A"   # 웜 골드
_DEFAULT_EQ_OK_FG  = "#4A5568"   # 슬레이트 그레이 (빈 슬롯)
_DEFAULT_EQ_NG_FG  = "#F56565"   # 소프트 레드

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_config.json")


def _resolve_image_path(raw_path: str) -> str:
    """Resolve image path relative to this file's directory."""
    if os.path.isabs(raw_path):
        return raw_path
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base, raw_path))


def _save_config_keys(updates: dict) -> None:
    """Merge updates into monitor_config.json and save."""
    data = {}
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data.update(updates)
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("config 저장 실패: %s", exc)


class NgAlertWindow:
    """Alert window displayed when an NG event occurs.

    Layout (grid rows, top → bottom):
        row 0  logo image          (weight = alert_image_ratio)
        row 1  "순환 에러" text     (weight = alert_title_ratio)
        row 2  equipment slots     (weight = alert_equipment_ratio, expand)
        row 3  controls panel      (fixed height, hidden by default)
    """

    _EQUIPMENT_SLOTS = 6

    def __init__(self, parent: tk.Tk, ng_equipments: list[str],
                 position: str, size_ratio: float,
                 cfg: dict | None = None) -> None:
        self._parent = parent
        self._cfg = cfg or {}
        self._closed = False
        self._resize_job = None
        self._photo_ref = None

        # Appearance (loaded from cfg, editable via controls)
        self._bg_color    = self._cfg.get("alert_bg_color",    _DEFAULT_BG)
        self._title_fg    = self._cfg.get("alert_title_color", _DEFAULT_TITLE_FG)
        self._eq_ok_fg    = self._cfg.get("alert_eq_ok_color", _DEFAULT_EQ_OK_FG)
        self._eq_ng_fg    = self._cfg.get("alert_eq_ng_color", _DEFAULT_EQ_NG_FG)
        self._font_size   = int(self._cfg.get("alert_font_size", 0))

        # Layout ratios
        self._img_ratio   = int(self._cfg.get("alert_image_ratio",     2))
        self._title_ratio = int(self._cfg.get("alert_title_ratio",     2))
        self._eq_ratio    = int(self._cfg.get("alert_equipment_ratio", 6))
        self._eq_slots    = int(self._cfg.get("alert_equipment_slots", self._EQUIPMENT_SLOTS))

        # Controls visibility: default hidden (False), config can override
        self._controls_visible = bool(self._cfg.get("show_alert_controls", False))

        self._ng_equipments: list[str] = []

        # ── Window ──────────────────────────────────────────────────────
        self._win = tk.Toplevel(parent)
        self._win.title("⚠ 순환 에러 알람")
        self._win.attributes("-topmost", True)
        self._win.resizable(True, True)
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._win.configure(bg=self._bg_color)

        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        if position in ("right", "left"):
            win_w, win_h = int(sw * size_ratio), sh
        else:
            win_w, win_h = sw, int(sh * size_ratio)
        self._win.geometry(f"{win_w}x{win_h}")

        # ── Grid layout ─────────────────────────────────────────────────
        # Main container fills the window
        self._main = tk.Frame(self._win, bg=self._bg_color)
        self._main.pack(fill=tk.BOTH, expand=True)
        self._main.columnconfigure(0, weight=1)
        # rows 0-2 share space by ratio weights; row 3 is fixed (controls)
        self._main.rowconfigure(0, weight=self._img_ratio)
        self._main.rowconfigure(1, weight=self._title_ratio)
        self._main.rowconfigure(2, weight=self._eq_ratio)
        self._main.rowconfigure(3, weight=0)  # controls: no expand

        self._img_frame   = tk.Frame(self._main, bg=self._bg_color)
        self._title_frame = tk.Frame(self._main, bg=self._bg_color)
        self._eq_frame    = tk.Frame(self._main, bg=self._bg_color)
        self._ctrl_frame  = tk.Frame(self._main, bg="#e0e0e0", relief=tk.RIDGE, bd=1)

        self._img_frame.grid  (row=0, column=0, sticky="nsew")
        self._title_frame.grid(row=1, column=0, sticky="nsew")
        self._eq_frame.grid   (row=2, column=0, sticky="nsew")
        # ctrl_frame placed in row 3 only when visible

        # Toggle button (always visible, top-right corner)
        self._toggle_btn = tk.Button(
            self._win, text="⚙", font=("Arial", 10),
            bg=self._bg_color, fg="#333333",
            relief=tk.FLAT, bd=0, cursor="hand2",
            command=self._toggle_controls,
        )
        self._toggle_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-4, y=4)

        self._build_controls()
        if self._controls_visible:
            self._ctrl_frame.grid(row=3, column=0, sticky="ew")

        self._win.update_idletasks()
        self._place(parent, position, win_w, win_h)
        self._render_all(ng_equipments)
        self._win.bind("<Configure>", self._on_resize_debounce)

    # ──────────────────────────────────────────────────────────────────
    # Controls toggle
    # ──────────────────────────────────────────────────────────────────

    def _toggle_controls(self) -> None:
        self._controls_visible = not self._controls_visible
        if self._controls_visible:
            self._ctrl_frame.grid(row=3, column=0, sticky="ew")
        else:
            self._ctrl_frame.grid_remove()
        _save_config_keys({"show_alert_controls": self._controls_visible})

    # ──────────────────────────────────────────────────────────────────
    # Controls panel
    # ──────────────────────────────────────────────────────────────────

    def _build_controls(self) -> None:
        f = self._ctrl_frame

        # ── Row 0: 비율 조정 ────────────────────────────────────────────
        tk.Label(f, text="비율", bg="#e0e0e0", font=("Arial", 8, "bold")).grid(
            row=0, column=0, padx=(6, 2), pady=(4, 1), sticky=tk.W)

        self._v_img   = tk.IntVar(value=self._img_ratio)
        self._v_title = tk.IntVar(value=self._title_ratio)
        self._v_eq    = tk.IntVar(value=self._eq_ratio)

        for c, var, label in [(1, self._v_img, "이미지"), (3, self._v_title, "제목"), (5, self._v_eq, "장비")]:
            tk.Label(f, text=label, bg="#e0e0e0", font=("Arial", 8)).grid(row=0, column=c, padx=(6, 0), pady=(4,1))
            sp = tk.Spinbox(f, textvariable=var, from_=1, to=8, width=3,
                            command=self._on_ratio_change, font=("Arial", 8))
            sp.grid(row=0, column=c+1, padx=(2, 4), pady=(4,1))
            sp.bind("<Return>", lambda _e: self._on_ratio_change())

        # ── Row 1: 색상 조정 ────────────────────────────────────────────
        tk.Label(f, text="색상", bg="#e0e0e0", font=("Arial", 8, "bold")).grid(
            row=1, column=0, padx=(6, 2), pady=(1, 4), sticky=tk.W)

        color_items = [
            ("배경",   lambda: self._pick_bg_color(),    "_bg_btn",    self._bg_color),
            ("제목",   lambda: self._pick_title_color(), "_title_btn", self._title_fg),
            ("NG글자", lambda: self._pick_ng_color(),    "_ng_btn",    self._eq_ng_fg),
        ]
        for idx, (label, cmd, attr, color) in enumerate(color_items):
            col = idx * 2 + 1
            tk.Label(f, text=label, bg="#e0e0e0", font=("Arial", 8)).grid(
                row=1, column=col, padx=(6, 0), pady=(1, 4))
            btn = tk.Button(f, bg=color, width=4, relief=tk.RAISED,
                            command=cmd, font=("Arial", 8))
            btn.grid(row=1, column=col+1, padx=(2, 4), pady=(1, 4))
            setattr(self, attr, btn)

    def _on_ratio_change(self) -> None:
        self._img_ratio   = max(1, self._v_img.get())
        self._title_ratio = max(1, self._v_title.get())
        self._eq_ratio    = max(1, self._v_eq.get())
        self._main.rowconfigure(0, weight=self._img_ratio)
        self._main.rowconfigure(1, weight=self._title_ratio)
        self._main.rowconfigure(2, weight=self._eq_ratio)
        _save_config_keys({
            "alert_image_ratio":     self._img_ratio,
            "alert_title_ratio":     self._title_ratio,
            "alert_equipment_ratio": self._eq_ratio,
        })
        self._render_all(self._ng_equipments)

    def _pick_bg_color(self) -> None:
        color = colorchooser.askcolor(color=self._bg_color, title="배경색 선택")[1]
        if color:
            self._bg_color = color
            self._bg_btn.configure(bg=color)
            self._win.configure(bg=color)
            self._main.configure(bg=color)
            self._img_frame.configure(bg=color)
            self._title_frame.configure(bg=color)
            self._eq_frame.configure(bg=color)
            self._toggle_btn.configure(bg=color)
            _save_config_keys({"alert_bg_color": color})
            self._render_all(self._ng_equipments)

    def _pick_title_color(self) -> None:
        color = colorchooser.askcolor(color=self._title_fg, title="제목 글자색 선택")[1]
        if color:
            self._title_fg = color
            self._title_btn.configure(bg=color)
            _save_config_keys({"alert_title_color": color})
            self._render_all(self._ng_equipments)

    def _pick_ng_color(self) -> None:
        color = colorchooser.askcolor(color=self._eq_ng_fg, title="NG 장비 글자색 선택")[1]
        if color:
            self._eq_ng_fg = color
            self._ng_btn.configure(bg=color)
            _save_config_keys({"alert_eq_ng_color": color})
            self._render_all(self._ng_equipments)

    # ──────────────────────────────────────────────────────────────────
    # Rendering
    # ──────────────────────────────────────────────────────────────────

    def _render_all(self, ng_equipments: list[str]) -> None:
        self._ng_equipments = ng_equipments
        win_w = max(self._win.winfo_width(), 100)
        win_h = max(self._win.winfo_height(), 200)

        # Estimate heights from grid weights for font sizing
        ctrl_h = self._ctrl_frame.winfo_height() if self._controls_visible else 0
        avail_h = max(win_h - ctrl_h, 100)
        total_ratio = self._img_ratio + self._title_ratio + self._eq_ratio
        img_h   = int(avail_h * self._img_ratio   / total_ratio)
        title_h = int(avail_h * self._title_ratio / total_ratio)
        eq_h    = avail_h - img_h - title_h

        self._img_frame.configure(bg=self._bg_color)
        self._title_frame.configure(bg=self._bg_color)
        self._eq_frame.configure(bg=self._bg_color)

        self._render_image(win_w, img_h)
        self._render_title(win_w, title_h)
        self._render_equipments(win_w, eq_h, ng_equipments)

    def _render_image(self, win_w: int, img_h: int) -> None:
        for w in self._img_frame.winfo_children():
            w.destroy()
        self._photo_ref = None

        img_path_raw = self._cfg.get("alert_image_path", "./image.png")
        img_path = _resolve_image_path(img_path_raw)

        if _PIL_AVAILABLE and os.path.exists(img_path) and img_h > 10:
            try:
                pil_img = Image.open(img_path)
                # Scale to fit within frame keeping aspect ratio
                orig_w, orig_h = pil_img.size
                scale = min(win_w / orig_w, img_h / orig_h)
                new_w = max(1, int(orig_w * scale))
                new_h = max(1, int(orig_h * scale))
                pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
                self._photo_ref = ImageTk.PhotoImage(pil_img)
                lbl = tk.Label(self._img_frame, image=self._photo_ref,
                               bg=self._bg_color, anchor=tk.CENTER)
                lbl.pack(fill=tk.BOTH, expand=True)
                return
            except Exception as exc:
                logger.warning("이미지 로드 실패: %s", exc)

        # Fallback: colored placeholder
        tk.Label(self._img_frame, text="[ 이미지 ]",
                 bg=self._bg_color, fg=self._title_fg,
                 font=("Arial", max(10, img_h // 4), "bold"),
                 anchor=tk.CENTER).pack(fill=tk.BOTH, expand=True)

    def _render_title(self, win_w: int, title_h: int) -> None:
        for w in self._title_frame.winfo_children():
            w.destroy()
        if title_h < 10:
            return

        fsize = self._font_size if self._font_size > 0 else max(12, int(title_h * 0.38))
        fsize = max(10, min(fsize, 300))

        tk.Label(
            self._title_frame, text="순환 에러",
            font=("Arial", fsize, "bold"),
            fg=self._title_fg, bg=self._bg_color,
            anchor=tk.CENTER,
        ).pack(fill=tk.BOTH, expand=True)

    def _render_equipments(self, win_w: int, eq_h: int, ng_equipments: list[str]) -> None:
        for w in self._eq_frame.winfo_children():
            w.destroy()
        if eq_h < 10:
            return

        slots = self._eq_slots
        slot_h = max(20, eq_h // slots)

        # Auto font size based on slot height and window width
        longest = max((len(eq) for eq in ng_equipments), default=4)
        if self._font_size > 0:
            fsize = self._font_size
        else:
            fsize_h = int(slot_h * 0.65)
            fsize_w = max(1, int((win_w - 20) / max(longest, 4) / 0.65))
            fsize = max(14, min(fsize_h, fsize_w, 300))

        ng_set = set(ng_equipments)
        # Fill slots: NG equipments first, then empty
        slot_labels = list(ng_equipments[:slots]) + [""] * max(0, slots - len(ng_equipments))

        for i in range(slots):
            text = slot_labels[i] if i < len(slot_labels) else ""
            is_ng = text in ng_set and text != ""
            fg = self._eq_ng_fg if is_ng else self._eq_ok_fg
            tk.Label(
                self._eq_frame, text=text,
                font=("Arial", fsize, "bold"),
                fg=fg, bg=self._bg_color,
                anchor=tk.CENTER, justify=tk.CENTER,
            ).pack(fill=tk.BOTH, expand=True)

    # ──────────────────────────────────────────────────────────────────
    # Resize / placement
    # ──────────────────────────────────────────────────────────────────

    def _on_resize_debounce(self, _event=None) -> None:
        if self._resize_job is not None:
            self._win.after_cancel(self._resize_job)
        self._resize_job = self._win.after(200, self._on_resize_done)

    def _on_resize_done(self) -> None:
        self._resize_job = None
        if not self._closed:
            self._render_all(self._ng_equipments)

    def _place(self, parent: tk.Tk, position: str, win_w: int, win_h: int) -> None:
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        if position == "right":
            x, y = sw - win_w, 0
        elif position == "left":
            x, y = 0, 0
        elif position == "top":
            x, y = 0, 0
        else:
            x, y = 0, sh - win_h
        self._win.geometry(f"{win_w}x{win_h}+{x}+{y}")

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

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
