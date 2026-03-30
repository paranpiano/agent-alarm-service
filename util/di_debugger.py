"""DI Debugger — Azure Document Intelligence raw result viewer.

Usage:
    python util/di_debugger.py

이미지를 업로드하면 DI가 추출한 paragraphs와 tables를 그대로 보여줍니다.
S540 스테이션 카운트 값이 paragraph로 잡히는지 확인하는 용도입니다.
"""

import io
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk

from dotenv import load_dotenv
from PIL import Image, ImageTk

# Load credentials from server/.env
_ENV_PATH = Path(__file__).resolve().parent.parent / "server" / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
_API_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "")


def _run_di(image_bytes: bytes) -> dict:
    """Run DI on image bytes and return raw paragraphs + tables."""
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential

    client = DocumentAnalysisClient(
        endpoint=_ENDPOINT,
        credential=AzureKeyCredential(_API_KEY),
    )
    poller = client.begin_analyze_document("prebuilt-layout", image_bytes)
    result = poller.result()

    paragraphs = []
    if result.paragraphs:
        for p in result.paragraphs:
            y = 0.0
            try:
                if p.bounding_regions and p.bounding_regions[0].polygon:
                    y = p.bounding_regions[0].polygon[0].y
            except Exception:
                pass
            paragraphs.append({"content": p.content, "y": round(y, 3)})

    tables = []
    if result.tables:
        for t_idx, t in enumerate(result.tables):
            rows: dict[int, list] = {}
            for c in t.cells:
                rows.setdefault(c.row_index, []).append((c.column_index, c.content))
            table_rows = []
            for r_idx in sorted(rows):
                row = [v for _, v in sorted(rows[r_idx])]
                table_rows.append(row)
            tables.append({
                "index": t_idx,
                "rows": t.row_count,
                "cols": t.column_count,
                "data": table_rows,
            })

    return {"paragraphs": paragraphs, "tables": tables}


def _format_result(data: dict) -> str:
    lines = []

    lines.append(f"=== PARAGRAPHS ({len(data['paragraphs'])} total) ===")
    for i, p in enumerate(data["paragraphs"]):
        lines.append(f"  [{i:02d}] y={p['y']:.3f}  \"{p['content']}\"")

    lines.append("")
    lines.append(f"=== TABLES ({len(data['tables'])} total) ===")
    for t in data["tables"]:
        lines.append(f"\n  Table {t['index']} ({t['rows']} rows x {t['cols']} cols):")
        for r_idx, row in enumerate(t["data"]):
            lines.append(f"    row[{r_idx}]: {row}")

    return "\n".join(lines)


class DIDebugger:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("DI Debugger")
        self.root.geometry("1200x750")
        self._photo: ImageTk.PhotoImage | None = None
        self._image_bytes: bytes | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        # Top bar
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Open Image...", command=self._on_open).pack(side=tk.LEFT)
        ttk.Button(top, text="Run DI", command=self._on_run).pack(side=tk.LEFT, padx=6)
        self._status = ttk.Label(top, text="No image loaded")
        self._status.pack(side=tk.LEFT, padx=8)

        # Paned: left = image preview, right = result text
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Image preview
        left = ttk.LabelFrame(paned, text="Image Preview", padding=4)
        self._canvas = tk.Canvas(left, bg="#2b2b2b", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        paned.add(left, weight=1)

        # Result text
        right = ttk.LabelFrame(paned, text="DI Raw Result", padding=4)
        self._text = scrolledtext.ScrolledText(
            right, wrap=tk.NONE, font=("Consolas", 10), state=tk.DISABLED
        )
        self._text.pack(fill=tk.BOTH, expand=True)
        paned.add(right, weight=2)

    def _on_open(self) -> None:
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")],
        )
        if not path:
            return
        self._image_bytes = Path(path).read_bytes()
        self._status.configure(text=Path(path).name)
        self._show_preview(self._image_bytes)
        self._clear_text()

    def _show_preview(self, image_bytes: bytes) -> None:
        img = Image.open(io.BytesIO(image_bytes))
        self.root.update_idletasks()
        w = self._canvas.winfo_width() or 500
        h = self._canvas.winfo_height() or 600
        ratio = min(w / img.width, h / img.height)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self._canvas.delete("all")
        self._canvas.create_image(w // 2, h // 2, image=self._photo, anchor=tk.CENTER)

    def _on_run(self) -> None:
        if not self._image_bytes:
            self._status.configure(text="Load an image first")
            return
        if not _ENDPOINT or not _API_KEY:
            self._set_text("ERROR: DI credentials not found in server/.env")
            return
        self._status.configure(text="Running DI...")
        self._clear_text()
        threading.Thread(target=self._run_di_thread, daemon=True).start()

    def _run_di_thread(self) -> None:
        try:
            data = _run_di(self._image_bytes)
            text = _format_result(data)
            self.root.after(0, lambda: self._set_text(text))
            self.root.after(0, lambda: self._status.configure(
                text=f"Done — {len(data['paragraphs'])} paragraphs, {len(data['tables'])} tables"
            ))
        except Exception as exc:
            self.root.after(0, lambda: self._set_text(f"ERROR: {exc}"))
            self.root.after(0, lambda: self._status.configure(text="Failed"))

    def _set_text(self, text: str) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, text)
        self._text.configure(state=tk.DISABLED)

    def _clear_text(self) -> None:
        self._set_text("")


if __name__ == "__main__":
    root = tk.Tk()
    DIDebugger(root)
    root.mainloop()
