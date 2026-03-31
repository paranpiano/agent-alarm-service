"""Cloud Log Upload Tester
이미지를 선택해 서버 analyze API를 호출하거나,
직접 POST /logs API를 호출해 DynamoDB 저장 여부를 진단합니다.

실행:
    python cloud_logging/util/cloud_log_tester.py
"""

import json
import logging
import os
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk

import requests

# ── 기본 설정 ──────────────────────────────────────────────
DEFAULT_SERVER_URL  = "http://localhost:8000"
DEFAULT_LOG_API_URL = "https://04x5u7rq6e.execute-api.eu-central-1.amazonaws.com/prod/logs"
TIMEOUT = 15

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# ── 로그 핸들러: tkinter Text 위젯으로 출력 ────────────────
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


# ── 메인 GUI ───────────────────────────────────────────────
class CloudLogTesterGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Cloud Log Upload Tester")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)
        self._image_path: Path | None = None
        self._build_ui()
        self._setup_logging()
        self._log("info", "=== Cloud Log Upload Tester 시작 ===")
        self._log("info", f"Python: {sys.version}")
        self._log("info", f"작업 디렉토리: {os.getcwd()}")

    # ── UI 구성 ────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── 설정 영역 ──
        cfg = ttk.LabelFrame(self.root, text="설정", padding=8)
        cfg.pack(fill=tk.X, padx=8, pady=(8, 4))

        # Server URL
        ttk.Label(cfg, text="Server URL:").grid(row=0, column=0, sticky=tk.W)
        self._server_var = tk.StringVar(value=DEFAULT_SERVER_URL)
        ttk.Entry(cfg, textvariable=self._server_var, width=45).grid(row=0, column=1, sticky=tk.EW, padx=(4, 0))

        # Log API URL
        ttk.Label(cfg, text="Log API URL:").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self._log_api_var = tk.StringVar(value=DEFAULT_LOG_API_URL)
        ttk.Entry(cfg, textvariable=self._log_api_var, width=45).grid(row=1, column=1, sticky=tk.EW, padx=(4, 0))
        cfg.columnconfigure(1, weight=1)

        # ── 이미지 선택 ──
        img = ttk.LabelFrame(self.root, text="이미지 선택 (서버 analyze 테스트용)", padding=8)
        img.pack(fill=tk.X, padx=8, pady=4)

        ttk.Button(img, text="이미지 선택...", command=self._browse_image).pack(side=tk.LEFT)
        self._img_label = ttk.Label(img, text="(선택 없음)", foreground="gray")
        self._img_label.pack(side=tk.LEFT, padx=8)

        # ── 테스트 버튼 ──
        btn = ttk.Frame(self.root, padding=(8, 4))
        btn.pack(fill=tk.X)

        ttk.Button(btn, text="① 서버 Health Check",
                   command=self._test_health).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn, text="② 직접 POST /logs (더미)",
                   command=self._test_direct_post).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn, text="③ 서버 analyze → 자동 업로드",
                   command=self._test_analyze).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn, text="④ GET /logs 조회",
                   command=self._test_get_logs).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn, text="⑤ 전체 진단",
                   command=self._run_full_diagnosis).pack(side=tk.LEFT, padx=(0, 4))

        # ── 로그 출력 ──
        log_frame = ttk.LabelFrame(self.root, text="상세 로그", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 4))

        self._log_text = scrolledtext.ScrolledText(
            log_frame, state=tk.DISABLED,
            font=("Consolas", 9), wrap=tk.WORD,
            bg="#1e1e1e", fg="#d4d4d4",
        )
        self._log_text.pack(fill=tk.BOTH, expand=True)

        # 색상 태그
        self._log_text.tag_configure("debug",  foreground="#858585")
        self._log_text.tag_configure("info",   foreground="#9cdcfe")
        self._log_text.tag_configure("warn",   foreground="#dcdcaa")
        self._log_text.tag_configure("error",  foreground="#f44747")
        self._log_text.tag_configure("ok",     foreground="#4ec9b0")
        self._log_text.tag_configure("header", foreground="#c586c0", font=("Consolas", 9, "bold"))

        # ── 하단 버튼 ──
        bottom = ttk.Frame(self.root, padding=(8, 2))
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="로그 복사", command=self._copy_log).pack(side=tk.LEFT)
        ttk.Button(bottom, text="로그 지우기", command=self._clear_log).pack(side=tk.LEFT, padx=4)
        self._status_var = tk.StringVar(value="준비")
        ttk.Label(bottom, textvariable=self._status_var).pack(side=tk.RIGHT)

    def _setup_logging(self) -> None:
        handler = _TextHandler(self._log_text)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(handler)

    # ── 헬퍼 ───────────────────────────────────────────────

    def _log(self, level: str, msg: str) -> None:
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        tag = level
        self._log_text.after(0, self._append_log, f"[{now}] {msg}\n", tag)

    def _append_log(self, msg: str, tag: str) -> None:
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, msg, tag)
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _sep(self, title: str) -> None:
        self._log("header", f"\n{'─'*60}\n  {title}\n{'─'*60}")

    def _copy_log(self) -> None:
        content = self._log_text.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self._status_var.set("로그 복사됨")

    def _clear_log(self) -> None:
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _browse_image(self) -> None:
        path = filedialog.askopenfilename(
            title="이미지 선택",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.PNG *.JPG"), ("All", "*.*")]
        )
        if path:
            self._image_path = Path(path)
            self._img_label.configure(text=str(self._image_path), foreground="black")
            self._log("info", f"이미지 선택: {self._image_path}")

    def _run_in_thread(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    # ── 테스트 ① Health Check ──────────────────────────────

    def _test_health(self) -> None:
        self._run_in_thread(self._do_health)

    def _do_health(self) -> None:
        self._sep("① 서버 Health Check")
        url = f"{self._server_var.get().rstrip('/')}/api/v1/health"
        self._log("info", f"GET {url}")
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            self._log("info", f"Status: {resp.status_code}")
            self._log("ok",   f"Response: {resp.text}")
        except Exception as e:
            self._log("error", f"실패: {e}")
        self._status_var.set("Health Check 완료")

    # ── 테스트 ② 직접 POST /logs ───────────────────────────

    def _test_direct_post(self) -> None:
        self._run_in_thread(self._do_direct_post)

    def _do_direct_post(self) -> None:
        self._sep("② 직접 POST /logs (더미 데이터)")
        url = self._log_api_var.get().strip()
        payload = {
            "request_id": f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "OK",
            "reason": "Cloud Log Tester 직접 테스트",
            "image_name": "test_image.png",
            "processing_time_ms": 123,
            "equipment_data": {"S520": {"identified": True, "ng_items": []}},
        }
        self._log("info", f"POST {url}")
        self._log("debug", f"Payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
        try:
            resp = requests.post(url, json=payload,
                                 headers={"Content-Type": "application/json"},
                                 timeout=TIMEOUT)
            self._log("info", f"Status: {resp.status_code}")
            self._log("ok" if resp.ok else "error", f"Response: {resp.text}")
            if not resp.ok:
                self._log("error", f"Headers: {dict(resp.headers)}")
        except requests.exceptions.ConnectionError as e:
            self._log("error", f"연결 실패 (네트워크/DNS 문제): {e}")
        except requests.exceptions.Timeout:
            self._log("error", f"Timeout ({TIMEOUT}s) - 방화벽 또는 API GW 문제")
        except Exception as e:
            self._log("error", f"예외: {type(e).__name__}: {e}")
        self._status_var.set("직접 POST 완료")

    # ── 테스트 ③ 서버 analyze ─────────────────────────────

    def _test_analyze(self) -> None:
        if self._image_path is None:
            self._log("warn", "이미지를 먼저 선택해 주세요.")
            return
        self._run_in_thread(self._do_analyze)

    def _do_analyze(self) -> None:
        self._sep("③ 서버 analyze API 호출")
        url = f"{self._server_var.get().rstrip('/')}/api/v1/analyze"
        self._log("info", f"POST {url}")
        self._log("info", f"이미지: {self._image_path}")
        try:
            with open(self._image_path, "rb") as f:
                files = {"image": (self._image_path.name, f, "image/png")}
                resp = requests.post(url, files=files, timeout=60)
            self._log("info", f"Status: {resp.status_code}")
            try:
                body = resp.json()
                self._log("ok" if resp.ok else "error",
                           f"Response:\n{json.dumps(body, ensure_ascii=False, indent=2)}")
                if resp.ok:
                    self._log("info", "→ 서버가 정상 응답했습니다.")
                    self._log("info", "→ CloudLogger가 백그라운드에서 POST /logs를 호출합니다.")
                    self._log("info", "→ 5초 후 GET /logs로 저장 여부를 확인하세요.")
            except Exception:
                self._log("error", f"Response (raw): {resp.text[:500]}")
        except Exception as e:
            self._log("error", f"예외: {type(e).__name__}: {e}")
        self._status_var.set("analyze 완료")

    # ── 테스트 ④ GET /logs ────────────────────────────────

    def _test_get_logs(self) -> None:
        self._run_in_thread(self._do_get_logs)

    def _do_get_logs(self) -> None:
        self._sep("④ GET /logs 조회")
        url = self._log_api_var.get().strip()
        today = datetime.now().strftime("%Y-%m-%d")
        params = {"date": today, "limit": 5}
        self._log("info", f"GET {url}?date={today}&limit=5")
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            self._log("info", f"Status: {resp.status_code}")
            if resp.ok:
                data = resp.json()
                count = data.get("count", 0)
                self._log("ok", f"오늘({today}) 로그 {count}건 조회됨")
                for log in data.get("logs", [])[:3]:
                    self._log("info",
                        f"  [{log.get('timestamp')}] {log.get('status')} - {log.get('image_name')}")
            else:
                self._log("error", f"Response: {resp.text}")
        except Exception as e:
            self._log("error", f"예외: {type(e).__name__}: {e}")
        self._status_var.set("GET 조회 완료")

    # ── 테스트 ⑤ 전체 진단 ───────────────────────────────

    def _run_full_diagnosis(self) -> None:
        self._run_in_thread(self._do_full_diagnosis)

    def _do_full_diagnosis(self) -> None:
        self._sep("⑤ 전체 진단 시작")

        # 환경 정보
        self._log("info", f"Server URL : {self._server_var.get()}")
        self._log("info", f"Log API URL: {self._log_api_var.get()}")

        # 1. DNS 확인
        self._sep("1/4 DNS 확인")
        import socket
        try:
            from urllib.parse import urlparse
            host = urlparse(self._log_api_var.get()).hostname
            self._log("info", f"DNS 조회: {host}")
            ip = socket.gethostbyname(host)
            self._log("ok", f"DNS 해석 성공: {host} → {ip}")
        except Exception as e:
            self._log("error", f"DNS 실패: {e}")
            self._log("error", "→ 네트워크가 해당 엔드포인트에 접근할 수 없습니다.")
            self._log("error", "→ VPN/VPC 연결 또는 URL을 확인하세요.")

        # 2. Health Check
        self._sep("2/4 서버 Health Check")
        self._do_health()

        # 3. 직접 POST
        self._sep("3/4 직접 POST /logs")
        self._do_direct_post()

        # 4. GET 확인
        self._sep("4/4 GET /logs 저장 확인")
        import time
        self._log("info", "2초 대기 후 조회...")
        time.sleep(2)
        self._do_get_logs()

        self._sep("진단 완료")
        self._status_var.set("전체 진단 완료")


def main() -> None:
    root = tk.Tk()
    CloudLogTesterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
