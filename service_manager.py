"""
Windows Service Manager GUI
NSSM을 이용해 server/main.py 와 Stator_Trk_Monitoring/Alarm_System.py 를
Windows 서비스로 등록/관리하는 GUI 도구입니다.
관리자 권한으로 실행해야 합니다.
"""

import ctypes
import logging
import os
import subprocess
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ── 파일 로깅 설정 (GUI 뜨기 전 크래시도 잡기 위해 최상단에 배치) ──────────────
LOG_FILE = Path(__file__).parent / "service_manager.log"
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
    # 콘솔에도 출력
    print(msg, file=sys.stderr)
    try:
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showerror("치명적 오류", f"오류가 발생했습니다.\n로그 파일을 확인하세요:\n{LOG_FILE}\n\n{exc_value}")
        _root.destroy()
    except Exception:
        pass

sys.excepthook = _excepthook
log.info("service_manager.py 시작")

# ── 서비스 정의 ──────────────────────────────────────────────────────────────
SERVICES = [
    {
        "key": "server",
        "name": "AIAlarmServer",
        "label": "AI Alarm Server (server/main.py)",
        "default_rel": os.path.join("server", "main.py"),
        "args": "",
    },
    {
        "key": "alarm",
        "name": "AIAlarmSystem",
        "label": "Alarm System (Stator_Trk_Monitoring/Alarm_System.py)",
        "default_rel": os.path.join("Stator_Trk_Monitoring", "Alarm_System.py"),
        "args": "",
    },
]


def is_admin() -> bool:
    try:
        result = ctypes.windll.shell32.IsUserAnAdmin()
        log.info("관리자 권한 확인: %s", bool(result))
        return bool(result)
    except Exception as e:
        log.warning("관리자 권한 확인 실패: %s", e)
        return False


def run_as_admin():
    """관리자 권한으로 재실행"""
    script = str(Path(__file__).resolve())
    python = str(Path(sys.executable).resolve())
    working_dir = str(Path(__file__).parent.resolve())
    log.info("재실행: python=%s, script=%s, cwd=%s", python, script, working_dir)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", python, f'"{script}"', working_dir, 1
    )
    sys.exit()


def find_winsw():
    """PATH 또는 프로젝트 루트에서 WinSW 실행파일 탐색"""
    log.debug("WinSW 탐색 시작")
    for candidate in ["WinSW.exe", "winsw.exe", "WinSW-x64.exe", "WinSW-net461.exe"]:
        # 스크립트 옆에 있는지 확인
        local = Path(__file__).parent / candidate
        if local.exists():
            log.info("WinSW 발견 (로컬): %s", local)
            return str(local)
        # PATH에 있는지 확인
        try:
            result = subprocess.run([candidate, "version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                log.info("WinSW 발견 (PATH): %s", candidate)
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    log.warning("WinSW를 찾을 수 없음")
    return None


def run_cmd(cmd, log_widget):
    """명령 실행 후 로그 위젯에 출력"""
    log.debug("명령 실행: %s", cmd)
    log_widget.insert(tk.END, f"\n> {' '.join(cmd)}\n")
    log_widget.see(tk.END)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        output = result.stdout + result.stderr
        log.debug("명령 결과 (rc=%d): %s", result.returncode, output.strip())
        log_widget.insert(tk.END, output or "(출력 없음)\n")
        log_widget.see(tk.END)
        return result.returncode, output
    except subprocess.TimeoutExpired:
        msg = "오류: 명령 시간 초과\n"
        log.error("명령 타임아웃: %s", cmd)
        log_widget.insert(tk.END, msg)
        return -1, msg
    except Exception as e:
        msg = f"오류: {e}\n"
        log.error("명령 실행 오류: %s / %s", cmd, e)
        log_widget.insert(tk.END, msg)
        return -1, msg


def get_service_status(service_name):
    """sc.exe로 서비스 상태 반환 (WinSW 불필요)"""
    try:
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True, text=True, timeout=10
        )
        if "RUNNING" in result.stdout:
            return "실행 중"
        elif "STOPPED" in result.stdout:
            return "중지됨"
        elif result.returncode != 0:
            return "미등록"
        return "알 수 없음"
    except Exception as e:
        log.warning("서비스 상태 확인 실패 [%s]: %s", service_name, e)
        return "알 수 없음"


def make_winsw_xml(svc_name, display_name, python, script, work_dir, log_dir):
    """WinSW XML 설정 파일 내용 생성"""
    return f"""<service>
  <id>{svc_name}</id>
  <name>{display_name}</name>
  <description>Auto-managed by Service Manager GUI</description>
  <executable>{python}</executable>
  <arguments>"{script}"</arguments>
  <workingdirectory>{work_dir}</workingdirectory>
  <logpath>{log_dir}</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
  <onfailure action="restart" delay="5 sec"/>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="20 sec"/>
  <startmode>Automatic</startmode>
</service>
"""


# ── 메인 GUI ─────────────────────────────────────────────────────────────────
class ServiceManagerApp(tk.Tk):
    def __init__(self):
        log.info("ServiceManagerApp 초기화 시작")
        super().__init__()
        self.title("Windows Service Manager")
        self.resizable(False, False)
        self.configure(bg="#f0f0f0")

        self.winsw_path = tk.StringVar()
        self.python_path = tk.StringVar(value=sys.executable)
        self.project_dir = tk.StringVar(value=str(Path(__file__).parent))

        # 서비스별 상태 변수
        self.svc_vars: dict[str, dict] = {}
        self._manual_procs: dict = {}  # key -> subprocess.Popen
        for svc in SERVICES:
            self.svc_vars[svc["key"]] = {
                "script": tk.StringVar(),
                "status": tk.StringVar(value="확인 중..."),
            }

        self._build_ui()
        log.info("UI 빌드 완료")
        self._auto_detect()
        log.info("자동 탐지 완료")
        self._refresh_all_status()
        log.info("ServiceManagerApp 초기화 완료")

    # ── UI 구성 ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # ── 상단: 경로 설정 ──
        path_frame = ttk.LabelFrame(self, text="경로 설정", padding=10)
        path_frame.grid(row=0, column=0, sticky="ew", **pad)

        self._path_row(path_frame, 0, "WinSW 경로:", self.winsw_path,
                       lambda: self._browse_file(self.winsw_path, "WinSW.exe", [("exe", "*.exe")]))
        self._path_row(path_frame, 1, "Python 경로:", self.python_path,
                       lambda: self._browse_file(self.python_path, "python.exe", [("exe", "*.exe")]))
        self._path_row(path_frame, 2, "프로젝트 폴더:", self.project_dir,
                       lambda: self._browse_dir(self.project_dir))

        ttk.Button(path_frame, text="스크립트 경로 자동 설정",
                   command=self._apply_project_dir).grid(
            row=3, column=0, columnspan=3, pady=(8, 0))
        ttk.Label(path_frame,
                  text="WinSW 다운로드: https://github.com/winsw/winsw/releases  (WinSW-x64.exe 를 이 폴더에 복사)",
                  foreground="gray", font=("", 8)).grid(row=4, column=0, columnspan=3, pady=(4, 0))

        # ── 서비스 카드 ──
        for i, svc in enumerate(SERVICES):
            self._build_service_card(i + 1, svc)

        # ── 로그 ──
        log_frame = ttk.LabelFrame(self, text="실행 로그", padding=10)
        log_frame.grid(row=len(SERVICES) + 1, column=0, sticky="nsew", **pad)

        self.log = scrolledtext.ScrolledText(
            log_frame, width=80, height=12, state="normal",
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4"
        )
        self.log.pack(fill="both", expand=True)

        ttk.Button(self, text="로그 지우기",
                   command=lambda: self.log.delete("1.0", tk.END)).grid(
            row=len(SERVICES) + 2, column=0, pady=(0, 10))

    def _path_row(self, parent, row, label, var, browse_cmd):
        ttk.Label(parent, text=label, width=14, anchor="e").grid(row=row, column=0, sticky="e", padx=(0, 5))
        ttk.Entry(parent, textvariable=var, width=55).grid(row=row, column=1, sticky="ew")
        ttk.Button(parent, text="찾기", width=6, command=browse_cmd).grid(row=row, column=2, padx=(5, 0))

    def _build_service_card(self, row: int, svc: dict):
        key = svc["key"]
        frame = ttk.LabelFrame(self, text=svc["label"], padding=10)
        frame.grid(row=row, column=0, sticky="ew", padx=10, pady=5)

        # 스크립트 경로
        ttk.Label(frame, text="스크립트:", width=10, anchor="e").grid(row=0, column=0, sticky="e")
        ttk.Entry(frame, textvariable=self.svc_vars[key]["script"], width=55).grid(row=0, column=1, sticky="ew")
        ttk.Button(frame, text="찾기", width=6,
                   command=lambda k=key: self._browse_file(
                       self.svc_vars[k]["script"], "*.py", [("Python", "*.py")]
                   )).grid(row=0, column=2, padx=(5, 0))

        # 버튼 행 1: 수동 실행
        run_frame = ttk.Frame(frame)
        run_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        ttk.Label(run_frame, text="수동 실행:").pack(side="left", padx=(0, 6))
        ttk.Button(run_frame, text="▶ 실행 (새 창)",
                   command=lambda s=svc: self._run_manual(s, new_window=True)).pack(side="left", padx=2)
        ttk.Button(run_frame, text="▶ 실행 (백그라운드)",
                   command=lambda s=svc: self._run_manual(s, new_window=False)).pack(side="left", padx=2)
        ttk.Button(run_frame, text="■ 수동 중지",
                   command=lambda s=svc: self._stop_manual(s)).pack(side="left", padx=2)

        # 버튼 행 2: 서비스 관리
        svc_frame = ttk.Frame(frame)
        svc_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        ttk.Label(svc_frame, text="서비스:     ").pack(side="left", padx=(0, 6))
        ttk.Button(svc_frame, text="등록", width=7,
                   command=lambda s=svc: self._install(s)).pack(side="left", padx=2)
        ttk.Button(svc_frame, text="시작", width=7,
                   command=lambda s=svc: self._start(s)).pack(side="left", padx=2)
        ttk.Button(svc_frame, text="중지", width=7,
                   command=lambda s=svc: self._stop(s)).pack(side="left", padx=2)
        ttk.Button(svc_frame, text="제거", width=7,
                   command=lambda s=svc: self._remove(s)).pack(side="left", padx=2)
        ttk.Button(svc_frame, text="새로고침", width=8,
                   command=lambda s=svc: self._refresh_status(s)).pack(side="left", padx=2)

        # 상태 표시
        status_lbl = ttk.Label(frame, textvariable=self.svc_vars[key]["status"],
                                foreground="gray", font=("", 9, "italic"))
        status_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

    # ── 자동 탐지 ─────────────────────────────────────────────────────────────
    def _auto_detect(self):
        winsw = find_winsw()
        if winsw:
            self.winsw_path.set(winsw)
            self._log(f"WinSW 자동 감지: {winsw}\n")
        else:
            self._log(
                "WinSW를 찾을 수 없습니다.\n"
                "https://github.com/winsw/winsw/releases 에서\n"
                "WinSW-x64.exe 를 다운로드해 이 폴더에 복사하세요.\n"
            )
        self._apply_project_dir()

    def _apply_project_dir(self):
        base = Path(self.project_dir.get())
        for svc in SERVICES:
            path = base / svc["default_rel"]
            self.svc_vars[svc["key"]]["script"].set(str(path))

    # ── 상태 새로고침 ─────────────────────────────────────────────────────────
    def _refresh_status(self, svc: dict):
        status = get_service_status(svc["name"])
        self.svc_vars[svc["key"]]["status"].set(f"상태: {status}")
        self._log(f"[{svc['name']}] 상태: {status}\n")

    def _refresh_all_status(self):
        for svc in SERVICES:
            status = get_service_status(svc["name"])
            self.svc_vars[svc["key"]]["status"].set(f"상태: {status}")

    # ── 수동 실행 ─────────────────────────────────────────────────────────────
    def _run_manual(self, svc: dict, new_window: bool = True):
        key = svc["key"]
        script = self.svc_vars[key]["script"].get().strip()
        python = self.python_path.get().strip()
        project = self.project_dir.get().strip()

        if not Path(script).exists():
            messagebox.showerror("오류", f"스크립트를 찾을 수 없습니다:\n{script}")
            return

        # 이미 실행 중이면 중지 먼저
        if key in self._manual_procs and self._manual_procs[key].poll() is None:
            if not messagebox.askyesno("확인", f"[{svc['name']}] 이미 실행 중입니다.\n재시작하시겠습니까?"):
                return
            self._stop_manual(svc)

        self._log(f"\n=== [{svc['name']}] 수동 실행 ({'새 창' if new_window else '백그라운드'}) ===\n")
        self._log(f"  python: {python}\n  script: {script}\n  cwd: {project}\n")
        log.info("수동 실행: %s %s (new_window=%s)", python, script, new_window)

        try:
            if new_window:
                # 새 콘솔 창으로 실행
                proc = subprocess.Popen(
                    [python, script],
                    cwd=project,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                # 백그라운드 실행 - 로그 파일로 출력
                out_file = open(Path(project) / f"manual_{key}_stdout.log", "w", encoding="utf-8")
                proc = subprocess.Popen(
                    [python, script],
                    cwd=project,
                    stdout=out_file,
                    stderr=out_file,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            self._manual_procs[key] = proc
            self.svc_vars[key]["status"].set(f"상태: 수동 실행 중 (PID {proc.pid})")
            self._log(f"  PID: {proc.pid}\n")
            log.info("수동 실행 성공 PID=%d", proc.pid)
        except Exception as e:
            self._log(f"  실행 실패: {e}\n")
            log.error("수동 실행 실패: %s", e)
            messagebox.showerror("오류", f"실행 실패:\n{e}")

    def _stop_manual(self, svc: dict):
        key = svc["key"]
        proc = self._manual_procs.get(key)
        if proc is None or proc.poll() is not None:
            self._log(f"[{svc['name']}] 수동 실행 중인 프로세스 없음\n")
            return
        self._log(f"\n=== [{svc['name']}] 수동 실행 중지 (PID {proc.pid}) ===\n")
        log.info("수동 중지 PID=%d", proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        self.svc_vars[key]["status"].set("상태: 수동 중지됨")
        self._log("  중지 완료\n")

    # ── WinSW 작업 ────────────────────────────────────────────────────────────
    def _get_winsw(self):
        winsw = self.winsw_path.get().strip()
        if not winsw:
            messagebox.showerror("오류", "WinSW 경로를 지정하세요.\nhttps://github.com/winsw/winsw/releases")
            return None
        if not Path(winsw).exists():
            messagebox.showerror("오류", f"WinSW 파일을 찾을 수 없습니다:\n{winsw}")
            return None
        return winsw

    def _install(self, svc: dict):
        winsw = self._get_winsw()
        if not winsw:
            return

        script = self.svc_vars[svc["key"]]["script"].get().strip()
        python = self.python_path.get().strip()
        project = self.project_dir.get().strip()

        if not Path(script).exists():
            messagebox.showerror("오류", f"스크립트를 찾을 수 없습니다:\n{script}")
            return

        # WinSW는 자신과 같은 이름의 XML을 읽음 → 서비스명.xml + 서비스명.exe 복사
        svc_dir = Path(project)
        xml_path = svc_dir / f"{svc['name']}.xml"
        exe_path = svc_dir / f"{svc['name']}.exe"
        log_dir  = svc_dir / f"logs_{svc['key']}"
        log_dir.mkdir(exist_ok=True)

        # XML 생성
        xml_content = make_winsw_xml(
            svc_name=svc["name"],
            display_name=svc["label"],
            python=python,
            script=script,
            work_dir=project,
            log_dir=str(log_dir),
        )
        xml_path.write_text(xml_content, encoding="utf-8")
        self._log(f"\n=== [{svc['name']}] XML 생성: {xml_path} ===\n{xml_content}\n")

        # WinSW exe를 서비스명.exe 로 복사 (WinSW 규칙)
        import shutil
        shutil.copy2(winsw, str(exe_path))
        self._log(f"WinSW 복사: {winsw} → {exe_path}\n")

        # 서비스 등록
        self._log(f"=== [{svc['name']}] 서비스 등록 ===\n")
        code, _ = run_cmd([str(exe_path), "install"], self.log)
        if code == 0:
            self._refresh_status(svc)
            messagebox.showinfo("완료", f"[{svc['name']}] 서비스 등록 완료.\n시작 버튼을 눌러 실행하세요.")
        else:
            messagebox.showerror("오류", f"[{svc['name']}] 서비스 등록 실패.\n로그를 확인하세요.")

    def _start(self, svc: dict):
        winsw = self._get_winsw()
        if not winsw:
            return
        exe_path = Path(self.project_dir.get()) / f"{svc['name']}.exe"
        self._log(f"\n=== [{svc['name']}] 시작 ===\n")
        run_cmd([str(exe_path), "start"], self.log)
        self.after(1500, lambda: self._refresh_status(svc))

    def _stop(self, svc: dict):
        winsw = self._get_winsw()
        if not winsw:
            return
        exe_path = Path(self.project_dir.get()) / f"{svc['name']}.exe"
        self._log(f"\n=== [{svc['name']}] 중지 ===\n")
        run_cmd([str(exe_path), "stop"], self.log)
        self.after(1500, lambda: self._refresh_status(svc))

    def _remove(self, svc: dict):
        if not messagebox.askyesno("확인", f"[{svc['name']}] 서비스를 제거하시겠습니까?"):
            return
        exe_path = Path(self.project_dir.get()) / f"{svc['name']}.exe"
        self._log(f"\n=== [{svc['name']}] 제거 ===\n")
        run_cmd([str(exe_path), "stop"], self.log)
        run_cmd([str(exe_path), "uninstall"], self.log)
        self.after(1500, lambda: self._refresh_status(svc))

    # ── 유틸 ──────────────────────────────────────────────────────────────────
    def _browse_file(self, var: tk.StringVar, title: str, filetypes: list):
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if path:
            var.set(path)

    def _browse_dir(self, var: tk.StringVar):
        path = filedialog.askdirectory(title="프로젝트 폴더 선택")
        if path:
            var.set(path)
            self._apply_project_dir()

    def _log(self, msg: str):
        self.log.insert(tk.END, msg)
        self.log.see(tk.END)


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Python %s / 플랫폼: %s", sys.version, sys.platform)
    log.info("작업 디렉토리: %s", Path.cwd())

    if not is_admin():
        _root = tk.Tk()
        _root.withdraw()
        answer = messagebox.askyesno(
            "관리자 권한 필요",
            "Windows 서비스 등록에는 관리자 권한이 필요합니다.\n관리자 권한으로 재실행하시겠습니까?"
        )
        _root.destroy()
        if answer:
            log.info("관리자 권한으로 재실행 시도")
            run_as_admin()
        log.info("관리자 권한 없이 종료")
        sys.exit()

    try:
        log.info("메인 앱 시작")
        app = ServiceManagerApp()
        app.mainloop()
        log.info("앱 정상 종료")
    except Exception as e:
        log.critical("앱 실행 중 오류: %s", traceback.format_exc())
        raise
