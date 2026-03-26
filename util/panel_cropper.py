"""HMI 패널 이미지 크롭 유틸리티

전체 HMI 이미지(1920x1170)를 4개 패널로 분할하여 저장합니다.
  top_left     → S520
  top_right    → S530
  bottom_left  → S540
  bottom_right → S810

Usage:
    python util/panel_cropper.py
"""

import io
import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 2x2 크롭 설정 (비율 기반)
PANEL_CROPS = {
    "top_left":     (0.0, 0.0, 0.5, 0.5),
    "top_right":    (0.5, 0.0, 1.0, 0.5),
    "bottom_left":  (0.0, 0.5, 0.5, 1.0),
    "bottom_right": (0.5, 0.5, 1.0, 1.0),
}

PANEL_LABELS = {
    "top_left":     "S520",
    "top_right":    "S530",
    "bottom_left":  "S540",
    "bottom_right": "S810",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def crop_image(image_path: Path, output_dir: Path) -> list[Path]:
    """이미지를 4개 패널로 크롭하여 output_dir에 저장."""
    img = Image.open(image_path)
    w, h = img.size
    saved = []

    for pos, (lf, uf, rf, bf) in PANEL_CROPS.items():
        box = (int(w * lf), int(h * uf), int(w * rf), int(h * bf))
        cropped = img.crop(box)
        label = PANEL_LABELS[pos]
        out_name = f"{image_path.stem}_{label}{image_path.suffix}"
        out_path = output_dir / out_name
        cropped.save(out_path)
        saved.append(out_path)

    return saved


class PanelCropperGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("HMI Panel Cropper")
        self.root.geometry("700x520")
        self.root.minsize(600, 400)

        self._preview_photo = None
        self._build_ui()

    def _build_ui(self) -> None:
        # ── 폴더 설정 ──────────────────────────────────────────────────
        folder_frame = ttk.LabelFrame(self.root, text="Folders", padding=8)
        folder_frame.pack(fill=tk.X, padx=10, pady=(10, 4))

        ttk.Label(folder_frame, text="Input:").grid(row=0, column=0, sticky=tk.W)
        self._input_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self._input_var, width=55).grid(row=0, column=1, padx=4)
        ttk.Button(folder_frame, text="Browse", command=self._browse_input).grid(row=0, column=2)

        ttk.Label(folder_frame, text="Output:").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self._output_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self._output_var, width=55).grid(row=1, column=1, padx=4, pady=(4, 0))
        ttk.Button(folder_frame, text="Browse", command=self._browse_output).grid(row=1, column=2, pady=(4, 0))

        # ── 미리보기 ───────────────────────────────────────────────────
        preview_frame = ttk.LabelFrame(self.root, text="Preview (first image)", padding=4)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        self._canvas = tk.Canvas(preview_frame, bg="#2b2b2b", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # ── 진행 상황 ──────────────────────────────────────────────────
        prog_frame = ttk.Frame(self.root, padding=(10, 0))
        prog_frame.pack(fill=tk.X)

        self._progress = ttk.Progressbar(prog_frame, mode="determinate")
        self._progress.pack(fill=tk.X, pady=(0, 4))

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(prog_frame, textvariable=self._status_var).pack(anchor=tk.W)

        # ── 버튼 ───────────────────────────────────────────────────────
        btn_frame = ttk.Frame(self.root, padding=(10, 4))
        btn_frame.pack(fill=tk.X)

        self._crop_btn = ttk.Button(btn_frame, text="Crop All", command=self._on_crop)
        self._crop_btn.pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="Preview", command=self._on_preview).pack(side=tk.LEFT, padx=6)

    # ── 폴더 선택 ──────────────────────────────────────────────────────

    def _browse_input(self) -> None:
        folder = filedialog.askdirectory(title="Select input folder")
        if folder:
            self._input_var.set(folder)
            self._on_preview()

    def _browse_output(self) -> None:
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self._output_var.set(folder)

    # ── 미리보기 ───────────────────────────────────────────────────────

    def _on_preview(self) -> None:
        input_dir = Path(self._input_var.get())
        if not input_dir.is_dir():
            return
        images = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        if not images:
            return
        self._show_preview(images[0])

    def _show_preview(self, image_path: Path) -> None:
        try:
            img = Image.open(image_path)
            w_c = self._canvas.winfo_width() or 600
            h_c = self._canvas.winfo_height() or 300
            ratio = min(w_c / img.width, h_c / img.height)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

            # Draw crop grid lines
            draw_w, draw_h = img.size
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.line([(draw_w // 2, 0), (draw_w // 2, draw_h)], fill="yellow", width=2)
            draw.line([(0, draw_h // 2), (draw_w, draw_h // 2)], fill="yellow", width=2)
            for pos, label in PANEL_LABELS.items():
                lf, uf, _, _ = PANEL_CROPS[pos]
                x = int(draw_w * lf) + 8
                y = int(draw_h * uf) + 8
                draw.text((x, y), label, fill="yellow")

            self._preview_photo = ImageTk.PhotoImage(img)
            self._canvas.delete("all")
            self._canvas.create_image(w_c // 2, h_c // 2, image=self._preview_photo, anchor=tk.CENTER)
        except Exception as exc:
            logger.warning("Preview failed: %s", exc)

    # ── 크롭 실행 ──────────────────────────────────────────────────────

    def _on_crop(self) -> None:
        input_dir = Path(self._input_var.get())
        output_dir = Path(self._output_var.get())

        if not input_dir.is_dir():
            messagebox.showerror("Error", "Input folder not found.")
            return
        if not self._output_var.get():
            messagebox.showerror("Error", "Please select an output folder.")
            return

        images = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        if not images:
            messagebox.showinfo("Info", "No images found in input folder.")
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        self._crop_btn.configure(state=tk.DISABLED)
        self._progress["maximum"] = len(images)
        self._progress["value"] = 0

        threading.Thread(
            target=self._run_crop,
            args=(images, output_dir),
            daemon=True,
        ).start()

    def _run_crop(self, images: list[Path], output_dir: Path) -> None:
        total = len(images)
        done = 0
        errors = 0

        for img_path in images:
            try:
                crop_image(img_path, output_dir)
                done += 1
            except Exception as exc:
                errors += 1
                logger.error("Failed to crop %s: %s", img_path.name, exc)

            self.root.after(0, lambda d=done: self._update_progress(d, total))

        summary = f"Done: {done}/{total} images → {output_dir}"
        if errors:
            summary += f"  ({errors} errors)"
        self.root.after(0, lambda: self._on_crop_done(summary))

    def _update_progress(self, done: int, total: int) -> None:
        self._progress["value"] = done
        self._status_var.set(f"Processing: {done} / {total}")

    def _on_crop_done(self, summary: str) -> None:
        self._status_var.set(summary)
        self._crop_btn.configure(state=tk.NORMAL)
        messagebox.showinfo("Crop Complete", summary)


def main() -> None:
    root = tk.Tk()
    PanelCropperGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
