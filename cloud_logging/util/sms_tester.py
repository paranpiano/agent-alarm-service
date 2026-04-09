"""SMS Send Tester GUI

Reads monitor_config.json settings, sends SMS alerts directly,
and displays detailed HTTP request/response logs in real time.

Usage:
    python cloud_logging/util/sms_tester.py
"""

import json
import logging
import os
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, scrolledtext, ttk

import requests

# ── Path correction (so it runs from the project root as well) ─
_HERE = os.path.dirname(os.path.abspath(__file__))
_LOG_VIEWER_DIR = os.path.join(os.path.dirname(_HERE), "log_viewer")
_CONFIG_PATH = os.path.join(_LOG_VIEWER_DIR, "monitor_config.json")

# ── Defaults ───────────────────────────────────────────────────
_DEFAULTS = {
    "sns_api_url": "",
    "sms_topic_arn": "",
}

_MAX_RETRIES = 3


# ── Log handler: streams to the Text widget in real time ───────
class _TextHandler(logging.Handler):
    def __init__(self, widget: scrolledtext.ScrolledText) -> None:
        super().__init__()
        self._widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        self._widget.after(0, self._append, msg, record.levelno)

    def _append(self, msg: str, level: int) -> None:
        tag = {
            logging.DEBUG:    "debug",
            logging.INFO:     "info",
            logging.WARNING:  "warn",
            logging.ERROR:    "error",
            logging.CRITICAL: "error",
        }.get(level, "info")
        self._widget.configure(state=tk.NORMAL)
        self._widget.insert(tk.END, msg, tag)
        self._widget.see(tk.END)
        self._widget.configure(state=tk.DISABLED)


# ── Main GUI ────────────────────────────────────────────────────
class SmsTesterGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SMS Send Tester")
        self.root.geometry("860x700")
        self.root.minsize(700, 550)
        self._build_ui()
        self._setup_logging()
        self._load_config()

    # ── UI setup ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ─ Top: Settings section ───────────────────────────────
        cfg_frame = ttk.LabelFrame(self.root, text="Settings (monitor_config.json)", padding=8)
        cfg_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        cfg_frame.columnconfigure(1, weight=1)

        ttk.Label(cfg_frame, text="SNS API URL:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self._api_url_var = tk.StringVar()
        ttk.Entry(cfg_frame, textvariable=self._api_url_var, width=60).grid(
            row=0, column=1, sticky=tk.EW, padx=(6, 0), pady=2
        )

        ttk.Label(cfg_frame, text="SMS Topic ARN:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self._topic_arn_var = tk.StringVar()
        ttk.Entry(cfg_frame, textvariable=self._topic_arn_var, width=60).grid(
            row=1, column=1, sticky=tk.EW, padx=(6, 0), pady=2
        )

        btn_row = ttk.Frame(cfg_frame)
        btn_row.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(6, 2))
        ttk.Button(btn_row, text="⟳  Reload Config", command=self._load_config).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="💾  Save Changes", command=self._save_config).pack(side=tk.LEFT)

        # ─ Middle: Message section ────────────────────────────────
        msg_frame = ttk.LabelFrame(self.root, text="SMS Message", padding=8)
        msg_frame.pack(fill=tk.X, padx=10, pady=4)
        msg_frame.columnconfigure(0, weight=1)

        self._msg_text = tk.Text(msg_frame, height=4, wrap=tk.WORD, font=("Consolas", 10))
        self._msg_text.pack(fill=tk.BOTH, expand=True)

        # Insert default message
        default_msg = (
            "[AI Alarm SMS Test] This is an SNS SMS test message. "
            f"Sent at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self._msg_text.insert(tk.END, default_msg)

        btn_msg_row = ttk.Frame(msg_frame)
        btn_msg_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_msg_row, text="↺  Reset Default Message", command=self._reset_message).pack(side=tk.LEFT)

        # ─ Send button ──────────────────────────────────────────
        send_frame = ttk.Frame(self.root)
        send_frame.pack(fill=tk.X, padx=10, pady=6)

        self._send_btn = ttk.Button(
            send_frame,
            text="📤  Send SMS",
            command=self._on_send,
            style="Accent.TButton",
        )
        self._send_btn.pack(side=tk.LEFT, ipadx=16, ipady=4)

        self._status_var = tk.StringVar(value="Idle")
        self._status_lbl = ttk.Label(send_frame, textvariable=self._status_var, foreground="#555")
        self._status_lbl.pack(side=tk.LEFT, padx=14)

        ttk.Button(send_frame, text="🗑  Clear Log", command=self._clear_log).pack(side=tk.RIGHT)

        # ─ Bottom: Log section ───────────────────────────────────
        log_frame = ttk.LabelFrame(self.root, text="Detailed Log", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self._log_widget = scrolledtext.ScrolledText(
            log_frame,
            state=tk.DISABLED,
            font=("Consolas", 10),
            wrap=tk.WORD,
            bg="#1e1e1e",
            fg="#d4d4d4",
        )
        self._log_widget.pack(fill=tk.BOTH, expand=True)

        # Color tags
        self._log_widget.tag_configure("debug",   foreground="#858585")
        self._log_widget.tag_configure("info",    foreground="#9cdcfe")
        self._log_widget.tag_configure("warn",    foreground="#dcdcaa")
        self._log_widget.tag_configure("error",   foreground="#f44747")
        self._log_widget.tag_configure("success", foreground="#4ec9b0")
        self._log_widget.tag_configure("header",  foreground="#c586c0", font=("Consolas", 10, "bold"))
        self._log_widget.tag_configure("request", foreground="#569cd6")
        self._log_widget.tag_configure("response",foreground="#b5cea8")

    # ── Logging setup ────────────────────────────────────────────

    def _setup_logging(self) -> None:
        handler = _TextHandler(self._log_widget)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)
        self._log_raw("=== SMS Tester Started ===\n", "header")
        self._log_raw(f"Config path: {_CONFIG_PATH}\n", "debug")

    # ── Config load / save ─────────────────────────────────────

    def _load_config(self) -> None:
        cfg = dict(_DEFAULTS)
        if os.path.exists(_CONFIG_PATH):
            try:
                with open(_CONFIG_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                cfg.update(data)
                self._log_raw("✓ monitor_config.json loaded\n", "info")
            except Exception as exc:
                self._log_raw(f"✗ config load failed: {exc}\n", "error")
        else:
            self._log_raw(f"⚠ config file not found: {_CONFIG_PATH}\n", "warn")

        self._api_url_var.set(cfg.get("sns_api_url", ""))
        self._topic_arn_var.set(cfg.get("sms_topic_arn", ""))

        # 설정 요약 출력
        self._log_raw(f"  sns_api_url   : {self._api_url_var.get() or '(not set)'}\n", "debug")
        self._log_raw(f"  sms_topic_arn : {self._topic_arn_var.get() or '(not set)'}\n", "debug")

    def _save_config(self) -> None:
        """Update only the SMS-related fields in the config file with current UI values."""
        try:
            if os.path.exists(_CONFIG_PATH):
                with open(_CONFIG_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
            data["sns_api_url"]   = self._api_url_var.get().strip()
            data["sms_topic_arn"] = self._topic_arn_var.get().strip()
            data["sms_alert_enabled"] = True
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._log_raw("✓ config saved\n", "success")
            messagebox.showinfo("Saved", "monitor_config.json saved")
        except Exception as exc:
            self._log_raw(f"✗ config save failed: {exc}\n", "error")
            messagebox.showerror("Save Failed", str(exc))

    # ── SMS send ─────────────────────────────────────────────────

    def _on_send(self) -> None:
        api_url   = self._api_url_var.get().strip()
        topic_arn = self._topic_arn_var.get().strip()
        message   = self._msg_text.get("1.0", tk.END).strip()

        # Input validation
        errors = []
        if not api_url:
            errors.append("SNS API URL is empty.")
        if not topic_arn:
            errors.append("SMS Topic ARN is empty.")
        if not message:
            errors.append("Please enter a message.")

        if errors:
            self._log_raw("\n[Validation Error]\n", "error")
            for e in errors:
                self._log_raw(f"  • {e}\n", "error")
            messagebox.showerror("Input Error", "\n".join(errors))
            return

        # Lock UI
        self._send_btn.config(state=tk.DISABLED)
        self._set_status("Sending...", "#e8a000")

        # Send in background thread
        threading.Thread(
            target=self._do_send,
            args=(api_url, topic_arn, message),
            daemon=True,
        ).start()

    def _do_send(self, api_url: str, topic_arn: str, message: str) -> None:
        url = f"{api_url.rstrip('/')}?action=publishMessage"
        payload = {
            "topicArn": topic_arn,
            "message":  message,
            "protocol": "sms",
        }

        self._log_raw("\n" + "─" * 60 + "\n", "header")
        self._log_raw(f"[SMS Send Start] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n", "header")
        self._log_raw("\n[Request Info]\n", "request")
        self._log_raw(f"  URL       : {url}\n", "request")
        self._log_raw(f"  topicArn  : {topic_arn}\n", "request")
        self._log_raw(f"  protocol  : sms\n", "request")
        self._log_raw(f"  message   :\n    {message}\n", "request")
        self._log_raw(f"\n  Full payload:\n{json.dumps(payload, ensure_ascii=False, indent=4)}\n", "debug")

        success = False
        last_error = None

        for attempt in range(1, _MAX_RETRIES + 1):
            self._log_raw(f"\n[Attempt {attempt}/{_MAX_RETRIES}]\n", "info")
            try:
                self._log_raw(f"  POST {url}\n", "request")
                resp = requests.post(url, json=payload, timeout=15)

                # 응답 상세
                self._log_raw(f"\n[Response Info]\n", "response")
                self._log_raw(f"  HTTP Status : {resp.status_code} {resp.reason}\n", "response")
                self._log_raw(f"  Headers     :\n", "response")
                for k, v in resp.headers.items():
                    self._log_raw(f"    {k}: {v}\n", "debug")
                self._log_raw(f"  Body        :\n", "response")

                try:
                    body = resp.json()
                    self._log_raw(
                        json.dumps(body, indent=4, ensure_ascii=False) + "\n", "response"
                    )
                except Exception:
                    self._log_raw(f"  (raw) {resp.text[:500]}\n", "response")
                    body = {}

                resp.raise_for_status()

                message_id = body.get("messageId", "unknown")
                self._log_raw(f"\n✓ SMS sent successfully! (attempt={attempt}, messageId={message_id})\n", "success")
                success = True
                break

            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                self._log_raw(f"\n✗ Connection Error (attempt {attempt}/{_MAX_RETRIES})\n", "error")
                self._log_raw(f"  {type(exc).__name__}: {exc}\n", "error")
                self._log_raw("  → Check the API Gateway URL.\n", "warn")

            except requests.exceptions.Timeout as exc:
                last_error = exc
                self._log_raw(f"\n✗ Request Timeout (attempt {attempt}/{_MAX_RETRIES})\n", "error")
                self._log_raw(f"  {type(exc).__name__}: {exc}\n", "error")

            except requests.exceptions.HTTPError as exc:
                last_error = exc
                self._log_raw(f"\n✗ HTTP Error (attempt {attempt}/{_MAX_RETRIES})\n", "error")
                self._log_raw(f"  {type(exc).__name__}: {exc}\n", "error")
                if resp.status_code == 400:
                    self._log_raw("  → Check the request payload format.\n", "warn")
                elif resp.status_code == 403:
                    self._log_raw("  → Check the API Key or IAM permissions.\n", "warn")
                elif resp.status_code == 404:
                    self._log_raw("  → Check the API URL or action parameter.\n", "warn")
                elif resp.status_code >= 500:
                    self._log_raw("  → Server (Lambda/SNS) internal error.\n", "warn")

            except Exception as exc:
                last_error = exc
                self._log_raw(f"\n✗ Unknown Error (attempt {attempt}/{_MAX_RETRIES})\n", "error")
                self._log_raw(f"  {type(exc).__name__}: {exc}\n", "error")

        # 결과 요약
        self._log_raw("\n" + "─" * 60 + "\n", "header")
        if success:
            self._log_raw("[ Result: Success ✓ ]\n", "success")
        else:
            self._log_raw(f"[ Result: Failed ✗  (last error: {last_error}) ]\n", "error")
        self._log_raw("─" * 60 + "\n", "header")

        # UI 복원 (메인 스레드에서)
        self.root.after(0, self._on_send_done, success)

    def _on_send_done(self, success: bool) -> None:
        self._send_btn.config(state=tk.NORMAL)
        if success:
            self._set_status("Sent ✓", "#4ec9b0")
        else:
            self._set_status("Failed ✗", "#f44747")

    # ── Helpers ──────────────────────────────────────────────────

    def _reset_message(self) -> None:
        self._msg_text.delete("1.0", tk.END)
        self._msg_text.insert(
            tk.END,
            f"[AI Alarm SMS Test] SNS SMS 전송 테스트 메시지입니다. "
            f"발송 시각: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        )

    def _clear_log(self) -> None:
        self._log_widget.configure(state=tk.NORMAL)
        self._log_widget.delete("1.0", tk.END)
        self._log_widget.configure(state=tk.DISABLED)

    def _set_status(self, text: str, color: str) -> None:
        self._status_var.set(text)
        self._status_lbl.configure(foreground=color)

    def _log_raw(self, msg: str, tag: str = "info") -> None:
        """메인 스레드에서만 안전하게 호출. 스레드에서는 after() 사용."""
        def _write():
            self._log_widget.configure(state=tk.NORMAL)
            self._log_widget.insert(tk.END, msg, tag)
            self._log_widget.see(tk.END)
            self._log_widget.configure(state=tk.DISABLED)
        self._log_widget.after(0, _write)


# ── Entry point ─────────────────────────────────────────────────
def main() -> None:
    root = tk.Tk()
    app = SmsTesterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
