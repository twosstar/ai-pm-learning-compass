from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # optional until OCR dependencies are installed
    fitz = None


def detect_tesseract() -> dict:
    configured = os.getenv("TESSERACT_CMD", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates += [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"D:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"D:\Tesseract-OCR\tesseract.exe"),
        Path(r"D:\AppGallery\tesseract.exe"),
    ]
    candidates += [Path(r"D:\AppGallery\tesseract.exe")]
    executable = shutil.which("tesseract") or next((str(p) for p in candidates if p.exists()), None)
    if not executable:
        return {"available": False, "path": None, "reason": "未找到 tesseract.exe"}
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        languages = subprocess.run([executable, "--list-langs"], capture_output=True, text=True, check=True).stdout.splitlines()
        return {"available": True, "path": executable, "version": version, "languages": languages, "missing_languages": [x for x in ("chi_sim", "eng") if x not in languages]}
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        return {"available": False, "path": executable, "reason": str(exc)}


def extract_pdf_ocr(pdf_path: Path, language: str = "chi_sim+eng", page_numbers: set[int] | None = None) -> list[tuple[int, str]]:
    """OCR selected PDF pages using PyMuPDF rendering and local Tesseract."""
    if fitz is None:
        raise RuntimeError("扫描版 PDF 需要安装 PyMuPDF。")
    detection = detect_tesseract()
    tesseract = detection.get("path")
    if not tesseract:
        raise RuntimeError(f"扫描版 PDF 需要 Tesseract OCR：{detection.get('reason', '未找到 tesseract.exe')}。")
    missing_languages = detection.get("missing_languages") or []
    if missing_languages:
        raise RuntimeError(f"Tesseract 缺少语言包：{', '.join(missing_languages)}。")
    results = []
    with (
        tempfile.TemporaryDirectory(prefix="ai_pm_pdf_ocr_") as tmp,
        fitz.open(str(pdf_path)) as document,
    ):
        selected = page_numbers or set(range(1, document.page_count + 1))
        for number in sorted(selected):
            if number < 1 or number > document.page_count:
                continue
            image = Path(tmp) / f"page-{number}.png"
            document[number - 1].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(str(image))
            result = subprocess.run(
                [tesseract, str(image), "stdout", "-l", language],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            results.append((number, result.stdout.strip()))
    return results
