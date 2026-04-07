"""
AI 알람 시스템 - 프로세스 관리자
"""

import json
import logging
import os
import subprocess
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

LOG_FILE = Path(__file__).parent / "service_manager.log"
CONFIG_FILE = Path(__file__).parent / "service_manager_config.json"
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
log = logging.getLogger(__name__)


def _excepthook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log.critical("Unhandled exception:\n%s", msg)
    try:
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showerror("오류 발생", f"예기치 않은 오류가 발생했습니다.\n\n{exc_value}")
        _root.destroy()
    except Exception:
        pass


sys.excepthook = _excepthook

# ── 프로세스 정의 ─────────────────────────────────────────────────────────────
SERVICES = [
    {
        "key": "server",
        "name": "AI 분석 서버",
        "desc": "이미지를 분석하고 알람을 판단하는 서버입니다.",
        "default_rel": os.path.join("server", "main.py"),
        "module": "server.main",
    },
    {
        "key": "alarm",
        "name": "알람 모니터링",
        "desc": "설비 상태를 모니터링하고 알람을 표시합니다.",
        "default_rel": os.path.join("Stator_Trk_Monitoring", "Alarm_System.py"),
        "module": None,
    },
]

# 색상 팔레트
CLR_BG       = "#F5F6FA"
CLR_CARD     = "#FFFFFF"
CLR_BORDER   = "#E0E0E0"
CLR_PRIMARY  = "#2563EB"
CLR_DANGER   = "#DC2626"
CLR_SUCCESS  = "#16A34A"
CLR_WARN     = "#D97706"
CLR_TEXT     = "#1E293B"
CLR_SUBTEXT  = "#64748B"
CLR_LOG_BG   = "#1E293B"
CLR_LOG_FG   = "#CBD5E1"


class ServiceManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI 알람 시스템 관리자")
        self.resizable(False, False)
        self.configure(bg=CLR_BG)

        self.python_path = tk.StringVar(value=sys.executable)
        self.project_dir = tk.StringVar(value=str(Path(__file__).parent.parent))
        self._advanced_open = tk.BooleanVar(value=False)

        self.svc_vars: dict[str, dict] = {}
        self._manual_procs: dict = {}
        for svc in SERVICES:
            self.svc_vars[svc["key"]] = {
                "script": tk.StringVar(),
                "status_text": tk.StringVar(value="중지됨"),
                "dot": None,   # Canvas 인디케이터
            }

        self._build_ui()
        self._load_config()

        for var in [self.python_path, self.project_dir]:
            var.trace_add("write", lambda *_: self._save_config())
        for svc in SERVICES:
            self.svc_vars[svc["key"]]["script"].trace_add("write", lambda *_: self._save_config())

    # ── UI 구성 ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # 헤더
        hdr = tk.Frame(self, bg=CLR_PRIMARY, pady=14)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="🖥  AI 알람 시스템 관리자", bg=CLR_PRIMARY, fg="white",
                 font=("맑은 고딕", 14, "bold")).pack()
        tk.Label(hdr, text="프로그램을 시작하거나 중지할 수 있습니다.", bg=CLR_PRIMARY, fg="#BFDBFE",
                 font=("맑은 고딕", 9)).pack()

        # 프로그램 카드
        cards_frame = tk.Frame(self, bg=CLR_BG)
        cards_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(14, 4))
        for i, svc in enumerate(SERVICES):
            self._build_card(cards_frame, i, svc)

        # 고급 설정 (접기/펼치기)
        adv_toggle = tk.Frame(self, bg=CLR_BG)
        adv_toggle.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 0))
        tk.Button(adv_toggle, text="⚙  고급 설정 ▾", bg=CLR_BG, fg=CLR_SUBTEXT,
                  relief="flat", cursor="hand2", font=("맑은 고딕", 9),
                  command=self._toggle_advanced).pack(anchor="w")

        self._adv_frame = tk.Frame(self, bg=CLR_CARD, relief="solid", bd=1)
        # 고급 설정 내용
        self._build_advanced(self._adv_frame)

        # 로그
        log_outer = tk.Frame(self, bg=CLR_BG)
        log_outer.grid(row=4, column=0, sticky="nsew", padx=16, pady=(8, 4))
        tk.Label(log_outer, text="실행 기록", bg=CLR_BG, fg=CLR_SUBTEXT,
                 font=("맑은 고딕", 9, "bold")).pack(anchor="w")
        self.log_widget = scrolledtext.ScrolledText(
            log_outer, width=72, height=10,
            font=("Consolas", 9), bg=CLR_LOG_BG, fg=CLR_LOG_FG,
            relief="flat", bd=0, state="normal"
        )
        self.log_widget.pack(fill="both", expand=True, pady=(2, 0))

        # 하단 버튼
        bottom = tk.Frame(self, bg=CLR_BG)
        bottom.grid(row=5, column=0, pady=(4, 12))
        tk.Button(bottom, text="기록 지우기", bg=CLR_BG, fg=CLR_SUBTEXT,
                  relief="flat", cursor="hand2", font=("맑은 고딕", 9),
                  command=lambda: self.log_widget.delete("1.0", tk.END)).pack()

    def _build_card(self, parent, idx: int, svc: dict):
        key = svc["key"]
        card = tk.Frame(parent, bg=CLR_CARD, relief="solid", bd=1,
                        highlightbackground=CLR_BORDER, highlightthickness=1)
        card.grid(row=0, column=idx, padx=6, pady=4, sticky="nsew")
        parent.columnconfigure(idx, weight=1)

        # 상단: 이름 + 상태 인디케이터
        top = tk.Frame(card, bg=CLR_CARD)
        top.pack(fill="x", padx=14, pady=(12, 4))

        dot_canvas = tk.Canvas(top, width=12, height=12, bg=CLR_CARD,
                               highlightthickness=0)
        dot_canvas.pack(side="left", padx=(0, 6))
        dot_id = dot_canvas.create_oval(1, 1, 11, 11, fill=CLR_DANGER, outline="")
        self.svc_vars[key]["dot"] = (dot_canvas, dot_id)

        tk.Label(top, text=svc["name"], bg=CLR_CARD, fg=CLR_TEXT,
                 font=("맑은 고딕", 11, "bold")).pack(side="left")

        # 설명
        tk.Label(card, text=svc["desc"], bg=CLR_CARD, fg=CLR_SUBTEXT,
                 font=("맑은 고딕", 9), wraplength=200, justify="left").pack(
            anchor="w", padx=14, pady=(0, 8))

        # 상태 텍스트
        status_lbl = tk.Label(card, textvariable=self.svc_vars[key]["status_text"],
                               bg=CLR_CARD, fg=CLR_SUBTEXT, font=("맑은 고딕", 9))
        status_lbl.pack(anchor="w", padx=14)
        self.svc_vars[key]["status_label"] = status_lbl

        # 버튼
        btn_frame = tk.Frame(card, bg=CLR_CARD)
        btn_frame.pack(fill="x", padx=14, pady=(10, 14))

        tk.Button(btn_frame, text="▶  시작 (창 표시)", bg=CLR_PRIMARY, fg="white",
                  relief="flat", cursor="hand2", font=("맑은 고딕", 10, "bold"),
                  padx=10, pady=6,
                  command=lambda s=svc: self._run(s, new_window=True)).pack(side="left", padx=(0, 4))

        tk.Button(btn_frame, text="▶  백그라운드", bg="#3B82F6", fg="white",
                  relief="flat", cursor="hand2", font=("맑은 고딕", 10),
                  padx=10, pady=6,
                  command=lambda s=svc: self._run(s, new_window=False)).pack(side="left", padx=(0, 4))

        tk.Button(btn_frame, text="⬛  중지", bg="#F1F5F9", fg=CLR_TEXT,
                  relief="flat", cursor="hand2", font=("맑은 고딕", 10),
                  padx=10, pady=6,
                  command=lambda s=svc: self._stop(s)).pack(side="left", padx=(0, 4))

        tk.Button(btn_frame, text="🧹  정리", bg="#FEF2F2", fg=CLR_DANGER,
                  relief="flat", cursor="hand2", font=("맑은 고딕", 10),
                  padx=10, pady=6,
                  command=lambda s=svc: self._kill_orphans(s)).pack(side="left")
    def _build_advanced(self, parent):
        pad = {"padx": 12, "pady": 4}
        tk.Label(parent, text="Python 실행 파일", bg=CLR_CARD, fg=CLR_SUBTEXT,
                 font=("맑은 고딕", 9)).grid(row=0, column=0, sticky="w", **pad)
        self._adv_path_row(parent, 1, self.python_path,
                           lambda: self._browse_file(self.python_path, "python.exe", [("exe", "*.exe")]))

        tk.Label(parent, text="프로젝트 폴더", bg=CLR_CARD, fg=CLR_SUBTEXT,
                 font=("맑은 고딕", 9)).grid(row=2, column=0, sticky="w", **pad)
        self._adv_path_row(parent, 3, self.project_dir,
                           lambda: self._browse_dir(self.project_dir))

        for i, svc in enumerate(SERVICES):
            key = svc["key"]
            tk.Label(parent, text=f"{svc['name']} 파일", bg=CLR_CARD, fg=CLR_SUBTEXT,
                     font=("맑은 고딕", 9)).grid(row=4 + i * 2, column=0, sticky="w", **pad)
            self._adv_path_row(parent, 5 + i * 2, self.svc_vars[key]["script"],
                               lambda k=key: self._browse_file(
                                   self.svc_vars[k]["script"], "*.py", [("Python", "*.py")]))

        tk.Button(parent, text="경로 자동 설정", bg=CLR_BG, fg=CLR_PRIMARY,
                  relief="flat", cursor="hand2", font=("맑은 고딕", 9),
                  command=self._apply_project_dir).grid(
            row=4 + len(SERVICES) * 2, column=0, columnspan=3,
            padx=12, pady=(4, 10), sticky="w")

    def _adv_path_row(self, parent, row, var, browse_cmd):
        entry = tk.Entry(parent, textvariable=var, width=52, fg=CLR_TEXT,
                         font=("맑은 고딕", 9), relief="solid", bd=1)
        entry.grid(row=row, column=0, padx=(12, 4), pady=2, sticky="ew")
        tk.Button(parent, text="찾기", bg=CLR_BG, fg=CLR_TEXT, relief="flat",
                  cursor="hand2", font=("맑은 고딕", 9), padx=6,
                  command=browse_cmd).grid(row=row, column=1, padx=(0, 12), pady=2)

    def _toggle_advanced(self):
        if self._advanced_open.get():
            self._adv_frame.grid_forget()
            self._advanced_open.set(False)
        else:
            self._adv_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(2, 4))
            self._advanced_open.set(True)

    # ── 설정 저장/로드 ────────────────────────────────────────────────────────
    def _save_config(self):
        data = {
            "python_path": self.python_path.get(),
            "project_dir": self.project_dir.get(),
            "scripts": {svc["key"]: self.svc_vars[svc["key"]]["script"].get() for svc in SERVICES},
        }
        try:
            CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("설정 저장 실패: %s", e)

    def _load_config(self):
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if data.get("python_path"):
                    self.python_path.set(data["python_path"])
                if data.get("project_dir"):
                    self.project_dir.set(data["project_dir"])
                for svc in SERVICES:
                    saved = data.get("scripts", {}).get(svc["key"], "")
                    if saved:
                        self.svc_vars[svc["key"]]["script"].set(saved)
                self._log("설정을 불러왔습니다.\n")
                return
            except Exception as e:
                log.warning("설정 로드 실패: %s", e)
        self._apply_project_dir()

    def _apply_project_dir(self):
        base = Path(self.project_dir.get())
        for svc in SERVICES:
            self.svc_vars[svc["key"]]["script"].set(str(base / svc["default_rel"]))

    # ── 상태 인디케이터 업데이트 ──────────────────────────────────────────────
    def _set_status(self, key: str, text: str, color: str):
        self.svc_vars[key]["status_text"].set(text)
        canvas, dot_id = self.svc_vars[key]["dot"]
        canvas.itemconfig(dot_id, fill=color)

    # ── 실행/중지 ─────────────────────────────────────────────────────────────
    def _run(self, svc: dict, new_window: bool = False):
        key = svc["key"]
        script = self.svc_vars[key]["script"].get().strip()
        python = self.python_path.get().strip()
        module = svc.get("module")

        if not Path(script).exists():
            messagebox.showerror("파일을 찾을 수 없음",
                                 f"'{svc['name']}' 파일을 찾을 수 없습니다.\n\n"
                                 f"고급 설정에서 파일 경로를 확인해 주세요.")
            return

        if key in self._manual_procs and self._manual_procs[key].poll() is None:
            if not messagebox.askyesno("이미 실행 중",
                                       f"'{svc['name']}'이(가) 이미 실행 중입니다.\n다시 시작하시겠습니까?"):
                return
            self._stop(svc)

        python_dir = Path(python).parent
        py = str(python_dir / ("python.exe" if new_window else "pythonw.exe"))
        if not Path(py).exists():
            py = python

        if module:
            cwd = self.project_dir.get().strip()
            cmd = [py, "-m", module]
        else:
            cwd = str(Path(script).parent)
            cmd = [py, script]

        self._log(f"\n[{svc['name']}] 시작 중...\n")
        self._set_status(key, "시작 중...", CLR_WARN)

        try:
            if new_window:
                proc = subprocess.Popen(cmd, cwd=cwd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                # 백그라운드: 창 없이 실행하되 poll()이 동작하도록 분리하지 않음
                proc = subprocess.Popen(
                    cmd, cwd=cwd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            self._manual_procs[key] = proc
            self._set_status(key, f"실행 중  (PID {proc.pid})", CLR_SUCCESS)
            self._log(f"[{svc['name']}] 실행됨 (PID {proc.pid})\n")
            # 2초 후 즉시 종료 여부 확인, 이후 10초마다 지속 모니터링
            self.after(2000, lambda p=proc, s=svc, k=key: self._check_alive(p, s, k))
        except Exception as e:
            self._set_status(key, "실행 실패", CLR_DANGER)
            self._log(f"[{svc['name']}] 실행 실패: {e}\n")
            messagebox.showerror("실행 실패", f"'{svc['name']}' 실행에 실패했습니다.\n\n{e}")

    def _check_alive(self, proc, svc: dict, key: str):
        # 이미 다른 프로세스로 교체됐으면 무시
        if self._manual_procs.get(key) is not proc:
            return
        rc = proc.poll()
        if rc is not None:
            self._set_status(key, f"오류로 종료됨 (코드 {rc})", CLR_DANGER)
            self._log(f"[{svc['name']}] ⚠ 프로그램이 예기치 않게 종료됐습니다 (코드 {rc})\n")
            messagebox.showwarning(
                "프로그램 종료됨",
                f"'{svc['name']}'이(가) 예기치 않게 종료됐습니다.\n\n"
                f"설정이 올바른지 확인하거나 관리자에게 문의하세요.\n(종료 코드: {rc})"
            )
        else:
            # 10초마다 계속 모니터링
            self.after(10000, lambda p=proc, s=svc, k=key: self._check_alive(p, s, k))

    def _stop(self, svc: dict):
        key = svc["key"]
        proc = self._manual_procs.get(key)
        if proc is None or proc.poll() is not None:
            self._log(f"[{svc['name']}] 실행 중인 프로그램 없음\n")
            messagebox.showinfo("알림", f"'{svc['name']}'은(는) 현재 실행 중이 아닙니다.")
            return
        self._log(f"[{svc['name']}] 중지 중...\n")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._set_status(key, "중지됨", CLR_DANGER)
        self._log(f"[{svc['name']}] 중지 완료\n")

    # ── 잔여 프로세스 강제 종료 ───────────────────────────────────────────────
    def _kill_orphans(self, svc: dict):
        key = svc["key"]
        script = self.svc_vars[key]["script"].get().strip()
        module = svc.get("module")
        # 매칭 키워드: module 방식이면 모듈명, 아니면 스크립트 파일명
        keyword = module if module else Path(script).name

        try:
            import psutil
        except ImportError:
            messagebox.showerror(
                "psutil 없음",
                "이 기능은 psutil 라이브러리가 필요합니다.\n\n"
                "터미널에서 아래 명령을 실행하세요:\n  pip install psutil"
            )
            return

        killed = []
        my_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.pid == my_pid:
                    continue
                cmdline = " ".join(proc.info["cmdline"] or [])
                if keyword in cmdline and "python" in proc.info["name"].lower():
                    proc.kill()
                    killed.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if killed:
            self._set_status(key, "중지됨", CLR_DANGER)
            self._manual_procs.pop(key, None)
            self._log(f"[{svc['name']}] 🧹 잔여 프로세스 {len(killed)}개 종료: PID {killed}\n")
            messagebox.showinfo("정리 완료",
                                f"'{svc['name']}' 관련 프로세스 {len(killed)}개를 종료했습니다.\n"
                                f"PID: {killed}")
        else:
            self._log(f"[{svc['name']}] 🧹 정리할 잔여 프로세스 없음\n")
            messagebox.showinfo("정리 완료", f"'{svc['name']}' 관련 실행 중인 프로세스가 없습니다.")

    # ── 유틸 ──────────────────────────────────────────────────────────────────    def _browse_file(self, var: tk.StringVar, title: str, filetypes: list):
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if path:
            var.set(path)

    def _browse_dir(self, var: tk.StringVar):
        path = filedialog.askdirectory(title="프로젝트 폴더 선택")
        if path:
            var.set(path)
            self._apply_project_dir()

    def _log(self, msg: str):
        self.log_widget.insert(tk.END, msg)
        self.log_widget.see(tk.END)
        log.info(msg.strip())


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if Path(sys.executable).stem.lower() == "python":
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if pythonw.exists():
            import subprocess as _sp
            _sp.Popen([str(pythonw)] + sys.argv, cwd=str(Path(__file__).parent))
            sys.exit()

    log.info("Python %s / 플랫폼: %s", sys.version, sys.platform)

    try:
        app = ServiceManagerApp()
        app.mainloop()
        log.info("앱 정상 종료")
    except Exception:
        log.critical("앱 실행 중 오류: %s", traceback.format_exc())
        raise
